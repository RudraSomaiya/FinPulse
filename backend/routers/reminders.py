import backend.config  # noqa: F401
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import pandas as pd

from backend.config import REM_PATH
from backend.serializers import df_to_records
from data_manager import load_reminders, save_reminders
from calendar_tools import create_event as cal_create_event, update_event as cal_update_event, delete_event as cal_delete_event

router = APIRouter()


class CreateReminderRequest(BaseModel):
    client: str
    date: str  # YYYY-MM-DD
    title: str
    content: Optional[str] = None
    amount: Optional[float] = None


class UpdateReminderRequest(BaseModel):
    subject: Optional[str] = None
    content: Optional[str] = None


class DeleteRemindersRequest(BaseModel):
    ids: List[str]


@router.get("")
def get_reminders():
    df = load_reminders(REM_PATH)
    return df_to_records(df)


@router.post("")
def create_reminder(req: CreateReminderRequest):
    df = load_reminders(REM_PATH)
    target_date = pd.to_datetime(req.date).date()
    result = cal_create_event(
        req.client,
        target_date,
        req.title,
        req.amount,
        reminders_df=df,
        content=req.content,
    )
    new_df = result.get("reminders_df", df)
    save_reminders(new_df, REM_PATH)
    return {"ok": True}


@router.put("/{reminder_id}")
def update_reminder(reminder_id: str, req: UpdateReminderRequest):
    df = load_reminders(REM_PATH)
    fields = {}
    if req.subject is not None:
        fields["Subject"] = req.subject
    if req.content is not None:
        fields["Content"] = req.content
    fields["Edited"] = "1"
    fields["Date of edit"] = datetime.now().isoformat()
    new_df = cal_update_event(reminder_id, fields, df)
    save_reminders(new_df, REM_PATH)
    return {"ok": True}


@router.delete("")
def delete_reminders(req: DeleteRemindersRequest):
    df = load_reminders(REM_PATH)
    for rid in req.ids:
        df = cal_delete_event(rid, df)
    save_reminders(df, REM_PATH)
    return {"ok": True}
