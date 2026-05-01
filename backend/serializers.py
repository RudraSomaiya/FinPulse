import pandas as pd
import numpy as np


def _serialize(val):
    if val is None:
        return None
    if isinstance(val, pd.Timestamp):
        return None if pd.isna(val) else val.isoformat()[:10]
    if isinstance(val, float) and np.isnan(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return None if np.isnan(val) else float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    return val


def df_to_records(df: pd.DataFrame) -> list:
    records = []
    for _, row in df.iterrows():
        records.append({col: _serialize(val) for col, val in row.items()})
    return records
