import os

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, date
from streamlit_calendar import calendar
import numpy as np
from llm_parser import parse_instructions
from rules import apply_actions, commit_to_excel
from client_plan_llm import generate_client_plan

st.set_page_config(page_title="Client Recommendations Calendar", layout="wide")

@st.cache_data(show_spinner=False)
def load_recos(path, mtime):
    """Load recommendations with cache keyed by file path and modification time."""
    df = pd.read_excel(path)
    # Map common alternative names
    if "Cluster" not in df.columns and "Cluster_Name" in df.columns:
        df = df.rename(columns={"Cluster_Name": "Cluster"})
    # Ensure required columns exist
    for col in ["Client","Cluster"]:
        if col not in df.columns:
            df[col] = np.nan
    # Detect event date column (priority: Predicted_Purchase_Date)
    date_cols = []
    if "EventDate" in df.columns:
        date_cols = ["EventDate"]
    if not date_cols and "Predicted_Purchase_Date" in df.columns:
        date_cols = ["Predicted_Purchase_Date"]
    if not date_cols:
        date_cols = [c for c in df.columns if c.lower().startswith("predicted_next_purchase_date".lower())]
    if not date_cols:
        date_cols = [c for c in df.columns if c.lower() in {"date","recommended_date","next_purchase_date"}]
    if date_cols:
        date_col = date_cols[0]
    else:
        date_col = "Predicted_Next_Purchase_Date"
        if date_col not in df.columns:
            df[date_col] = pd.NaT
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    amount_cols = {
        "Recommended_Amount_P10": ["Recommended_Amount_P10","P10","Rec_P10"],
        "Recommended_Amount_P50": ["Recommended_Amount_P50","P50","Rec_P50","Predicted_Amount_SGD"],
        "Recommended_Amount_P90": ["Recommended_Amount_P90","P90","Rec_P90"]
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


@st.cache_data(show_spinner=False)
def load_transactions(path, mtime):
    """Load cleaned transaction history (cleaned_data.xlsx)."""
    if not os.path.exists(path) or not mtime:
        return pd.DataFrame()
    try:
        tdf = pd.read_excel(path)
    except Exception:
        return pd.DataFrame()
    return tdf


@st.cache_data(show_spinner=False)
def build_client_history(tdf: pd.DataFrame):
    """Build per-client transaction summary and product universe.

    Groups by 'Client number' and collects product types and amounts.
    Returns (history_map, product_universe).
    """
    if tdf is None or tdf.empty:
        return {}, []

    col_client_id = "Client number"
    col_prod = "Product Type"
    col_amt = "Transaction Amount (SGD)"

    if col_client_id not in tdf.columns:
        return {}, []

    history = {}
    product_universe = set()

    for cid, g in tdf.groupby(col_client_id):
        g = g.copy()
        tx_list = []
        if col_prod in g.columns:
            product_universe.update(
                {str(x).strip() for x in g[col_prod].dropna().astype(str).tolist()}
            )
        for _, r in g.iterrows():
            prod = str(r.get(col_prod, "")).strip() if col_prod in g.columns else ""
            amt = r.get(col_amt, None) if col_amt in g.columns else None
            tx_list.append({"product": prod, "amount": amt})
        avg_amt = None
        if col_amt in g.columns and not g[col_amt].isna().all():
            try:
                avg_amt = float(g[col_amt].mean())
            except Exception:
                avg_amt = None
        history[str(cid)] = {
            "transactions": tx_list,
            "avg_amount": avg_amt,
            "total_tx": int(len(g)),
        }

    return history, sorted({p for p in product_universe if p})

# No transactions file reference needed

cluster_colors = {
    "Passive Long-Term Investor": "#1f77b4",
    "Regular Retail Investor": "#ff7f0e",
    "Ultra High-Net-Worth": "#2ca02c",
    "New/Single-Transaction": "#7f7f7f",
}
rec_path = "recommendationOutput.xlsx"
rec_mtime = os.path.getmtime(rec_path) if os.path.exists(rec_path) else 0
df = load_recos(rec_path, rec_mtime)

tx_path = "cleaned_data.xlsx"
tx_mtime = os.path.getmtime(tx_path) if os.path.exists(tx_path) else 0
tx_df = load_transactions(tx_path, tx_mtime)
client_history_map, tx_product_universe = build_client_history(tx_df)
# If overrides were applied previously, use them
if "applied_df" in st.session_state and st.session_state.get("use_overrides", False):
    try:
        if isinstance(st.session_state["applied_df"], pd.DataFrame) and len(st.session_state["applied_df"]) > 0:
            df = st.session_state["applied_df"].copy()
    except Exception:
        pass
if "Recent_Product" not in df.columns:
    df["Recent_Product"] = np.nan
if "Recent_Date" not in df.columns:
    df["Recent_Date"] = pd.NaT

if "EventDate" not in df.columns:
    df["EventDate"] = pd.NaT

static_product_types = ["BONDS", "STOCK", "UT", "DPMS", "ETF"]
reco_products = set()
if "Recommended_ProductType" in df.columns:
    reco_products.update(
        {str(x).strip() for x in df["Recommended_ProductType"].dropna().astype(str).tolist()}
    )
if "Current_ProductType" in df.columns:
    reco_products.update(
        {str(x).strip() for x in df["Current_ProductType"].dropna().astype(str).tolist()}
    )
available_product_types = sorted(
    {p for p in static_product_types} |
    {p for p in tx_product_universe} |
    {p for p in reco_products if p}
)

min_date = pd.to_datetime(df["EventDate"].min()) if df["EventDate"].notna().any() else None
max_date = pd.to_datetime(df["EventDate"].max()) if df["EventDate"].notna().any() else None

# Status summary to help verify input
st.caption(
    f"Loaded {len(df)} rows | EventDate non-null: {int(df['EventDate'].notna().sum())} | "
    f"Clusters: {len([c for c in df['Cluster'].dropna().unique().tolist()])} | "
    f"Date range: {min_date.date() if min_date is not None else '-'} to {max_date.date() if max_date is not None else '-'}"
)

st.sidebar.markdown("### Natural language overrides")
nl_text = st.sidebar.text_area("Type instructions", height=100)
col_parse, col_apply = st.sidebar.columns(2)
if col_parse.button("Parse"):
    actions = parse_instructions(nl_text)
    st.session_state["actions"] = actions
    st.session_state["summary"] = {}
    if not actions or not actions.get("rules"):
        st.sidebar.warning("No valid rules parsed.")
    else:
        st.sidebar.success(f"Parsed {len(actions.get('rules', []))} rule(s).")
if col_apply.button("Apply"):
    actions = st.session_state.get("actions", {})
    if not actions or not actions.get("rules"):
        st.sidebar.warning("Nothing to apply. Parse instructions first.")
    else:
        new_df, summary = apply_actions(df, actions, date.today())
        st.session_state["applied_df"] = new_df
        st.session_state["summary"] = summary
        st.session_state["use_overrides"] = True
        st.rerun()

summary = st.session_state.get("summary", {})
if summary:
    st.sidebar.caption(f"Changes — Removed: {summary.get('removed',0)}, Modified: {summary.get('modified',0)}, Added: {summary.get('added',0)}")
    if st.sidebar.button("Commit to Excel"):
        try:
            applied = st.session_state.get("applied_df")
            if isinstance(applied, pd.DataFrame) and len(applied) > 0:
                backup_path = commit_to_excel(applied, "recommendationOutput.xlsx")
                st.sidebar.success(f"Saved. Backup: {backup_path if backup_path else 'none'}")
                st.session_state["use_overrides"] = False
                st.rerun()
            else:
                st.sidebar.warning("No applied data to save.")
        except Exception as e:
            st.sidebar.error(f"Save failed: {e}")

st.sidebar.markdown("### Filters")
start_date, end_date = st.sidebar.date_input(
    "Date range", 
    value=(min_date.date() if min_date is not None else datetime.today().date(),
           (max_date.date() if max_date is not None else (datetime.today()+timedelta(days=30)).date())),
)
clusters = sorted([c for c in df["Cluster"].dropna().unique().tolist()])
selected_clusters = st.sidebar.multiselect("Clusters", options=clusters, default=clusters)
client_q = st.sidebar.text_input("Search client")

# Sidebar legend for clusters
st.sidebar.markdown("---")
st.sidebar.markdown("**Legend**")
for name, col in cluster_colors.items():
    st.sidebar.markdown(
        f"<div style='display:flex; align-items:center; gap:8px;'>"
        f"<span style='display:inline-block; width:12px; height:12px; background:{col}; border-radius:6px;'></span>"
        f"<span>{name}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

mask = df["EventDate"].between(pd.to_datetime(start_date), pd.to_datetime(end_date))
if selected_clusters:
    mask &= df["Cluster"].isin(selected_clusters)
if client_q:
    mask &= df["Client"].astype(str).str.strip() == str(client_q).strip()

fdf = df[mask].copy()

# Determine focus date for calendar if an exact client is searched
focus_date_str = None
if client_q and not fdf.empty:
    # Use earliest event date for the client in the filtered frame
    first_date = pd.to_datetime(fdf.sort_values("EventDate")["EventDate"].iloc[0], errors="coerce")
    if pd.notna(first_date):
        focus_date_str = first_date.strftime("%Y-%m-%d")

by_date_cluster = fdf.assign(EventDay=fdf["EventDate"].dt.date).groupby(["EventDay","Cluster"], dropna=True)

events = []
for (d, cn), g in by_date_cluster:
    g = g.sort_values("Recommended_Amount_P50", ascending=False)
    first_client = str(g.iloc[0]["Client"]) if len(g) else ""
    extra = len(g) - 1
    title = first_client if extra <= 0 else f"{first_client} + {extra} others"
    start_str = pd.to_datetime(d).strftime("%Y-%m-%d")
    events.append({
        "id": f"day-{start_str}-{str(cn)}",
        "title": title,
        "start": start_str,
        "allDay": True,
        "color": cluster_colors.get(cn, "#999999"),
        "extendedProps": {"date": start_str, "cluster": str(cn)}
    })

options = {
    "initialView": "dayGridMonth",
    "height": 750,
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,dayGridWeek,dayGridDay"
    },
    "eventDisplay": "block",
}

# If we have a client search, center the calendar on that client's event date
if focus_date_str is not None:
    options["initialDate"] = focus_date_str

cal = calendar(events=events, options=options)

clicked_date = None
if cal.get("dateClick"):
    clicked_date = cal["dateClick"].get("dateStr") or cal["dateClick"].get("date")
if not clicked_date and cal.get("eventClick"):
    ev = cal["eventClick"].get("event")
    if ev:
        clicked_date = ev.get("extendedProps", {}).get("date") or ev.get("start")

if clicked_date:
    day = pd.to_datetime(clicked_date).date()
    # Always show all entries for the clicked date (across clusters)
    day_df = fdf[fdf["EventDate"].dt.date == day].reset_index(drop=True)
    if day_df.empty:
        st.info("No records for this date.")
    else:
        idx_state_key = f"idx_{clicked_date}"
        if idx_state_key not in st.session_state:
            st.session_state[idx_state_key] = 0
        col1, col2, col3 = st.columns([6,1,1])
        i = st.session_state[idx_state_key]
        i = int(np.clip(i, 0, len(day_df)-1))
        row = day_df.iloc[i]
        with col1:
            client = str(row.get('Client', ''))
            cluster = str(row.get('Cluster', ''))
            cluster_color = cluster_colors.get(cluster, '#777777')

            # Header: Client name big
            st.markdown(f"<div style='font-size:26px; font-weight:700; margin-bottom:6px;'>{client}</div>", unsafe_allow_html=True)

            # Cluster badge with background color
            st.markdown(
                f"<span style='display:inline-block; background:{cluster_color}; color:#ffffff; padding:4px 10px; border-radius:14px; font-weight:600; font-size:12px;'>"
                f"{cluster}</span>",
                unsafe_allow_html=True,
            )

            # Spacing
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            # Recent purchase info (normal)
            recent_date = row.get('Current_ProductType_Date', row.get('Recent_Date', pd.NaT))
            if pd.notna(recent_date):
                try:
                    recent_date = pd.to_datetime(recent_date).date()
                except Exception:
                    pass
            recent_ptype = row.get('Current_ProductType', '')
            st.markdown(f"<div>Recent Purchase Date: <strong>{recent_date if pd.notna(recent_date) else '-'}</strong></div>", unsafe_allow_html=True)
            st.markdown(f"<div>Recent Product Type: <strong>{recent_ptype if pd.notna(recent_ptype) else '-'}</strong></div>", unsafe_allow_html=True)

            # Recommended info (bold and slightly bigger)
            rec_ptype = row.get('Recommended_ProductType', '')
            pred_date = row.get('Predicted_Purchase_Date', row.get('EventDate', pd.NaT))
            if pd.notna(pred_date):
                try:
                    pred_date = pd.to_datetime(pred_date).date()
                except Exception:
                    pass
            rec_amt = row.get('Recommended_Amount_P50', np.nan)

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-weight:700; font-size:15px;'>Recommended Product Type: {rec_ptype if pd.notna(rec_ptype) else '-'}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-weight:700; font-size:15px;'>Predicted Purchase Date: {pred_date if pd.notna(pred_date) else '-'}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-weight:700; font-size:15px;'>Recommended Product Type Amount: ${rec_amt:,.0f}</div>",
                unsafe_allow_html=True,
            )

            # Confidence (bold green)
            conf = row.get('Confidence', None)
            conf_txt = '-' if conf is None or (isinstance(conf, float) and np.isnan(conf)) else f"{conf}"
            st.markdown(
                f"<div style='font-weight:700; color:#16a34a;'>Confidence: {conf_txt}</div>",
                unsafe_allow_html=True,
            )

            # Top 10% Buyer flag
            top_flag = row.get('Top_10pct_Buyer', None)
            is_top = False
            if isinstance(top_flag, str):
                is_top = top_flag.strip().lower() in {"true","yes","1"}
            elif isinstance(top_flag, (bool, np.bool_)):
                is_top = bool(top_flag)
            elif isinstance(top_flag, (int, float)) and not np.isnan(top_flag):
                is_top = bool(top_flag)
            top_color = '#16a34a' if is_top else '#dc2626'
            top_text = 'True' if is_top else 'False'
            st.markdown(
                f"<div style='font-weight:700; color:{top_color};'>Top 10% Buyer: {top_text}</div>",
                unsafe_allow_html=True,
            )

            # AI-generated future plan paragraph
            client_id = str(row.get('Client', '')).strip()
            hist = client_history_map.get(client_id, {})
            tx_list = hist.get("transactions", [])

            avg_hist = row.get('Avg_Historical_Amount', np.nan)
            if (isinstance(avg_hist, float) and np.isnan(avg_hist)) or avg_hist is None:
                avg_hist = hist.get("avg_amount")

            total_tx = row.get('Total_Transactions', np.nan)
            if (isinstance(total_tx, float) and np.isnan(total_tx)) or total_tx is None:
                total_tx = hist.get("total_tx")

            rec_ptype = row.get('Recommended_ProductType', '')
            pred_amt = row.get('Predicted_Amount_SGD', row.get('Recommended_Amount_P50', np.nan))
            conf_val = row.get('Confidence', None)

            plan_context = {
                "client_name": client,
                "cluster": cluster,
                "transactions": tx_list,
                "recommended_product_type": rec_ptype,
                "confidence": conf_val,
                "predicted_amount_sgd": pred_amt,
                "avg_historical_amount": avg_hist,
                "total_transactions": total_tx,
                "available_product_types": available_product_types,
            }

            if "client_plan_cache" not in st.session_state:
                st.session_state["client_plan_cache"] = {}
            cache = st.session_state["client_plan_cache"]
            cache_key = client_id or client
            plan_text = cache.get(cache_key)
            if not plan_text:
                with st.spinner("Generating future plan..."):
                    plan_text = generate_client_plan(plan_context)
                cache[cache_key] = plan_text

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            st.markdown("**Future Plan (AI Advisor)**")
            st.markdown(plan_text)
        with col2:
            if st.button("Prev", key=f"prev-{clicked_date}"):
                st.session_state[idx_state_key] = (i - 1) % len(day_df)
                st.rerun()
        with col3:
            if st.button("Next", key=f"next-{clicked_date}"):
                st.session_state[idx_state_key] = (i + 1) % len(day_df)
                st.rerun()
        if st.button("Show all", key=f"showall-{clicked_date}"):
            st.dataframe(day_df[[c for c in day_df.columns if c not in {"EventDate"}]].sort_values("Recommended_Amount_P50", ascending=False))
            st.download_button(
                label="Download shown (CSV)",
                data=day_df.to_csv(index=False).encode("utf-8"),
                file_name=f"calendar_{clicked_date}.csv",
                mime="text/csv",
            )

st.dataframe(fdf.sort_values(["EventDate","Recommended_Amount_P50"], ascending=[True, False]))

csv = fdf.to_csv(index=False).encode("utf-8")
st.download_button("Download filtered CSV", data=csv, file_name="filtered_recommendations.csv", mime="text/csv")
