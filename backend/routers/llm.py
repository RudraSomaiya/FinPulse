import backend.config  # noqa: F401
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from backend.config import PROFILE_PATH, OUTLOOK_PATH
from client_plan_llm import (
    generate_client_plan,
    generate_market_outlook,
    generate_reminder_content,
    retrain_writing_profile,
)

router = APIRouter()


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _write_file(path: str, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---- Writing Profile ----

@router.get("/profile")
def get_profile():
    return {"text": _read_file(PROFILE_PATH)}


# ---- Market Outlook ----

@router.post("/market-outlook")
def market_outlook():
    profile = _read_file(PROFILE_PATH)
    outlook_src = _read_file(OUTLOOK_PATH)
    text = generate_market_outlook(profile, outlook_src)
    return {"text": text}


# ---- Client Plan ----

class ClientPlanRequest(BaseModel):
    context: Dict[str, Any]


@router.post("/client-plan")
def client_plan(req: ClientPlanRequest):
    text = generate_client_plan(req.context)
    return {"text": text}


# ---- Reminder Content ----

class ReminderContentRequest(BaseModel):
    title: str
    prompt: str


@router.post("/reminder-content")
def reminder_content(req: ReminderContentRequest):
    profile = _read_file(PROFILE_PATH)
    text = generate_reminder_content(profile, req.title, req.prompt)
    return {"text": text}


# ---- Retrain Profile ----

class RetrainRequest(BaseModel):
    edited_reminders: List[Dict[str, str]]


@router.post("/retrain-profile")
def retrain_profile(req: RetrainRequest):
    profile = _read_file(PROFILE_PATH)
    new_profile = retrain_writing_profile(profile, req.edited_reminders)
    if new_profile and new_profile != profile:
        # Backup + save
        import shutil, os
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        root, ext = os.path.splitext(PROFILE_PATH)
        shutil.copy2(PROFILE_PATH, f"{root}_backup_{ts}{ext}")
        _write_file(PROFILE_PATH, new_profile)
    return {"text": new_profile, "changed": new_profile != profile}
