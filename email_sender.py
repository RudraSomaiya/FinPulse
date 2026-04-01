import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

def send_client_report(client_email: str, market_outlook: str | None, future_plan: str | None) -> bool:
    """Send generated reports (Market Outlook and/or Future Plan) to client email."""
    if not GMAIL_EMAIL or not GMAIL_APP_PASSWORD:
        raise ValueError("Missing GMAIL_EMAIL or GMAIL_APP_PASSWORD in .env")

    subject = "Your Market Outlook & Investment Review"
    
    body_parts = []
    body_parts.append("Hello,")
    body_parts.append("Please find your personalized market and portfolio updates below.\n")

    if market_outlook:
        body_parts.append("=== Market Outlook ===")
        body_parts.append(market_outlook)
        body_parts.append("")

    if future_plan:
        body_parts.append("=== Future Plan (AI Advisor) ===")
        body_parts.append(future_plan)
        body_parts.append("")

    body_parts.append("Best regards,")
    body_parts.append("Your Financial Advisor")

    return send_email(client_email, subject, "\n".join(body_parts))

def send_reminder_email(client_email: str, subject: str, content: str) -> bool:
    """Send a specific reminder to a client."""
    if not GMAIL_EMAIL or not GMAIL_APP_PASSWORD:
        raise ValueError("Missing GMAIL_EMAIL or GMAIL_APP_PASSWORD in .env")
        
    # If subject is missing, use "Test email" as requested by user for blank subjects
    final_subject = subject.strip() if subject else "Test email"
    
    return send_email(client_email, final_subject, content)

def send_email(to_email: str, subject: str, body: str) -> bool:
    if not GMAIL_EMAIL or not GMAIL_APP_PASSWORD:
        raise ValueError("Missing Google credentials in .env file.")
        
    msg = MIMEMultipart()
    msg['From'] = GMAIL_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        text = msg.as_string()
        server.sendmail(GMAIL_EMAIL, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {str(e)}")
        raise e
