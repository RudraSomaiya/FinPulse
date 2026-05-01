import backend.config  # noqa: F401
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import date
import pandas as pd

from backend.config import REC_PATH, REM_PATH
from data_manager import load_recommendations, load_reminders, save_reminders, save_recommendations
from agent_controller import generate_plan
from calendar_tools import create_event as cal_create_event, update_event as cal_update_event, delete_event as cal_delete_event
from client_tools import get_client_birth_date

router = APIRouter()


class PlanRequest(BaseModel):
    query: str
    profile_text: Optional[str] = None


class ConfirmRequest(BaseModel):
    plan: Dict[str, Any]


@router.post("/plan")
def get_plan(req: PlanRequest):
    client_df = load_recommendations(REC_PATH)
    reminders_df = load_reminders(REM_PATH)
    plan = generate_plan(
        req.query,
        client_df=client_df,
        reminders_df=reminders_df,
        profile_text=req.profile_text,
    )
    return plan


@router.post("/confirm")
def confirm_plan(req: ConfirmRequest):
    plan = req.plan
    rec_df = load_recommendations(REC_PATH)
    rem_df = load_reminders(REM_PATH)

    for item in plan.get("events_to_create") or []:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        client_id = (item.get("client") or "").strip()
        use_birthdate = item.get("use_client_birthdate") is True
        birth_keywords = ("birthday", "birthdate", "birth date", "on their birth", "wish on birth")
        if not use_birthdate and title:
            use_birthdate = any(kw in title.lower() for kw in birth_keywords)

        d = None
        if use_birthdate and client_id and "Client_Birthdate" in rec_df.columns:
            d = get_client_birth_date(client_id, rec_df, date.today().year)
        if d is None:
            d_raw = item.get("date")
            if isinstance(d_raw, str):
                d = pd.to_datetime(d_raw).date() if d_raw else date.today()
            elif d_raw is not None and hasattr(d_raw, "date"):
                d = d_raw.date()
            else:
                d = date.today()

        result = cal_create_event(
            client_id,
            d,
            item.get("title", "Reminder"),
            item.get("amount"),
            reminders_df=rem_df,
            content=item.get("content"),
        )
        if result.get("reminders_df") is not None:
            rem_df = result["reminders_df"]

    for item in plan.get("events_to_modify") or []:
        if isinstance(item, dict) and item.get("id") and item.get("fields"):
            rem_df = cal_update_event(item["id"], item["fields"], rem_df)

    for eid in plan.get("events_to_delete") or []:
        if isinstance(eid, str):
            rem_df = cal_delete_event(eid, rem_df)

    for item in plan.get("recommendation_changes") or []:
        if isinstance(item, dict) and item.get("client") and item.get("field") is not None:
            mask = rec_df["Client"].astype(str).str.strip() == str(item["client"]).strip()
            if mask.any() and item["field"] in rec_df.columns:
                rec_df.loc[mask, item["field"]] = item.get("value")

    save_reminders(rem_df, REM_PATH)
    if plan.get("recommendation_changes"):
        save_recommendations(rec_df, REC_PATH)

    return {"ok": True}
