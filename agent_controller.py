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
    load_reminders,
)
from calendar_tools import get_events
from llm_router import ask_llm


PLAN_JSON_SCHEMA = """
Return a single JSON object with exactly these keys (use empty arrays where nothing to do):
- "reasoning": string (brief explanation of what you will do)
- "events_to_create": [ {"client": string, "date": "YYYY-MM-DD", "title": string, "amount": number or null} ]
- "events_to_modify": [ {"id": string (ReminderId), "fields": {"Date": "YYYY-MM-DD"|null, "Subject": string|null, "Content": string|null} } ]
- "events_to_delete": [ string ] (list of ReminderIds)
- "recommendation_changes": [ {"client": string, "field": string (e.g. Recommended_Amount_P50), "value": number|string} ]

Dates must be YYYY-MM-DD. For recommendation_changes, field can be Recommended_Amount_P50, Recommended_Amount_P10, Recommended_Amount_P90, or Recommended_ProductType.
"""


def _build_data_context(
    client_df: pd.DataFrame,
    reminders_df: pd.DataFrame,
    today: date,
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
        # Top 3 and "All X with birth dates" for every product type in the data (ETF, STOCK, BOND, DPMS, UT, etc.)
        for ptype in types:
            sub = filter_clients_by_recommended_product(ptype, client_df)
            if sub.empty:
                continue
            if "Client" in sub.columns and "Total_Transactions" in sub.columns:
                one_per_client = sub.sort_values("Total_Transactions", ascending=False, na_position="last").drop_duplicates(subset=["Client"], keep="first")
                top = one_per_client.head(3)
            else:
                top = sub.head(3)
            clients = top["Client"].astype(str).tolist() if "Client" in top.columns else []
            if clients:
                lines.append(f"Top 3 {ptype} clients by Recommended_ProductType (by Total_Transactions): {', '.join(clients)}")
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


def generate_plan(
    user_query: str,
    client_df: pd.DataFrame | None = None,
    reminders_df: pd.DataFrame | None = None,
    today: date | None = None,
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

    rec_schema = get_recommendation_schema()
    rem_schema = get_reminder_schema()
    data_ctx = _build_data_context(client_df, reminders_df, today)

    prompt = f"""You are a data-aware AI agent that manages a client recommendation dataset and a calendar (reminders).
You must output a JSON execution plan. No changes are applied until the user confirms.

SCHEMAS:
- Recommendation columns: {', '.join(rec_schema)}
- Reminder columns: {', '.join(rem_schema)}

DATA CONTEXT (use these exact client IDs and dates; do not invent clients):
{data_ctx}

USER REQUEST:
{user_query}

For "wish X clients on their birthdays" (X = any product type: ETF, STOCK, BOND, DPMS, UT, etc.): use the exact list "All X clients with birth dates in YYYY" from DATA CONTEXT to create one event per client on that client's birth_date, with a title like "Birthday wish – <Client>".
{PLAN_JSON_SCHEMA}

Output only the JSON object, no other text."""

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
