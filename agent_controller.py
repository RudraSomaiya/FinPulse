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


def _build_data_context(
    client_df: pd.DataFrame,
    reminders_df: pd.DataFrame,
    today: date,
    tx_df: pd.DataFrame | None = None,
) -> str:
    """Run read-only tools and build a context string for the LLM.
    Uses Recommended_ProductType only for product-type lists (so 'ETF clients' = clients we recommend ETF to).
    """
    lines = [f"Today's date: {today.isoformat()}"]

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
            # Full list of this product type's clients with birth dates this year (for "wish X on birthdays" queries)
            bd_sub = get_birthdays(sub, year=today.year)
            if not bd_sub.empty and "Client" in bd_sub.columns and "birth_date" in bd_sub.columns:
                rows = bd_sub.apply(lambda r: f"{r['Client']} ({r['birth_date']})", axis=1).tolist()
                lines.append(f"All {ptype} clients with birth dates in {today.year}: {', '.join(rows)}")
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
        col_prod_name = "Product Name"
        col_amt = "Transaction Amount (SGD)"
        col_date = "Transaction Date"

        lines.append(f"Total transaction rows: {len(tx_df)}")

        # Per-product-type aggregation
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

        # Per-client summary: first purchase, last purchase, products, total amount
        # This is the KEY data the LLM needs for queries like "1 year after first purchase"
        if col_client in tx_df.columns and col_date in tx_df.columns:
            tx_dated = tx_df.copy()
            tx_dated[col_date] = pd.to_datetime(tx_dated[col_date], errors="coerce")
            lines.append("\nPer-client transaction summary (first_purchase | last_purchase | products | total_amount | txn_count):")
            for cid, grp in tx_dated.groupby(col_client):
                cid_str = str(cid).strip()
                dated = grp.dropna(subset=[col_date])
                if dated.empty:
                    first_dt = "-"
                    last_dt = "-"
                else:
                    first_dt = dated[col_date].min().strftime("%Y-%m-%d")
                    last_dt = dated[col_date].max().strftime("%Y-%m-%d")
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
                    f"  {cid_str}: first={first_dt} | last={last_dt} | "
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
    data_ctx = _build_data_context(client_df, reminders_df, today, tx_df=tx_df)

    prompt = f"""You are a data-aware AI agent that manages a client recommendation dataset, a calendar (reminders), and has access to actual transaction history.
You must output a JSON execution plan. No changes are applied until the user confirms.

SCHEMAS:
- Recommendation columns: {', '.join(rec_schema)}
- Reminder columns: {', '.join(rem_schema)}
- Transaction history columns: {', '.join(tx_schema)}

DATA CONTEXT (use these exact client IDs and dates; do not invent clients):
{data_ctx}

When the user asks about past purchases, transaction history, first/last purchase dates, or "who bought X", you MUST use the "Per-client transaction summary" in the TRANSACTION HISTORY section above. Each line shows: client_id: first=YYYY-MM-DD | last=YYYY-MM-DD | products=... | total=... | count=N. Use the "first" date for first purchase queries and the "last" date for last/recent purchase queries. When they ask about recommended products or model predictions, use the Recommendation data.

USER REQUEST:
{user_query}

For ANY request about birthdays or birthdates (e.g. "wish X on birthdays", "call clients on their birthdates"): use the exact list "All X clients with birth dates in YYYY" from DATA CONTEXT. For each event that is on a client's birth date you MUST set "use_client_birthdate": true so the system uses the real date from the data; do not invent or guess dates.

For ANY request of the form "top K <PRODUCT> clients" (for example "top 7 STOCK clients by number of transactions"), you MUST:
- Treat K as the requested number.
- Look at the "<PRODUCT> clients by Recommended_ProductType ordered by Total_Transactions (first N of TOTAL): ..." line in DATA CONTEXT.
- Select the first min(K, TOTAL) distinct client IDs from that ordered list and create events for ALL of them. Do NOT arbitrarily cap this at 3.

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
