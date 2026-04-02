"""
WhatsApp sender using the official Meta WhatsApp Business Cloud API.

Required .env variables:
    WHATSAPP_API_TOKEN       – Permanent or temporary access token from Meta Business
    WHATSAPP_PHONE_NUMBER_ID – The Phone-Number-ID assigned to your WhatsApp Business number
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")


def _normalize_phone(phone: str) -> str:
    """Strip spaces, dashes, parentheses and ensure the number starts with a country code (no '+')."""
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    # Remove leading '+' – the API expects digits only
    if phone.startswith("+"):
        phone = phone[1:]
    return phone


def send_text_message(to_phone: str, body: str) -> bool:
    """Send a plain-text WhatsApp message to *to_phone* via the Cloud API.

    Raises ValueError when credentials are missing and generic Exception on API errors.
    Returns True on success.
    """
    if not WHATSAPP_API_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise ValueError(
            "Missing WHATSAPP_API_TOKEN or WHATSAPP_PHONE_NUMBER_ID in .env"
        )

    phone = _normalize_phone(to_phone)
    if not phone:
        raise ValueError("Phone number is empty after normalisation.")

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": body},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code not in (200, 201):
        detail = resp.text
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            pass
        raise Exception(f"WhatsApp API error ({resp.status_code}): {detail}")

    return True


def send_client_report(
    client_phone: str,
    market_outlook: str | None,
    future_plan: str | None,
) -> bool:
    """Compose and send a client report via WhatsApp."""
    parts = ["Hello,\n\nPlease find your personalised updates below.\n"]

    if market_outlook:
        parts.append("=== Market Outlook ===")
        parts.append(market_outlook)
        parts.append("")

    if future_plan:
        parts.append("=== Future Plan (AI Advisor) ===")
        parts.append(future_plan)
        parts.append("")

    parts.append("Best regards,\nYour Financial Advisor")

    return send_text_message(client_phone, "\n".join(parts))


def send_reminder_message(client_phone: str, subject: str, content: str) -> bool:
    """Send a reminder over WhatsApp."""
    final_subject = subject.strip() if subject else "Reminder"
    body = f"*{final_subject}*\n\n{content}"
    return send_text_message(client_phone, body)
