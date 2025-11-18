import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# Column constants used by the app/notebooks
COL_CLIENT = "Client"
COL_CLUSTER = "Cluster"
COL_EVENT_DATE = "EventDate"
COL_REC_TYPE = "Recommended_ProductType"
COL_P10 = "Recommended_Amount_P10"
COL_P50 = "Recommended_Amount_P50"
COL_P90 = "Recommended_Amount_P90"
COL_CONF = "Confidence"

# Provenance flags for injected/overridden rows
COL_IS_GENERATED = "IsGenerated"
COL_IS_SEASONAL = "IsSeasonal"
COL_GEN_RULE = "GenerationRule"
COL_RULE_REASON = "RuleReason"

# Utility

def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in [COL_EVENT_DATE, COL_P10, COL_P50, COL_P90, COL_REC_TYPE, COL_CONF, COL_CLUSTER]:
        if c not in df.columns:
            if c == COL_EVENT_DATE:
                df[c] = pd.NaT
            elif c in (COL_P10, COL_P50, COL_P90):
                df[c] = np.nan
            else:
                df[c] = np.nan
    # provenance cols
    for c in [COL_IS_GENERATED, COL_IS_SEASONAL, COL_GEN_RULE, COL_RULE_REASON]:
        if c not in df.columns:
            df[c] = False if c in (COL_IS_GENERATED, COL_IS_SEASONAL) else ""
    return df


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return [str(v)]


def _match_scope(df: pd.DataFrame, scope: Dict[str, Any] | None) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    if not scope:
        return mask
    if "product_type_in" in scope and COL_REC_TYPE in df.columns:
        mask &= df[COL_REC_TYPE].astype(str).isin([str(x) for x in scope.get("product_type_in", [])])
    if "cluster_in" in scope and COL_CLUSTER in df.columns:
        mask &= df[COL_CLUSTER].astype(str).isin([str(x) for x in scope.get("cluster_in", [])])
    if "date_between" in scope and COL_EVENT_DATE in df.columns:
        try:
            lo, hi = scope.get("date_between", [None, None])
            lo = pd.to_datetime(lo) if lo else None
            hi = pd.to_datetime(hi) if hi else None
            if lo is not None:
                mask &= pd.to_datetime(df[COL_EVENT_DATE]) >= lo
            if hi is not None:
                mask &= pd.to_datetime(df[COL_EVENT_DATE]) <= hi
        except Exception:
            pass
    if "confidence_min" in scope and COL_CONF in df.columns:
        def _parse_conf(v):
            # supports "65%" or numeric
            if isinstance(v, str) and v.endswith("%"):
                try:
                    return float(v[:-1]) / 100.0
                except Exception:
                    return np.nan
            try:
                return float(v)
            except Exception:
                return np.nan
        conf_vals = df[COL_CONF].apply(_parse_conf)
        mask &= conf_vals >= float(scope.get("confidence_min", 0))
    return mask


def _safe_amount(v: Any) -> float:
    try:
        f = float(v)
        return max(0.0, f)
    except Exception:
        return 0.0


def _infer_p10_p90_from_p50(p50: float) -> Tuple[float, float]:
    return max(0.0, 0.5 * p50), max(0.0, 1.5 * p50)


def _repeat_dates(start: pd.Timestamp, frequency: str, count: int) -> List[pd.Timestamp]:
    dates = []
    cur = start
    for _ in range(count):
        if frequency == "daily":
            cur = cur + timedelta(days=1)
        elif frequency == "weekly":
            cur = cur + timedelta(weeks=1)
        elif frequency == "biweekly":
            cur = cur + timedelta(weeks=2)
        elif frequency == "monthly":
            # approximate by adding 30 days to avoid month-end edge cases
            cur = cur + timedelta(days=30)
        elif frequency == "quarterly":
            cur = cur + timedelta(days=91)
        else:
            cur = cur + timedelta(days=30)
        dates.append(cur)
    return dates


def _append_row(base_row: pd.Series, overrides: Dict[str, Any]) -> Dict[str, Any]:
    row = base_row.to_dict()
    row.update(overrides)
    return row


def apply_actions(df: pd.DataFrame, actions: Dict[str, Any], today: date | None = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply validated action rules to df. Returns (new_df, summary)."""
    df = _ensure_cols(df.copy())
    today_ts = pd.to_datetime(today or date.today())

    removed = 0
    modified = 0
    added = 0

    rules = actions.get("rules", []) if isinstance(actions, dict) else []

    for rule in rules:
        rtype = str(rule.get("type", "")).strip().lower()
        reason = str(rule.get("reason", "")).strip()
        clients = _as_list(rule.get("client"))
        scope = rule.get("scope") or rule.get("where")

        if rtype == "suppress_client":
            if not clients:
                continue
            pre = len(df)
            df = df[~df[COL_CLIENT].astype(str).isin(clients)].reset_index(drop=True)
            removed += (pre - len(df))

        elif rtype == "amount_multiplier":
            if not clients:
                continue
            factor = float(rule.get("factor", 1.0))
            mask = df[COL_CLIENT].astype(str).isin(clients)
            if scope:
                mask &= _match_scope(df, scope)
            for col in (COL_P10, COL_P50, COL_P90):
                df.loc[mask, col] = df.loc[mask, col].apply(lambda v: _safe_amount(v) * factor)
            df.loc[mask, COL_GEN_RULE] = "amount_multiplier"
            if reason:
                df.loc[mask, COL_RULE_REASON] = reason
            modified += int(mask.sum())

        elif rtype == "amount_set":
            if not clients:
                continue
            p50 = rule.get("amount_p50")
            if p50 is None:
                continue
            p50 = _safe_amount(p50)
            p10 = rule.get("amount_p10")
            p90 = rule.get("amount_p90")
            if p10 is None or p90 is None:
                ip10, ip90 = _infer_p10_p90_from_p50(p50)
                p10 = _safe_amount(rule.get("amount_p10", ip10))
                p90 = _safe_amount(rule.get("amount_p90", ip90))
            mask = df[COL_CLIENT].astype(str).isin(clients)
            if scope:
                mask &= _match_scope(df, scope)
            df.loc[mask, [COL_P10, COL_P50, COL_P90]] = [p10, p50, p90]
            df.loc[mask, COL_GEN_RULE] = "amount_set"
            if reason:
                df.loc[mask, COL_RULE_REASON] = reason
            modified += int(mask.sum())

        elif rtype == "change_recommendation":
            if not clients:
                continue
            ptype = str(rule.get("product_type", "")).strip()
            if not ptype:
                continue
            mask = df[COL_CLIENT].astype(str).isin(clients)
            if scope:
                mask &= _match_scope(df, scope)
            df.loc[mask, COL_REC_TYPE] = ptype
            df.loc[mask, COL_GEN_RULE] = "change_recommendation"
            if reason:
                df.loc[mask, COL_RULE_REASON] = reason
            modified += int(mask.sum())

        elif rtype == "change_frequency":
            if not clients:
                continue
            freq = str(rule.get("frequency", "monthly")).strip().lower()
            count = int(rule.get("count", 0))
            as_additional = bool(rule.get("as_additional", True))
            start_from = rule.get("start_from")

            for client in clients:
                base_rows = df[df[COL_CLIENT].astype(str) == str(client)]
                if base_rows.empty:
                    continue
                # Choose a base row: the latest by EventDate
                base_rows = base_rows.copy()
                base_rows[COL_EVENT_DATE] = pd.to_datetime(base_rows[COL_EVENT_DATE], errors="coerce")
                base_rows = base_rows.sort_values(COL_EVENT_DATE)
                base_row = base_rows.iloc[-1]
                if start_from:
                    start_ts = pd.to_datetime(start_from, errors="coerce")
                    if pd.isna(start_ts):
                        start_ts = base_row[COL_EVENT_DATE] if pd.notna(base_row[COL_EVENT_DATE]) else today_ts + timedelta(days=30)
                else:
                    start_ts = base_row[COL_EVENT_DATE] if pd.notna(base_row[COL_EVENT_DATE]) else today_ts + timedelta(days=30)

                future_dates = _repeat_dates(pd.to_datetime(start_ts), freq, max(0, min(count, 3)))
                new_rows = []
                for dt_ in future_dates:
                    overrides = {
                        COL_EVENT_DATE: pd.to_datetime(dt_),
                        COL_IS_GENERATED: True,
                        COL_GEN_RULE: "change_frequency",
                        COL_RULE_REASON: reason,
                    }
                    new_rows.append(_append_row(base_row, overrides))
                if new_rows:
                    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                    added += len(new_rows)
                if not as_additional and count > 0:
                    # Optionally adjust/replace existing predicted EventDate to start_from
                    # For now, we do not delete base rows; we only add future ones (as_additional default True)
                    pass

        elif rtype == "seasonality_inject":
            client = clients[0] if clients else None
            if not client:
                continue
            product_type = str(rule.get("product_type", "")).strip()
            dom = int(rule.get("day_of_month", 1))
            amount_p50 = rule.get("amount_p50", None)
            amount_p10 = rule.get("amount_p10")
            amount_p90 = rule.get("amount_p90")
            effective_from = pd.to_datetime(rule.get("effective_from", today_ts.date()))
            effective_to = pd.to_datetime(rule.get("effective_to", None))
            as_additional = bool(rule.get("as_additional", True))

            # Get a base row template for the client (latest)
            base_rows = df[df[COL_CLIENT].astype(str) == str(client)]
            if base_rows.empty:
                continue
            base_rows = base_rows.copy()
            base_rows[COL_EVENT_DATE] = pd.to_datetime(base_rows[COL_EVENT_DATE], errors="coerce")
            base_rows = base_rows.sort_values(COL_EVENT_DATE)
            base_row = base_rows.iloc[-1]

            # Determine amounts
            if isinstance(amount_p50, str) and amount_p50.lower() == "match_last":
                p50 = _safe_amount(base_row.get(COL_P50, np.nan))
                if np.isnan(p50) or p50 == 0:
                    # fallback to client median
                    p50 = _safe_amount(base_rows[COL_P50].median())
            else:
                p50 = _safe_amount(amount_p50 if amount_p50 is not None else base_row.get(COL_P50, np.nan))
            if amount_p10 is None or amount_p90 is None:
                ip10, ip90 = _infer_p10_p90_from_p50(p50)
                p10 = _safe_amount(rule.get("amount_p10", ip10))
                p90 = _safe_amount(rule.get("amount_p90", ip90))
            else:
                p10 = _safe_amount(amount_p10)
                p90 = _safe_amount(amount_p90)

            # Determine date range (default next 12 months if no effective_to)
            start = pd.to_datetime(effective_from)
            end = pd.to_datetime(effective_to) if pd.notna(effective_to) else (start + pd.DateOffset(months=12))

            cur = start
            new_rows = []
            while cur <= end:
                # set to desired day of month
                try:
                    candidate = pd.Timestamp(year=cur.year, month=cur.month, day=dom)
                except ValueError:
                    # if day 31 not valid, fallback to last day of month
                    candidate = (pd.Timestamp(year=cur.year, month=cur.month, day=1) + pd.offsets.MonthEnd(0))
                overrides = {
                    COL_EVENT_DATE: candidate,
                    COL_REC_TYPE: product_type if product_type else base_row.get(COL_REC_TYPE, ""),
                    COL_P10: p10,
                    COL_P50: p50,
                    COL_P90: p90,
                    COL_IS_GENERATED: True,
                    COL_IS_SEASONAL: True,
                    COL_GEN_RULE: "seasonality_inject",
                    COL_RULE_REASON: reason,
                }
                new_rows.append(_append_row(base_row, overrides))
                # increment 1 month
                cur = candidate + pd.offsets.MonthEnd(1) + pd.offsets.Day(1)
            if new_rows:
                df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                added += len(new_rows)
            # as_additional is always True by requirement; do not remove base rows

        elif rtype == "add_entry":
            # Insert a single explicit transaction row for each client
            date_val = rule.get("date")
            product_type = str(rule.get("product_type", "")).strip()
            amount_p50 = rule.get("amount_p50")
            amount_p10 = rule.get("amount_p10")
            amount_p90 = rule.get("amount_p90")
            if not date_val or amount_p50 is None or not clients:
                continue
            target_ts = pd.to_datetime(date_val, errors="coerce")
            if pd.isna(target_ts):
                continue
            p50 = _safe_amount(amount_p50)
            if amount_p10 is None or amount_p90 is None:
                ip10, ip90 = _infer_p10_p90_from_p50(p50)
                p10 = _safe_amount(rule.get("amount_p10", ip10))
                p90 = _safe_amount(rule.get("amount_p90", ip90))
            else:
                p10 = _safe_amount(amount_p10)
                p90 = _safe_amount(amount_p90)

            for client in clients:
                sub = df[df[COL_CLIENT].astype(str) == str(client)]
                if sub.empty:
                    # No existing template; create a minimal row
                    base = {
                        COL_CLIENT: str(client),
                        COL_CLUSTER: np.nan,
                        COL_REC_TYPE: product_type,
                        COL_P10: p10,
                        COL_P50: p50,
                        COL_P90: p90,
                        COL_EVENT_DATE: target_ts,
                        COL_IS_GENERATED: True,
                        COL_IS_SEASONAL: False,
                        COL_GEN_RULE: "add_entry",
                        COL_RULE_REASON: reason,
                    }
                else:
                    tmpl = sub.copy()
                    tmpl[COL_EVENT_DATE] = pd.to_datetime(tmpl[COL_EVENT_DATE], errors="coerce")
                    tmpl = tmpl.sort_values(COL_EVENT_DATE)
                    base_row = tmpl.iloc[-1]
                    overrides = {
                        COL_EVENT_DATE: target_ts,
                        COL_REC_TYPE: product_type if product_type else base_row.get(COL_REC_TYPE, ""),
                        COL_P10: p10,
                        COL_P50: p50,
                        COL_P90: p90,
                        COL_IS_GENERATED: True,
                        COL_IS_SEASONAL: False,
                        COL_GEN_RULE: "add_entry",
                        COL_RULE_REASON: reason,
                    }
                    base = _append_row(base_row, overrides)
                df = pd.concat([df, pd.DataFrame([base])], ignore_index=True)
                added += 1

        else:
            # Unknown rule type: ignore safely
            continue

    summary = {"removed": removed, "modified": modified, "added": added}
    # Ensure EventDate dtype
    if COL_EVENT_DATE in df.columns:
        df[COL_EVENT_DATE] = pd.to_datetime(df[COL_EVENT_DATE], errors="coerce")
    return df, summary


def commit_to_excel(df: pd.DataFrame, path: str) -> str:
    """Backup existing file and write df to Excel. Returns backup path (or '')."""
    backup_path = ""
    try:
        if os.path.exists(path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            root, ext = os.path.splitext(path)
            backup_path = f"{root}.backup_{ts}{ext}"
            # Use pandas to read/backup content: we just copy the file bytes
            import shutil
            shutil.copy2(path, backup_path)
        # Write new excel
        df_to_write = df.copy()
        # Convert datetime to date where applicable
        if COL_EVENT_DATE in df_to_write.columns:
            df_to_write[COL_EVENT_DATE] = pd.to_datetime(df_to_write[COL_EVENT_DATE], errors="coerce")
        df_to_write.to_excel(path, index=False)
    except Exception as e:
        raise e
    return backup_path
