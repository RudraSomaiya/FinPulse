import backend.config  # noqa: F401
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import email_sender
import whatsapp_sender

router = APIRouter()


class ClientReportRequest(BaseModel):
    recipient: str          # email or phone
    market_outlook: Optional[str] = None
    future_plan: Optional[str] = None


class ReminderMessageRequest(BaseModel):
    recipient: str
    subject: str
    content: str


@router.post("/email/report")
def send_email_report(req: ClientReportRequest):
    try:
        email_sender.send_client_report(req.recipient, req.market_outlook, req.future_plan)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email/reminder")
def send_email_reminder(req: ReminderMessageRequest):
    try:
        email_sender.send_reminder_email(req.recipient, req.subject, req.content)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whatsapp/report")
def send_whatsapp_report(req: ClientReportRequest):
    try:
        whatsapp_sender.send_client_report(req.recipient, req.market_outlook, req.future_plan)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whatsapp/reminder")
def send_whatsapp_reminder(req: ReminderMessageRequest):
    try:
        whatsapp_sender.send_reminder_message(req.recipient, req.subject, req.content)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
