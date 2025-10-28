import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from streamlit_calendar import calendar
import numpy as np

st.set_page_config(page_title="Client Recommendations Calendar", layout="wide")

@st.cache_data(show_spinner=False)
def load_recos(path):
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

# No transactions file reference needed

cluster_colors = {
    "Passive Long-Term Investor": "#1f77b4",
    "Regular Retail Investor": "#ff7f0e",
    "Ultra High-Net-Worth": "#2ca02c",
    "New/Single-Transaction": "#7f7f7f",
}

df = load_recos("recommendationOutput.xlsx")
if "Recent_Product" not in df.columns:
    df["Recent_Product"] = np.nan
if "Recent_Date" not in df.columns:
    df["Recent_Date"] = pd.NaT

if "EventDate" not in df.columns:
    df["EventDate"] = pd.NaT

min_date = pd.to_datetime(df["EventDate"].min()) if df["EventDate"].notna().any() else None
max_date = pd.to_datetime(df["EventDate"].max()) if df["EventDate"].notna().any() else None

# Status summary to help verify input
st.caption(
    f"Loaded {len(df)} rows | EventDate non-null: {int(df['EventDate'].notna().sum())} | "
    f"Clusters: {len([c for c in df['Cluster'].dropna().unique().tolist()])} | "
    f"Date range: {min_date.date() if min_date is not None else '-'} to {max_date.date() if max_date is not None else '-'}"
)

st.sidebar.markdown("### Filters")
start_date, end_date = st.sidebar.date_input(
    "Date range", 
    value=(min_date.date() if min_date is not None else datetime.today().date(),
           (max_date.date() if max_date is not None else (datetime.today()+timedelta(days=30)).date())),
)
clusters = sorted([c for c in df["Cluster"].dropna().unique().tolist()])
selected_clusters = st.sidebar.multiselect("Clusters", options=clusters, default=clusters)
client_q = st.sidebar.text_input("Search client")

mask = df["EventDate"].between(pd.to_datetime(start_date), pd.to_datetime(end_date))
if selected_clusters:
    mask &= df["Cluster"].isin(selected_clusters)
if client_q:
    mask &= df["Client"].astype(str).str.contains(client_q, case=False, na=False)

fdf = df[mask].copy()

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

cal = calendar(events=events, options=options)

clicked_date = None
if cal.get("eventClick"):
    ev = cal["eventClick"]["event"]
    clicked_date = ev.get("extendedProps", {}).get("date") or ev.get("start")

if clicked_date:
    day = pd.to_datetime(clicked_date).date()
    clicked_cluster = None
    if cal.get("eventClick") and cal["eventClick"].get("event"):
        clicked_cluster = cal["eventClick"]["event"].get("extendedProps", {}).get("cluster")
    if clicked_cluster is not None and len(clicked_cluster) > 0:
        sel = (fdf["EventDate"].dt.date == day) & (fdf["Cluster"].astype(str) == str(clicked_cluster))
        day_df = fdf[sel].reset_index(drop=True)
    else:
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
