"""
Read-only and derived-data operations on the recommendation (client) dataframe.
All functions operate on pandas; no file I/O. Handle missing columns gracefully.
"""

from datetime import date, datetime

import numpy as np
import pandas as pd


def get_top_clients(
    n: int,
    df: pd.DataFrame,
    sort_by: str = "Total_Transactions",
    ascending: bool = False,
) -> pd.DataFrame:
    """
    Return top n clients sorted by sort_by (e.g. Total_Transactions, Recommended_Amount_P50, Total_Invested_SGD).
    Handles missing columns by returning empty or partial result.
    """
    if df is None or df.empty or n <= 0:
        return pd.DataFrame()
    if sort_by not in df.columns:
        sort_by = "Client"
    out = df.sort_values(sort_by, ascending=ascending, na_position="last")
    return out.head(n).copy()


def filter_clients_by_product(
    product_type: str, df: pd.DataFrame
) -> pd.DataFrame:
    """
    Filter rows where Recommended_ProductType or Current_ProductType matches product_type (case-insensitive).
    """
    if df is None or df.empty:
        return pd.DataFrame()
    product_type = (product_type or "").strip()
    if not product_type:
        return df.copy()
    mask = pd.Series(False, index=df.index)
    if "Recommended_ProductType" in df.columns:
        mask |= df["Recommended_ProductType"].astype(str).str.strip().str.upper() == product_type.upper()
    if "Current_ProductType" in df.columns:
        mask |= df["Current_ProductType"].astype(str).str.strip().str.upper() == product_type.upper()
    return df[mask].copy()


def filter_clients_by_recommended_product(
    product_type: str, df: pd.DataFrame
) -> pd.DataFrame:
    """
    Filter rows where Recommended_ProductType equals product_type (case-insensitive).
    Use this when "ETF clients" means clients we recommend ETF to, not current product.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    product_type = (product_type or "").strip()
    if not product_type or "Recommended_ProductType" not in df.columns:
        return pd.DataFrame()
    mask = df["Recommended_ProductType"].astype(str).str.strip().str.upper() == product_type.upper()
    return df[mask].copy()


def get_client_summary(client: str, df: pd.DataFrame) -> dict | None:
    """
    Return first matching row for Client == client as a dict of key fields.
    """
    if df is None or df.empty or not (client or "").strip():
        return None
    client = str(client).strip()
    if "Client" not in df.columns:
        return None
    sub = df[df["Client"].astype(str).str.strip() == client]
    if sub.empty:
        return None
    row = sub.iloc[0]
    keys = [
        "Client",
        "Cluster",
        "Recommended_ProductType",
        "Recommended_Amount_P50",
        "Recommended_Amount_P10",
        "Recommended_Amount_P90",
        "Client_Birthdate",
        "Total_Transactions",
        "Total_Invested_SGD",
        "Confidence",
        "Predicted_Purchase_Date",
        "EventDate",
    ]
    summary = {}
    for k in keys:
        if k in row.index:
            v = row[k]
            if pd.isna(v):
                summary[k] = None
            else:
                summary[k] = v
    return summary


def get_client_birth_date(client: str, df: pd.DataFrame, year: int) -> date | None:
    """
    Get a single client's birth date in the given year from Client_Birthdate (DD/MM or DD/MM/YYYY).
    Returns date(year, month, day) or None if not found or invalid.
    """
    if df is None or df.empty or "Client" not in df.columns or "Client_Birthdate" not in df.columns:
        return None
    client = (client or "").strip()
    if not client:
        return None
    sub = df[df["Client"].astype(str).str.strip() == client]
    if sub.empty:
        return None
    bd_raw = sub.iloc[0].get("Client_Birthdate")
    if pd.isna(bd_raw) or not str(bd_raw).strip():
        return None
    parts = str(bd_raw).strip().split("/")
    if len(parts) < 2:
        return None
    try:
        day = int(parts[0])
        month = int(parts[1])
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def get_birthdays(
    df: pd.DataFrame, year: int | None = None
) -> pd.DataFrame:
    """
    Parse Client_Birthdate (DD/MM or DD/MM/YYYY); optionally filter to a given year.
    Returns dataframe with Client and a resolved birth_date (date in the given year or next valid).
    """
    if df is None or df.empty or "Client_Birthdate" not in df.columns:
        return pd.DataFrame()
    out_rows = []
    for _, row in df.iterrows():
        bd_raw = row.get("Client_Birthdate")
        if pd.isna(bd_raw) or not str(bd_raw).strip():
            continue
        parts = str(bd_raw).strip().split("/")
        if len(parts) < 2:
            continue
        try:
            day = int(parts[0])
            month = int(parts[1])
            if year is not None:
                try:
                    birth_date = date(year, month, day)
                except ValueError:
                    continue
            else:
                birth_date = date(2000, month, day)
            out_rows.append(
                {
                    "Client": row.get("Client"),
                    "Client_Birthdate": bd_raw,
                    "birth_date": birth_date,
                }
            )
        except (ValueError, IndexError):
            continue
    if not out_rows:
        return pd.DataFrame()
    result = pd.DataFrame(out_rows)
    # One row per client (same client may appear in multiple recommendation rows)
    if "Client" in result.columns:
        result = result.drop_duplicates(subset=["Client"], keep="first")
    if year is not None and "birth_date" in result.columns:
        result = result.sort_values("birth_date")
    return result


def get_high_value_clients(
    df: pd.DataFrame,
    min_amount: float | None = None,
    top_n: int | None = None,
    sort_by: str = "Recommended_Amount_P50",
) -> pd.DataFrame:
    """
    Filter/sort by amount (Recommended_Amount_P50 or Total_Invested_SGD).
    If sort_by column missing, use Total_Invested_SGD or Client. Supports min_amount and/or top_n.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if sort_by not in df.columns:
        sort_by = "Total_Invested_SGD" if "Total_Invested_SGD" in df.columns else "Client"
    out = df.copy()
    if min_amount is not None and sort_by in out.columns:
        out = out[out[sort_by].fillna(0) >= min_amount]
    out = out.sort_values(sort_by, ascending=False, na_position="last")
    if top_n is not None and top_n > 0:
        out = out.head(top_n)
    return out
