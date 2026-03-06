"""
Simulate the agent's plan and produce events_to_create, events_to_modify, events_to_delete,
and recommendation_changes for UI display. Does not modify any file or dataframe.
"""

from typing import Any

import pandas as pd


def simulate(
    plan: dict[str, Any],
    reminders_df: pd.DataFrame,
    recommendations_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Interpret plan and return structured preview for display.
    Returns:
      events_to_create: list of would-be rows (id as preview-1, preview-2, ...)
      events_to_modify: list of { id, before: row, after: fields }
      events_to_delete: list of { id, subject, date } for display
      recommendation_changes: list of { client, field, old_value, new_value }
    """
    events_to_create = []
    events_to_modify = []
    events_to_delete = []
    recommendation_changes = []

    # Events to create: build would-be rows with placeholder id
    for i, item in enumerate(plan.get("events_to_create") or []):
        if not isinstance(item, dict):
            continue
        events_to_create.append({
            "id": f"preview-{i + 1}",
            "client": item.get("client", ""),
            "date": item.get("date"),
            "title": item.get("title", ""),
            "amount": item.get("amount"),
        })

    # Events to modify: resolve by id, show before/after
    rem = reminders_df.copy() if reminders_df is not None else pd.DataFrame()
    if not rem.empty and "ReminderId" in rem.columns:
        rem["Date"] = pd.to_datetime(rem["Date"], errors="coerce")
    for item in plan.get("events_to_modify") or []:
        if not isinstance(item, dict):
            continue
        eid = item.get("id")
        fields = item.get("fields") or {}
        if not eid:
            continue
        row = None
        if not rem.empty:
            match = rem[rem["ReminderId"].astype(str) == str(eid)]
            if not match.empty:
                row = match.iloc[0].to_dict()
        events_to_modify.append({
            "id": eid,
            "before": row,
            "after": fields,
        })

    # Events to delete: list id and optional subject/date for display
    for eid in plan.get("events_to_delete") or []:
        if not isinstance(eid, str):
            continue
        row = None
        if not rem.empty:
            match = rem[rem["ReminderId"].astype(str) == eid]
            if not match.empty:
                r = match.iloc[0]
                row = {"id": eid, "subject": str(r.get("Subject", "")), "date": r.get("Date")}
        events_to_delete.append(row or {"id": eid, "subject": "", "date": None})

    # Recommendation changes: resolve old value from recommendations_df
    rec = recommendations_df.copy() if recommendations_df is not None else pd.DataFrame()
    for item in plan.get("recommendation_changes") or []:
        if not isinstance(item, dict):
            continue
        client = item.get("client")
        field = item.get("field")
        new_value = item.get("value")
        if not client or not field:
            continue
        old_value = None
        if not rec.empty and "Client" in rec.columns and field in rec.columns:
            match = rec[rec["Client"].astype(str).str.strip() == str(client).strip()]
            if not match.empty:
                old_value = match.iloc[0].get(field)
        recommendation_changes.append({
            "client": client,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        })

    return {
        "events_to_create": events_to_create,
        "events_to_modify": events_to_modify,
        "events_to_delete": events_to_delete,
        "recommendation_changes": recommendation_changes,
    }
