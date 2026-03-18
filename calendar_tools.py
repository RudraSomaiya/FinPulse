"""
Get events from reminders and create/update/delete reminder rows.
Persistence to reminders.xlsx only when caller invokes data_manager.save_reminders after mutations.
"""

from datetime import date, datetime
from typing import Any

import pandas as pd


def get_events(
    reminders_df: pd.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """
    Return list of events from reminders_df as { id, date, subject, content }.
    Optionally filter by start_date and end_date (inclusive).
    """
    if reminders_df is None or reminders_df.empty:
        return []
    df = reminders_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    if start_date is not None:
        df = df[df["Date"].dt.date >= start_date]
    if end_date is not None:
        df = df[df["Date"].dt.date <= end_date]
    events = []
    for _, row in df.iterrows():
        events.append(
            {
                "id": str(row.get("ReminderId", "")),
                "date": row["Date"].date() if hasattr(row["Date"], "date") else row["Date"],
                "subject": str(row.get("Subject", "")),
                "content": str(row.get("Content", "")),
            }
        )
    return events


def create_event(
    client: str,
    date_val: date | datetime,
    title: str,
    amount: float | None = None,
    reminders_df: pd.DataFrame | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """
    Build a new reminder row (ReminderId, Date, Subject, Content).
    If reminders_df is provided, append in-memory and return the new row; caller must persist.
    Otherwise return the row dict for preview only (no ReminderId needed for preview).
    """
    from datetime import datetime as dt

    ts = int(dt.now().timestamp() * 1000)
    seq = len(reminders_df) + 1 if reminders_df is not None and not reminders_df.empty else 1
    rid = f"R-{ts}-{seq}"
    
    if content:
        final_content = content.strip()
    else:
        final_content = str(client or "").strip()
        if amount is not None:
            final_content = f"{final_content}\nAmount: {amount}" if final_content else f"Amount: {amount}"
            
    row = {
        "ReminderId": rid,
        "Date": pd.Timestamp(date_val),
        "Subject": (title or "").strip() or "Reminder",
        "Content": final_content.strip(),
        "Edited": "0",
        "Date of edit": pd.NaT,
    }
    if reminders_df is not None:
        new_df = pd.concat(
            [reminders_df, pd.DataFrame([row])],
            ignore_index=True,
        )
        return {"row": row, "reminders_df": new_df}
    return {"row": row, "reminders_df": None}


def update_event(
    event_id: str,
    fields: dict[str, Any],
    reminders_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Find row by ReminderId == event_id, apply fields (Date, Subject, Content), return modified dataframe.
    Caller must call data_manager.save_reminders to persist.
    """
    if reminders_df is None or reminders_df.empty:
        return reminders_df
    mask = reminders_df["ReminderId"].astype(str) == str(event_id).strip()
    if not mask.any():
        return reminders_df
    out = reminders_df.copy()
    for key in ("Date", "Subject", "Content"):
        if key in fields:
            out.loc[mask, key] = fields[key]
    if "Date" in fields:
        out.loc[mask, "Date"] = pd.to_datetime(out.loc[mask, "Date"], errors="coerce")
    return out


def delete_event(event_id: str, reminders_df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop row(s) with ReminderId == event_id; return new dataframe. Caller must save.
    """
    if reminders_df is None or reminders_df.empty:
        return reminders_df
    mask = reminders_df["ReminderId"].astype(str) != str(event_id).strip()
    return reminders_df[mask].reset_index(drop=True)
