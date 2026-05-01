import sys
import os

# Add root FinPulse directory to Python path so existing modules can be imported
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# File paths
REC_PATH = os.path.join(ROOT, "recommendationOutput.xlsx")
REM_PATH = os.path.join(ROOT, "reminders.xlsx")
TX_PATH = os.path.join(ROOT, "cleaned_data.xlsx")
CLIENT_DETAILS_PATH = os.path.join(ROOT, "client-details.xlsx")
PROFILE_PATH = os.path.join(ROOT, "jonathan-writing-profile.txt")
OUTLOOK_PATH = os.path.join(ROOT, "marketoutlook-temporary.txt")
