import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from streamlit_calendar import calendar
import numpy as np

st.set_page_config(page_title="Client Recommendations Calendar", layout="wide")

@st.cache_data(show_spinner=False)
def load_recos(path):
    df = pd.read_excel(path)
    for col in ["Client","Cluster_Name"]:
        if col not in df.columns:
            df[col] = np.nan
    date_cols = [c for c in df.columns if c.lower().startswith("predicted_next_purchase_date".lower())] or [c for c in df.columns if c.lower() in {"date","recommended_date","next_purchase_date"}]
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
        "Recommended_Amount_P90": ["Recommended_Amount_P90","P90","Rec_P90"],
        "Baseline_Amount": ["Baseline_Amount","Baseline"]
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
def load_txns(path):
    try:
        tx = pd.read_excel(path)
    except Exception:
        return pd.DataFrame()
    colmap = {
        "Client number": "Client",
        "Product Name": "Product",
        "Transaction Date": "Date",
        "Transaction Amount (SGD)": "Amount",
    }
    for k,v in colmap.items():
        if k in tx.columns and v not in tx.columns:
            tx[v] = tx[k]
    keep = [c for c in ["Client","Product","Date","Amount"] if c in tx.columns]
    tx = tx[keep].copy()
    if "Date" in tx.columns:
        tx["Date"] = pd.to_datetime(tx["Date"], errors="coerce")
    return tx

cluster_colors = {
    "Passive Long-Term Investor": "#1f77b4",
    "Regular Retail Investor": "#ff7f0e",
    "Ultra High-Net-Worth": "#2ca02c",
    "New/Single-Transaction": "#7f7f7f",
}

path_reco = st.sidebar.text_input("Recommendations file", value="recommendationOutput.xlsx")
path_tx = st.sidebar.text_input("Transactions file (for recent product)", value="cleaned_data.xlsx")

df = load_recos(path_reco)
tx = load_txns(path_tx)

if tx.empty:
    last_tx = pd.DataFrame(columns=["Client","Recent_Product","Recent_Date"])
else:
    tx_sorted = tx.sort_values(["Client","Date"]).dropna(subset=["Client"]) if "Date" in tx.columns else tx
    last = tx_sorted.groupby("Client").tail(1)
    last_tx = last[["Client"]].copy()
    last_tx["Recent_Product"] = last["Product"].values if "Product" in last.columns else np.nan
    last_tx["Recent_Date"] = last["Date"].values if "Date" in last.columns else pd.NaT

if not last_tx.empty:
    df = df.merge(last_tx, on="Client", how="left")
else:
    if "Recent_Product" not in df.columns:
        df["Recent_Product"] = np.nan
    if "Recent_Date" not in df.columns:
        df["Recent_Date"] = pd.NaT

if "EventDate" not in df.columns:
    df["EventDate"] = pd.NaT

# Fallback: compute EventDate from transactions if missing
if df["EventDate"].isna().any() and not tx.empty and "Date" in tx.columns:
    tx_s = tx.dropna(subset=["Client"]).copy()
    tx_s["Date"] = pd.to_datetime(tx_s["Date"], errors="coerce")
    tx_s = tx_s.sort_values(["Client", "Date"]).dropna(subset=["Date"]).copy()
    # Compute days since last
    tx_s["Days_Since_Last"] = tx_s.groupby("Client")["Date"].diff().dt.days
    agg = tx_s.groupby("Client").agg(
        Last_Date=("Date", "max"),
        Median_Interval=("Days_Since_Last", lambda s: float(s.dropna().median()) if s.dropna().size else np.nan)
    ).reset_index()
    # Default median interval 30 if missing
    agg["Median_Interval"].fillna(30.0, inplace=True)
    agg["Fallback_EventDate"] = agg["Last_Date"] + pd.to_timedelta(agg["Median_Interval"].round().astype(int), unit="D")
    df = df.merge(agg[["Client", "Fallback_EventDate"]], on="Client", how="left")
    # Fill only missing EventDate
    df["EventDate"] = pd.to_datetime(df["EventDate"], errors="coerce")
    df["EventDate"].fillna(df["Fallback_EventDate"], inplace=True)
    df.drop(columns=[c for c in ["Fallback_EventDate"] if c in df.columns], inplace=True)

min_date = pd.to_datetime(df["EventDate"].min()) if df["EventDate"].notna().any() else None
max_date = pd.to_datetime(df["EventDate"].max()) if df["EventDate"].notna().any() else None

st.sidebar.markdown("### Filters")
start_date, end_date = st.sidebar.date_input(
    "Date range", 
    value=(min_date.date() if min_date is not None else datetime.today().date(),
           (max_date.date() if max_date is not None else (datetime.today()+timedelta(days=30)).date())),
)
clusters = sorted([c for c in df["Cluster_Name"].dropna().unique().tolist()])
selected_clusters = st.sidebar.multiselect("Clusters", options=clusters, default=clusters)
min_amt = float(np.nanmin(df["Recommended_Amount_P50"])) if df["Recommended_Amount_P50"].notna().any() else 0.0
max_amt = float(np.nanmax(df["Recommended_Amount_P50"])) if df["Recommended_Amount_P50"].notna().any() else 0.0
amt_range = st.sidebar.slider("P50 amount range (SGD)", min_value=0.0, max_value=max(1000.0, max_amt), value=(0.0, max_amt))
client_q = st.sidebar.text_input("Search client")

mask = df["EventDate"].between(pd.to_datetime(start_date), pd.to_datetime(end_date))
if selected_clusters:
    mask &= df["Cluster_Name"].isin(selected_clusters)
if df["Recommended_Amount_P50"].notna().any():
    mask &= df["Recommended_Amount_P50"].fillna(0).between(amt_range[0], amt_range[1])
if client_q:
    mask &= df["Client"].astype(str).str.contains(client_q, case=False, na=False)

fdf = df[mask].copy()

st.title("Recommendations Calendar")

by_date = fdf.groupby(fdf["EventDate"].dt.date)

events = []
for d, g in by_date:
    g = g.sort_values("Recommended_Amount_P50", ascending=False)
    first_client = str(g.iloc[0]["Client"]) if len(g) else ""
    extra = len(g) - 1
    title = first_client if extra <= 0 else f"{first_client} + {extra} others"
    start_str = pd.to_datetime(d).strftime("%Y-%m-%d")
    events.append({
        "id": f"day-{start_str}",
        "title": title,
        "start": start_str,
        "allDay": True,
        "color": "#444444",
        "extendedProps": {"date": start_str}
    })
    clusters_on_day = g["Cluster_Name"].dropna().unique().tolist()
    for idx, cn in enumerate(clusters_on_day):
        events.append({
            "id": f"dot-{start_str}-{idx}",
            "title": "",
            "start": start_str,
            "allDay": True,
            "color": cluster_colors.get(cn, "#999999"),
            "extendedProps": {"date": start_str, "cluster": cn}
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

st.subheader("Calendar")
cal = calendar(events=events, options=options)

clicked_date = None
if cal.get("eventClick"):
    ev = cal["eventClick"]["event"]
    clicked_date = ev.get("extendedProps", {}).get("date") or ev.get("start")

if clicked_date:
    day = pd.to_datetime(clicked_date).date()
    day_df = by_date.get_group(day).reset_index(drop=True) if day in by_date.groups else pd.DataFrame(columns=fdf.columns)
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
            st.markdown(f"#### {row['Client']}")
            st.caption(str(row.get('Cluster_Name', '')))
            st.metric("Recommended P50", f"${row.get('Recommended_Amount_P50', np.nan):,.0f}")
            st.write("Recent product:", str(row.get("Recent_Product", "")))
            rd = row.get("Recent_Date", pd.NaT)
            st.write("Recent date:", (pd.to_datetime(rd).date() if pd.notna(rd) else "-"))
            st.write("Recommended product:", str(row.get("Recent_Product", "")))
            st.write("Recommended amount:", f"${row.get('Recommended_Amount_P50', np.nan):,.0f}")
        with col2:
            if st.button("Prev", key=f"prev-{clicked_date}"):
                st.session_state[idx_state_key] = (i - 1) % len(day_df)
                st.experimental_rerun()
        with col3:
            if st.button("Next", key=f"next-{clicked_date}"):
                st.session_state[idx_state_key] = (i + 1) % len(day_df)
                st.experimental_rerun()
        if st.button("Show all", key=f"showall-{clicked_date}"):
            st.dataframe(day_df[[c for c in day_df.columns if c not in {"EventDate"}]].sort_values("Recommended_Amount_P50", ascending=False))
            st.download_button(
                label="Download shown (CSV)",
                data=day_df.to_csv(index=False).encode("utf-8"),
                file_name=f"calendar_{clicked_date}.csv",
                mime="text/csv",
            )

st.subheader("Table")
st.dataframe(fdf.sort_values(["EventDate","Recommended_Amount_P50"], ascending=[True, False]))

csv = fdf.to_csv(index=False).encode("utf-8")
st.download_button("Download filtered CSV", data=csv, file_name="filtered_recommendations.csv", mime="text/csv")
