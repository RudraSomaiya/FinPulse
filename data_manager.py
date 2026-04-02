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
DEFAULT_TX_PATH = "cleaned_data.xlsx"


def get_transaction_schema() -> list[str]:
    """Return column names for the transaction dataset (for agent schema prompts)."""
    return [
        "Client number",
        "Product Type",
        "Product Name",
        "Transaction Amount (SGD)",
        "Transaction Date",
        "Fund House/Issuer/Exchange",
        "Account Type",
        "Transaction Mode",
    ]


def load_transactions(path: str = DEFAULT_TX_PATH) -> pd.DataFrame:
    """Load cleaned transaction history. Returns empty DataFrame on failure."""
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_excel(path)
    except Exception:
        return pd.DataFrame()


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
        
    client_details_path = "client-details.xlsx"
    if os.path.exists(client_details_path):
        try:
            client_details = pd.read_excel(client_details_path)
            cols_to_drop = [c for c in ["Client_Birthdate", "Client_phone_number", "Client_email"] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
            if "Client" in client_details.columns and "Client" in df.columns:
                target_cols = ["Client_Birthdate", "Client_phone_number", "Client_email"]
                available_cols = [c for c in target_cols if c in client_details.columns]
                if available_cols:
                    df = pd.merge(df, client_details[["Client"] + available_cols], on="Client", how="left")
        except Exception:
            pass

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
        
        cols_to_drop = ["Client_Birthdate", "Client_phone_number", "Client_email"]
        out = out.drop(columns=[c for c in cols_to_drop if c in out.columns])
        
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
