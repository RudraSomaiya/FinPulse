"""
Central AI brain: receive user query, inspect schema, reason via LLM, produce execution plan.
Never writes to disk; only read-only tools are run to feed the LLM. Plan is preview-only until user confirms.

Example queries the agent handles:
1) "Schedule meetings with top 3 stock clients tomorrow"
   -> get_top_clients(3) on dataframe filtered by filter_clients_by_product("STOCK"); resolve tomorrow;
      plan events_to_create with one event per client, date = tomorrow.

2) "Wish ETF clients on their birthdays this year"
   -> filter_clients_by_product("ETF") + get_birthdays(df, year=current_year);
      plan events_to_create for each (client, birthday_date) with title "Birthday wish – {client}".

3) "Remove all meetings on Mondays"
   -> get_events(reminders_df); filter where date.weekday() == 0; plan events_to_delete with those ReminderIds.

4) "Add entries for client B10 during second week of July except Wednesday"
   -> Compute date range (second week of July), exclude Wednesday; plan events_to_create for B10 on each date.

5) "Change the recommended amount for B56 to 12000"
   -> plan recommendation_changes: client B56, field Recommended_Amount_P50, value 12000;
      on commit, apply via amount_set and save_recommendations.
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from client_tools import (
    filter_clients_by_product,
    filter_clients_by_recommended_product,
    get_birthdays,
    get_high_value_clients,
    get_top_clients,
)
from data_manager import (
    get_recommendation_schema,
    get_reminder_schema,
    get_transaction_schema,
    load_reminders,
    load_transactions,
)
from calendar_tools import get_events
from llm_router import ask_llm


PLAN_JSON_SCHEMA = """
Return a single JSON object with exactly these keys (use empty arrays where nothing to do):
- "reasoning": string (brief explanation of what you will do)
- "events_to_create": [ {"client": string, "date": "YYYY-MM-DD", "title": string, "amount": number or null, "use_client_birthdate": true|false, "content": string|null} ]
  For ANY event that is scheduled on a client's birth date (birthday wish, call on birthdate, etc.) you MUST set "use_client_birthdate": true. The system will then use the Client_Birthdate from the data (DD/MM) and ignore your "date" value. Do not invent dates for birthdate events.
  If the user's request explicitly asks to generate content (e.g. draft an email, prepare notes) for the reminders being created, generate the requested text and put it in the "content" field. If they ask for content for ALL reminders, generate tailored content for each. If for specific reminders, selectively generate it. If no content generation is requested, leave "content" as null.
- "events_to_modify": [ {"id": string (ReminderId), "fields": {"Date": "YYYY-MM-DD"|null, "Subject": string|null, "Content": string|null} } ]
- "events_to_delete": [ string ] (list of ReminderIds)
- "recommendation_changes": [ {"client": string, "field": string (e.g. Recommended_Amount_P50), "value": number|string} ]

Dates must be YYYY-MM-DD. For recommendation_changes, field can be Recommended_Amount_P50, Recommended_Amount_P10, Recommended_Amount_P90, or Recommended_ProductType.
"""


def _extract_mentioned_clients(query: str, client_df: pd.DataFrame) -> set[str]:
    """Extract client IDs explicitly mentioned in the user query (e.g. B10, B56).
    Uses word-boundary matching to avoid false positives (B10 should not match B1 or B100).
    """
    mentioned = set()
    if client_df is not None and not client_df.empty and "Client" in client_df.columns:
        all_ids = {str(c).strip() for c in client_df["Client"].dropna().unique()}
        for cid in all_ids:
            if cid and re.search(rf'\b{re.escape(cid)}\b', query):
                mentioned.add(cid)
    return mentioned


def _build_data_context(
    client_df: pd.DataFrame,
    reminders_df: pd.DataFrame,
    today: date,
    tx_df: pd.DataFrame | None = None,
    query: str = "",
) -> str:
    """Run read-only tools and build a context string for the LLM.
    Uses Recommended_ProductType only for product-type lists (so 'ETF clients' = clients we recommend ETF to).

    When transaction data is provided, context is built in two tiers:
    - ALWAYS: compact per-product-type cross-references (client lists with first/last tx dates)
    - SELECTIVELY: full per-client TX details only for clients explicitly named in the query
    This keeps context compact for bulk queries while providing detail for specific client lookups.
    """
    lines = [f"Today's date: {today.isoformat()}"]
    mentioned_clients = _extract_mentioned_clients(query, client_df) if query else set()

    if client_df is not None and not client_df.empty:
        if "Recommended_ProductType" in client_df.columns:
            types = sorted({str(t).strip() for t in client_df["Recommended_ProductType"].dropna().astype(str).unique().tolist() if str(t).strip()})
            lines.append(f"Product types in data: {', '.join(types)}")
        else:
            types = []
        # Ordered lists and "All X with birth dates" for every product type in the data (ETF, STOCK, BOND, DPMS, UT, etc.)
        for ptype in types:
            sub = filter_clients_by_recommended_product(ptype, client_df)
            if sub.empty:
                continue
            if "Client" in sub.columns and "Total_Transactions" in sub.columns:
                one_per_client = sub.sort_values("Total_Transactions", ascending=False, na_position="last").drop_duplicates(subset=["Client"], keep="first")
                total_count = len(one_per_client)
                sample = one_per_client.head(min(25, total_count))
            else:
                total_count = len(sub)
                sample = sub.head(min(25, total_count))
            clients = sample["Client"].astype(str).tolist() if "Client" in sample.columns else []
            if clients:
                lines.append(
                    f"{ptype} clients by Recommended_ProductType ordered by Total_Transactions "
                    f"(first {len(clients)} of {total_count}): {', '.join(clients)}"
                )
            # Full list of this product type's clients with birth dates this year
            bd_sub = get_birthdays(sub, year=today.year)
            if not bd_sub.empty and "Client" in bd_sub.columns and "birth_date" in bd_sub.columns:
                rows = bd_sub.apply(lambda r: f"{r['Client']} ({r['birth_date']})", axis=1).tolist()
                lines.append(f"All {ptype} clients with birth dates in {today.year}: {', '.join(rows)}")
            # Compact cross-reference: product-type clients with first and last transaction dates
            if tx_df is not None and not tx_df.empty and "Client number" in tx_df.columns and "Transaction Date" in tx_df.columns:
                tx_dated = tx_df.copy()
                tx_dated["Transaction Date"] = pd.to_datetime(tx_dated["Transaction Date"], errors="coerce")
                tx_dated_clean = tx_dated.dropna(subset=["Transaction Date"])
                tx_agg = tx_dated_clean.groupby("Client number")["Transaction Date"].agg(["min", "max"]).reset_index()
                tx_agg.columns = ["Client", "first_tx", "last_tx"]
                tx_agg["Client"] = tx_agg["Client"].astype(str).str.strip()
                ptype_client_ids = set(c.strip() for c in clients)
                tx_ptype = tx_agg[tx_agg["Client"].isin(ptype_client_ids)].copy()
                if not tx_ptype.empty:
                    tx_rows = []
                    for _, tr in tx_ptype.sort_values("first_tx").iterrows():
                        tx_rows.append(
                            f"{tr['Client']} (first_tx={tr['first_tx'].strftime('%Y-%m-%d')}, last_tx={tr['last_tx'].strftime('%Y-%m-%d')})"
                        )
                    lines.append(f"All {ptype} clients with transaction dates: {', '.join(tx_rows)}")
        # General birthdays this year (all clients, sample if many)
        bd = get_birthdays(client_df, year=today.year)
        if not bd.empty and "Client" in bd.columns and "birth_date" in bd.columns:
            rows = bd.apply(lambda r: f"{r['Client']} ({r['birth_date']})", axis=1).tolist()
            if len(rows) > 30:
                rows = rows[:30]
                lines.append(f"Birthdays this year (first 30 clients): {', '.join(rows)}")
            else:
                lines.append(f"Birthdays this year (all): {', '.join(rows)}")
        lines.append(f"Total clients in recommendation dataset: {len(client_df)}")

    if reminders_df is not None and not reminders_df.empty:
        events = get_events(reminders_df)
        monday_events = [e for e in events if e.get("date") and (e["date"].weekday() == 0 if hasattr(e["date"], "weekday") else False)]
        if monday_events:
            ids = [e["id"] for e in monday_events if e.get("id")]
            lines.append(f"Reminder IDs on Mondays (for 'remove Mondays'): {ids}")
        lines.append(f"Total reminders: {len(events)}")
        if events:
            sample = events[:5]
            lines.append("Sample reminders: " + "; ".join(f"{e.get('id')} on {e.get('date')} - {e.get('subject')}" for e in sample))
    # --- Transaction history from cleaned_data.xlsx ---
    if tx_df is not None and not tx_df.empty:
        lines.append("\n--- TRANSACTION HISTORY (cleaned_data.xlsx) ---")
        col_client = "Client number"
        col_prod = "Product Type"
        col_amt = "Transaction Amount (SGD)"
        col_date = "Transaction Date"

        lines.append(f"Total transaction rows: {len(tx_df)}")

        # Per-product-type aggregation (always included — compact)
        if col_prod in tx_df.columns:
            prod_agg = tx_df.groupby(col_prod).agg(
                count=(col_prod, "size"),
                total_sgd=(col_amt, "sum") if col_amt in tx_df.columns else (col_prod, "size"),
            ).reset_index()
            prod_lines = []
            for _, pr in prod_agg.iterrows():
                ptype = str(pr[col_prod]).strip()
                cnt = int(pr["count"])
                total = pr.get("total_sgd")
                if total is not None and col_amt in tx_df.columns:
                    prod_lines.append(f"{ptype}: {cnt} txns, total {float(total):,.0f} SGD")
                else:
                    prod_lines.append(f"{ptype}: {cnt} txns")
            lines.append("Product type breakdown: " + "; ".join(prod_lines))

        # Detailed per-client TX summary — ONLY for clients explicitly named in the query
        # Bulk queries ("all ETF clients") use the compact per-product cross-references above instead
        if mentioned_clients and col_client in tx_df.columns and col_date in tx_df.columns:
            tx_dated = tx_df.copy()
            tx_dated[col_date] = pd.to_datetime(tx_dated[col_date], errors="coerce")
            lines.append("\nDetailed transaction summary for mentioned clients:")
            for cid in sorted(mentioned_clients):
                grp = tx_dated[tx_dated[col_client].astype(str).str.strip() == cid]
                if grp.empty:
                    lines.append(f"  {cid}: no transactions found")
                    continue
                dated = grp.dropna(subset=[col_date])
                first_dt = dated[col_date].min().strftime("%Y-%m-%d") if not dated.empty else "-"
                last_dt = dated[col_date].max().strftime("%Y-%m-%d") if not dated.empty else "-"
                products = sorted({str(p).strip() for p in grp[col_prod].dropna().astype(str).tolist()}) if col_prod in grp.columns else []
                total_amt = None
                if col_amt in grp.columns and not grp[col_amt].isna().all():
                    try:
                        total_amt = float(grp[col_amt].sum())
                    except Exception:
                        total_amt = None
                amt_s = f"{total_amt:,.0f} SGD" if total_amt is not None else "-"
                cnt = len(grp)
                lines.append(
                    f"  {cid}: first={first_dt} | last={last_dt} | "
                    f"products={', '.join(products) if products else '-'} | "
                    f"total={amt_s} | count={cnt}"
                )

    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from LLM response (handle markdown code blocks)."""
    text = (text or "").strip()
    if not text:
        return {}
    # Strip ```json ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first { ... }
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
    return {}


def _needs_transaction_data(query: str) -> bool:
    """Lightweight keyword check: does the user query need actual transaction history?

    Returns True when the query references past purchases, transaction amounts,
    first/last buys, specific contract details, or similar historical data.
    Returns False for simple scheduling, birthday wishes, or recommendation edits
    — keeping the LLM context small and saving tokens.
    """
    q = (query or "").lower()
    triggers = [
        "transaction", "purchase", "bought", "first buy", "last buy",
        "first purchase", "last purchase", "transacted", "spending",
        "historical", "history", "past investment", "past purchase",
        "contract", "account no", "fund house", "issuer", "exchange",
        "payment method", "transaction mode", "transaction amount",
        "transaction date", "cleaned_data", "cleaned data",
        "how much did", "what did", "when did", "product name",
        "total spent", "total invested", "invested amount",
        "first investment", "recent investment", "recent purchase",
        "years after", "year after", "months after", "month after",
        "anniversary", "since their", "since first", "since last",
        "after their first", "after their last", "after first", "after last",
    ]
    return any(t in q for t in triggers)


def generate_plan(
    user_query: str,
    client_df: pd.DataFrame | None = None,
    reminders_df: pd.DataFrame | None = None,
    today: date | None = None,
    profile_text: str | None = None,
    tx_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Receive user query and optional data; run read-only tools to build context;
    call LLM to produce execution plan (JSON). Return plan dict for preview_engine and app.
    Never writes to disk.
    """
    today = today or date.today()
    if client_df is None:
        from data_manager import get_client_dataframe
        client_df = get_client_dataframe()
    if reminders_df is None:
        reminders_df = load_reminders()

    # Smart gate: only load/include transaction data when the query actually needs it
    use_tx = _needs_transaction_data(user_query)
    if use_tx:
        if tx_df is None:
            tx_df = load_transactions()
    else:
        tx_df = None  # intentionally skip to save tokens

    rec_schema = get_recommendation_schema()
    rem_schema = get_reminder_schema()
    tx_schema = get_transaction_schema()
    data_ctx = _build_data_context(client_df, reminders_df, today, tx_df=tx_df, query=user_query)

    prompt = f"""You are a data-aware AI agent that manages a client recommendation dataset, a calendar (reminders), and has access to actual transaction history.
You must output a JSON execution plan. No changes are applied until the user confirms.

SCHEMAS:
- Recommendation columns: {', '.join(rec_schema)}
- Reminder columns: {', '.join(rem_schema)}
- Transaction history columns: {', '.join(tx_schema)}

DATA CONTEXT (use these exact client IDs and dates; do not invent clients):
{data_ctx}

USER REQUEST:
{user_query}

INSTRUCTIONS:
1. The DATA CONTEXT above contains several data sources. You MUST cross-reference them as needed:
   - "<PRODUCT> clients by Recommended_ProductType ..." — client lists per product type.
   - "All <PRODUCT> clients with transaction dates: ..." — each product-type client's first_tx and last_tx dates.
   - "All <PRODUCT> clients with birth dates in YYYY: ..." — birth dates.
   - "Detailed transaction summary for mentioned clients:" — full TX details for specifically named clients.
   Use whichever sources are relevant to resolve the user's request. Combine and cross-reference them as needed.

2. When the request involves a group of clients (e.g. "all ETF clients", "top 5 STOCK clients"), you MUST create events for ALL matching clients from the DATA CONTEXT, not just a sample.

3. When the request involves date arithmetic relative to transaction dates (e.g. "2 years after first transaction", "6 months after last purchase"), compute the target date for EACH client individually using their first_tx or last_tx from the data. Dates in the past are acceptable.

4. For ANY event on a client's birthdate, you MUST set "use_client_birthdate": true. The system will use the real Client_Birthdate from the data. Do not invent birth dates.

5. NEVER return an empty plan or "-" as reasoning when the data to fulfill the request is present in the DATA CONTEXT.

{PLAN_JSON_SCHEMA}
"""
    if profile_text:
        prompt += f"\nWRITING STYLE PROFILE (GUIDELINES):\nIf you choose to generate 'content' for reminders, you must strictly follow the tone, style, greetings, and formatting laid out in this profile:\n{profile_text.strip()}\n"

    prompt += "\nOutput only the JSON object, no other text."

    response = ask_llm(prompt)
    plan = _extract_json(response)

    # Normalize to expected keys
    return {
        "reasoning": plan.get("reasoning", ""),
        "events_to_create": plan.get("events_to_create") or [],
        "events_to_modify": plan.get("events_to_modify") or [],
        "events_to_delete": plan.get("events_to_delete") or [],
        "recommendation_changes": plan.get("recommendation_changes") or [],
    }
