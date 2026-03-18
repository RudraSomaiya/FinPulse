"""
Central load/save for recommendation and reminder datasets.
Single source of column/schema usage for the agent; no Streamlit cache here.
"""

import os
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

DEFAULT_REC_PATH = "recommendationOutput.xlsx"
DEFAULT_REM_PATH = "reminders.xlsx"


def get_recommendation_schema() -> list[str]:
    """Return column names for the recommendation dataset (for agent schema prompts)."""
    return [
        "Client",
        "Cluster",
        "Current_ProductType",
        "Current_ProductType_Date",
        "Current_ProductType_Amount",
        "Recommended_ProductType",
        "Confidence",
        "Predicted_Amount_SGD",
        "Recommended_Amount_P10",
        "Recommended_Amount_P50",
        "Recommended_Amount_P90",
        "Predicted_Purchase_Date",
        "Avg_Historical_Amount",
        "Total_Transactions",
        "Top_10pct_Buyer",
        "First_Investment_Date",
        "Total_Invested_SGD",
        "Client_Birthdate",
        "EventDate",
    ]


def get_reminder_schema() -> list[str]:
    """Return column names for the reminders dataset (for agent schema prompts)."""
    return ["ReminderId", "Date", "Subject", "Content"]


def load_recommendations(path: str = DEFAULT_REC_PATH) -> pd.DataFrame:
    """
    Load recommendation dataset with column normalization and EventDate handling.
    Matches app.py load_recos behavior so calendar and agent see the same schema.
    """
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_excel(path)
    except Exception:
        return pd.DataFrame()
    if "Cluster" not in df.columns and "Cluster_Name" in df.columns:
        df = df.rename(columns={"Cluster_Name": "Cluster"})
    for col in ["Client", "Cluster"]:
        if col not in df.columns:
            df[col] = np.nan
    date_cols = []
    if "EventDate" in df.columns:
        date_cols = ["EventDate"]
    if not date_cols and "Predicted_Purchase_Date" in df.columns:
        date_cols = ["Predicted_Purchase_Date"]
    if not date_cols:
        date_cols = [
            c
            for c in df.columns
            if str(c).lower().startswith("predicted_next_purchase_date")
        ]
    if not date_cols:
        date_cols = [
            c
            for c in df.columns
            if str(c).lower() in {"date", "recommended_date", "next_purchase_date"}
        ]
    if date_cols:
        date_col = date_cols[0]
    else:
        date_col = "Predicted_Next_Purchase_Date"
        if date_col not in df.columns:
            df[date_col] = pd.NaT
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    amount_cols = {
        "Recommended_Amount_P10": ["Recommended_Amount_P10", "P10", "Rec_P10"],
        "Recommended_Amount_P50": [
            "Recommended_Amount_P50",
            "P50",
            "Rec_P50",
            "Predicted_Amount_SGD",
        ],
        "Recommended_Amount_P90": ["Recommended_Amount_P90", "P90", "Rec_P90"],
    }
    for target, candidates in amount_cols.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns:
                    df[target] = df[c]
                    break
        if target not in df.columns:
            df[target] = np.nan
    rename_map = {date_col: "EventDate"}
    df = df.rename(columns=rename_map)
    return df


def load_reminders(path: str = DEFAULT_REM_PATH) -> pd.DataFrame:
    """
    Load reminders dataset. Ensures columns ReminderId, Date, Subject, Content, Edited, Date of edit; Date as datetime.
    """
    if not os.path.exists(path):
        df = pd.DataFrame(columns=["ReminderId", "Date", "Subject", "Content", "Edited", "Date of edit"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        return df
    try:
        df = pd.read_excel(path)
    except Exception:
        df = pd.DataFrame(columns=["ReminderId", "Date", "Subject", "Content", "Edited", "Date of edit"])
    for col in ["ReminderId", "Date", "Subject", "Content", "Edited", "Date of edit"]:
        if col not in df.columns:
            if col == "Date" or col == "Date of edit":
                df[col] = pd.NaT
            elif col == "Edited":
                df[col] = "0"
            else:
                df[col] = ""
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


def get_client_dataframe(path: str = DEFAULT_REC_PATH) -> pd.DataFrame:
    """
    Return the client/recommendation dataset (same as load_recommendations).
    Use for agent and client_tools so they reason over the same schema.
    """
    return load_recommendations(path)


def save_recommendations(
    df: pd.DataFrame, path: str = DEFAULT_REC_PATH
) -> str:
    """
    Backup existing file (if any) and write df to Excel. Returns backup path or ''.
    """
    backup_path = ""
    try:
        if os.path.exists(path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            root, ext = os.path.splitext(path)
            backup_path = f"{root}.backup_{ts}{ext}"
            shutil.copy2(path, backup_path)
        out = df.copy()
        if "EventDate" in out.columns:
            out["EventDate"] = pd.to_datetime(out["EventDate"], errors="coerce")
        out.to_excel(path, index=False)
    except Exception as e:
        raise e
    return backup_path


def save_reminders(df: pd.DataFrame, path: str = DEFAULT_REM_PATH) -> str:
    """
    Backup existing file (if any) and write reminders to Excel. Returns backup path or ''.
    """
    backup_path = ""
    try:
        if os.path.exists(path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            root, ext = os.path.splitext(path)
            backup_path = f"{root}.backup_{ts}{ext}"
            shutil.copy2(path, backup_path)
        out = df.copy()
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
        out.to_excel(path, index=False)
    except Exception as e:
        raise e
    return backup_path
