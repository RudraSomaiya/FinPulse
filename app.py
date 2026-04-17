import os
import shutil

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, date
from streamlit_calendar import calendar
import numpy as np
import yfinance as yf
from llm_parser import parse_instructions
from rules import apply_actions, commit_to_excel
from client_plan_llm import generate_client_plan, generate_market_outlook, generate_reminder_content, retrain_writing_profile
from data_manager import save_recommendations, save_reminders
from agent_controller import generate_plan as agent_generate_plan
from preview_engine import simulate as preview_simulate
from calendar_tools import create_event as cal_create_event, update_event as cal_update_event, delete_event as cal_delete_event
from client_tools import get_client_birth_date
import email_sender
import whatsapp_sender
from audio_recorder_streamlit import audio_recorder
import hashlib
from stt_engine import transcribe_audio_bytes

TICKER_OVERRIDES = {
    "TENCENT": "0700.HK",
}

st.set_page_config(page_title="FinPulse Calendar", layout="wide")

st.sidebar.image("aigenthix-BXPI47w2.webp", use_container_width=True)

st.markdown(
    """
    <div style='text-align: center; padding-top: 1rem; padding-bottom: 2rem;'>
        <h1 style='font-size: 4.5rem; font-weight: 800; margin: 0; background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 50%, #10b981 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>FinPulse</h1>
    </div>
    """,
    unsafe_allow_html=True
)

@st.cache_data(show_spinner=False)
def load_recos(path, mtime):
    """Load recommendations with cache keyed by file path and modification time."""
    df = pd.read_excel(path)
    
    # Merge client details
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
def load_text_file(path: str):
    """Load a text file safely, returning an empty string on failure."""
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


@st.cache_data(show_spinner=False)
def load_reminders(path: str, mtime: float):
    if not os.path.exists(path) or not mtime:
        df = pd.DataFrame(columns=["ReminderId", "Client", "Date", "Subject", "Content", "Edited", "Date of edit"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        return df
    try:
        df = pd.read_excel(path)
    except Exception:
        df = pd.DataFrame(columns=["ReminderId", "Client", "Date", "Subject", "Content", "Edited", "Date of edit"])
    for col in ["ReminderId", "Client", "Date", "Subject", "Content", "Edited", "Date of edit"]:
        if col not in df.columns:
            if col == "Date" or col == "Date of edit":
                df[col] = pd.NaT
            elif col == "Edited":
                df[col] = "0"
            else:
                df[col] = ""
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


def commit_reminders_to_excel(df: pd.DataFrame, path: str) -> str:
    backup_path = ""
    try:
        if os.path.exists(path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            root, ext = os.path.splitext(path)
            backup_path = f"{root}.backup_{ts}{ext}"
            shutil.copy2(path, backup_path)
        df_to_write = df.copy()
        df_to_write["Date"] = pd.to_datetime(df_to_write["Date"], errors="coerce")
        df_to_write.to_excel(path, index=False)
    except Exception as e:
        raise e
    return backup_path


def apply_reminder_rules(df: pd.DataFrame, rules: list[dict]) -> tuple[pd.DataFrame, dict[str, int]]:
    df = df.copy()
    added = 0
    removed = 0
    for rule in rules:
        rtype = str(rule.get("type", "")).strip().lower()
        if rtype == "set_reminder":
            date_val = rule.get("date")
            subject = str(rule.get("subject", "")).strip()
            content = str(rule.get("content", "")).strip()
            client_name = str(rule.get("client", "")).strip()
            if not date_val or not subject:
                continue
            target_ts = pd.to_datetime(date_val, errors="coerce")
            if pd.isna(target_ts):
                continue
            if "ReminderId" not in df.columns:
                df["ReminderId"] = ""
            rid = f"R-{int(datetime.now().timestamp()*1000)}-{len(df) + added + 1}"
            new_row = {
                "ReminderId": rid,
                "Date": target_ts,
                "Subject": subject,
                "Content": content,
                "Client": client_name,
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            added += 1
        elif rtype == "remove_reminder":
            date_val = rule.get("date")
            subject = str(rule.get("subject", "")).strip().lower()
            if not date_val or not subject:
                continue
            target_ts = pd.to_datetime(date_val, errors="coerce")
            if pd.isna(target_ts):
                continue
            base = df.copy()
            base["Date"] = pd.to_datetime(base["Date"], errors="coerce")
            candidates = base[base["Date"].dt.date == target_ts.date()]
            if candidates.empty:
                continue
            best_idx = None
            best_score = 0.0
            for idx, row in candidates.iterrows():
                subj = str(row.get("Subject", "")).lower()
                content = str(row.get("Content", "")).lower()
                score = 0.0
                if subject in subj:
                    score += 2.0
                if subject in content:
                    score += 1.0
                if score == 0.0:
                    for token in subject.split():
                        token = token.strip()
                        if token and (token in subj or token in content):
                            score += 0.1
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx is not None:
                df = df.drop(index=best_idx).reset_index(drop=True)
                removed += 1
    return df, {"reminders_added": added, "reminders_removed": removed}


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

rem_path = "reminders.xlsx"
rem_mtime = os.path.getmtime(rem_path) if os.path.exists(rem_path) else 0
reminders_df = load_reminders(rem_path, rem_mtime)

tx_path = "cleaned_data.xlsx"
tx_mtime = os.path.getmtime(tx_path) if os.path.exists(tx_path) else 0
tx_df = load_transactions(tx_path, tx_mtime)
client_history_map, tx_product_universe = build_client_history(tx_df)

# Market outlook inputs (temporary: from text files; later these can be sourced from a database)
profile_path = "jonathan-writing-profile.txt"
outlook_path = "marketoutlook-temporary.txt"
_profile_text = load_text_file(profile_path)
_outlook_text = load_text_file(outlook_path)
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

# ----- AI Agent (preview then confirm) -----
if "agent_plan" not in st.session_state:
    st.session_state["agent_plan"] = None
if "agent_preview" not in st.session_state:
    st.session_state["agent_preview"] = None
if "agent_query" not in st.session_state:
    st.session_state["agent_query"] = ""

with st.expander("AI Agent", expanded=bool(st.session_state.get("agent_plan"))):
    # No key= on text_input — allows st.session_state["agent_query"] to be freely
    # updated before rerun (Streamlit blocks writes to a widget's own key after render).
    agent_query = st.text_input("Request", value=st.session_state["agent_query"])
    
    col_run, _, col_mic = st.columns([1.5, 6, 1.5])
    
    with col_run:
        run_clicked = st.button("Generate plan", key="agent_run")
        
    with col_mic:
        st.markdown("<div style='text-align: right;'>", unsafe_allow_html=True)
        audio_bytes = audio_recorder(text="", icon_name="microphone", icon_size="2x")
        st.markdown("</div>", unsafe_allow_html=True)
        
    if audio_bytes:
        audio_hash = hashlib.md5(audio_bytes).hexdigest()
        # Prevent re-processing the same clip on every Streamlit rerun
        if st.session_state.get("last_processed_audio") != audio_hash:
            with st.spinner("🎙️ Transcribing audio..."):
                transcript = transcribe_audio_bytes(audio_bytes)
                if transcript:
                    # agent_query holds what the user typed; append the transcript to it.
                    # We write to agent_query (not the widget key) — safe because there's no key.
                    current = (agent_query or "").strip()
                    st.session_state["agent_query"] = (current + " " + transcript).strip() if current else transcript
                    st.session_state["last_processed_audio"] = audio_hash
                    st.rerun()
                else:
                    st.session_state["last_processed_audio"] = audio_hash
                    st.toast("Transcription empty. Please check your microphone.")

    if run_clicked:
        # agent_query is the return value of the text_input — always up to date
        latest_query = (agent_query or "").strip()
        if not latest_query:
            st.warning("Enter a request.")
        else:
            st.session_state["agent_query"] = latest_query
            with st.spinner("Generating plan..."):
                try:
                    client_df = st.session_state.get("applied_df") if isinstance(st.session_state.get("applied_df"), pd.DataFrame) and len(st.session_state.get("applied_df", [])) > 0 else df
                    rem_df = st.session_state.get("reminders_df", reminders_df)
                    plan = agent_generate_plan(latest_query, client_df=client_df, reminders_df=rem_df, profile_text=_profile_text, tx_df=tx_df)
                    st.session_state["agent_plan"] = plan
                    st.session_state["agent_preview"] = preview_simulate(plan, rem_df, client_df)
                except Exception as e:
                    st.error(str(e))
                    st.session_state["agent_plan"] = None
                    st.session_state["agent_preview"] = None

    plan = st.session_state.get("agent_plan")
    preview = st.session_state.get("agent_preview")
    if plan:
        st.markdown("**Reasoning:** " + (plan.get("reasoning") or "—"))
    if preview:
        if preview.get("events_to_create"):
            st.markdown("**Events to create**")
            st.dataframe(preview["events_to_create"], use_container_width=True)
        if preview.get("events_to_modify"):
            st.markdown("**Events to modify**")
            st.json(preview["events_to_modify"])
        if preview.get("events_to_delete"):
            st.markdown("**Events to delete**")
            st.dataframe(preview["events_to_delete"], use_container_width=True)
        if preview.get("recommendation_changes"):
            st.markdown("**Recommendation changes**")
            st.dataframe(preview["recommendation_changes"], use_container_width=True)
        if st.button("Confirm and apply", key="agent_confirm"):
            try:
                rem_df = st.session_state.get("reminders_df", reminders_df).copy()
                rec_df = st.session_state.get("applied_df") if isinstance(st.session_state.get("applied_df"), pd.DataFrame) and len(st.session_state.get("applied_df", [])) > 0 else df.copy()
                plan = st.session_state["agent_plan"]
                for item in plan.get("events_to_create") or []:
                    if isinstance(item, dict):
                        title = (item.get("title") or "").strip()
                        client_id = (item.get("client") or "").strip()
                        use_birthdate = item.get("use_client_birthdate") is True
                        birth_keywords = ("birthday", "birthdate", "birth date", "on their birth", "call on birth", "wish on birth", "on birthdates", "on birthdate")
                        if not use_birthdate and title:
                            use_birthdate = any(kw in title.lower() for kw in birth_keywords)
                        if not use_birthdate:
                            query = (st.session_state.get("agent_query") or "").lower()
                            use_birthdate = any(kw in query for kw in birth_keywords)
                        d = None
                        # For any birthdate-related event, always use Client_Birthdate from the sheet (DD/MM); never use LLM date
                        if use_birthdate and client_id and "Client_Birthdate" in rec_df.columns:
                            d = get_client_birth_date(client_id, rec_df, date.today().year)
                        if d is None:
                            d = item.get("date")
                            if isinstance(d, str):
                                d = pd.to_datetime(d).date() if d else date.today()
                            elif d is not None and hasattr(d, "date"):
                                d = d.date()
                            else:
                                d = date.today()
                        result = cal_create_event(
                            item.get("client", ""),
                            d,
                            item.get("title", "Reminder"),
                            item.get("amount"),
                            reminders_df=rem_df,
                            content=item.get("content"),
                        )
                        if result.get("reminders_df") is not None:
                            rem_df = result["reminders_df"]
                for item in plan.get("events_to_modify") or []:
                    if isinstance(item, dict) and item.get("id") and item.get("fields"):
                        rem_df = cal_update_event(item["id"], item["fields"], rem_df)
                for eid in plan.get("events_to_delete") or []:
                    if isinstance(eid, str):
                        rem_df = cal_delete_event(eid, rem_df)
                for item in plan.get("recommendation_changes") or []:
                    if isinstance(item, dict) and item.get("client") and item.get("field") is not None:
                        mask = rec_df["Client"].astype(str).str.strip() == str(item["client"]).strip()
                        if mask.any() and item["field"] in rec_df.columns:
                            rec_df.loc[mask, item["field"]] = item.get("value")
                save_reminders(rem_df, rem_path)
                if plan.get("recommendation_changes"):
                    save_recommendations(rec_df, rec_path)
                    st.session_state["applied_df"] = rec_df
                    st.session_state["use_overrides"] = True
                st.session_state["reminders_df"] = rem_df
                st.session_state["agent_plan"] = None
                st.session_state["agent_preview"] = None
                st.session_state["agent_query"] = ""
                st.success("Changes applied.")
                st.rerun()
            except Exception as e:
                st.error("Apply failed: " + str(e))

st.sidebar.markdown("### Writing Profile")
with st.sidebar.expander("Writing Profile Details", expanded=False):
    if st.button("Show current writing profile", key="btn_show_profile"):
        st.session_state["show_profile"] = not st.session_state.get("show_profile", False)
    if st.session_state.get("show_profile"):
        st.text_area("Current Profile", value=_profile_text, height=200, disabled=True)
    
    if st.button("Retrain writing style", key="retrain_profile"):
        with st.spinner("Retraining writing profile based on recent edits..."):
            try:
                rem = st.session_state.get("reminders_df", reminders_df).copy()
                if "Edited" in rem.columns and "Date of edit" in rem.columns:
                    edited_rem = rem[rem["Edited"].astype(str) == "1"].copy()
                    if not edited_rem.empty:
                        edited_rem["Date of edit"] = pd.to_datetime(edited_rem["Date of edit"], errors="coerce")
                        edited_rem = edited_rem.sort_values(by="Date of edit", ascending=False).head(20)
                        
                        learning_data = []
                        for _, r in edited_rem.iterrows():
                            learning_data.append({
                                "subject": str(r.get("Subject", "")),
                                "content": str(r.get("Content", ""))
                            })
                        
                        new_profile = retrain_writing_profile(_profile_text, learning_data)
                        
                        if new_profile and new_profile != _profile_text:
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            backup_file = f"jonathan-writing-profile_backup_{ts}.txt"
                            with open(profile_path, "r", encoding="utf-8") as f:
                                old_txt = f.read()
                            with open(backup_file, "w", encoding="utf-8") as f:
                                f.write(old_txt)
                            
                            with open(profile_path, "w", encoding="utf-8") as f:
                                f.write(new_profile)
                            
                            st.success(f"Writing profile retrained and updated! Backup saved to {backup_file}")
                            st.rerun()
                        else:
                            st.info("No significant changes were generated by the model.")
                    else:
                        st.warning("No human-edited reminders found to train from.")
                else:
                    st.warning("Reminders dataset does not have 'Edited' and 'Date of edit' columns.")
            except Exception as e:
                st.error(f"Failed to retrain: {e}")

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
        rules = actions.get("rules", [])
        rec_rule_types = {
            "suppress_client",
            "amount_multiplier",
            "amount_set",
            "change_recommendation",
            "seasonality_inject",
            "change_frequency",
            "add_entry",
            "add_recurring",
            "delete_where",
            "remove_entry",
        }
        rec_rules = [r for r in rules if str(r.get("type", "")).strip().lower() in rec_rule_types]
        reminder_rules = [r for r in rules if str(r.get("type", "")).strip().lower() in {"set_reminder", "remove_reminder"}]

        new_df = df
        summary = {"removed": 0, "modified": 0, "added": 0}
        if rec_rules:
            new_df, summary = apply_actions(df, {"rules": rec_rules}, date.today())
            st.session_state["applied_df"] = new_df
            st.session_state["use_overrides"] = True

        # Apply reminder rules and auto-save to reminders.xlsx
        if reminder_rules:
            current_rem_df = st.session_state.get("reminders_df", reminders_df)
            new_rem_df, rem_summary = apply_reminder_rules(current_rem_df, reminder_rules)
            commit_reminders_to_excel(new_rem_df, rem_path)
            st.session_state["reminders_df"] = new_rem_df
            # Merge reminder summary into main summary dict for display if needed
            summary.update(rem_summary)

        st.session_state["summary"] = summary
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

# Filter reminders into the same date window
current_reminders_df = st.session_state.get("reminders_df", reminders_df)
if not current_reminders_df.empty:
    current_reminders_df = current_reminders_df.copy()
    current_reminders_df["Date"] = pd.to_datetime(current_reminders_df["Date"], errors="coerce")
    rem_mask = current_reminders_df["Date"].between(pd.to_datetime(start_date), pd.to_datetime(end_date))
    rem_fdf = current_reminders_df[rem_mask].copy()
else:
    rem_fdf = current_reminders_df

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

# Reminder events (red) grouped by date
if not rem_fdf.empty:
    rem_dates = rem_fdf["Date"].dt.date.dropna().tolist()
    unique_dates = sorted({d for d in rem_dates})
    for d in unique_dates:
        day_rows = rem_fdf[rem_fdf["Date"].dt.date == d]
        count = int(len(day_rows))
        start_str = pd.to_datetime(d).strftime("%Y-%m-%d")
        title = "Reminder" if count <= 1 else f"Reminder + {count - 1}"
        events.append({
            "id": f"rem-{start_str}",
            "title": title,
            "start": start_str,
            "allDay": True,
            "color": "#dc2626",
            "extendedProps": {"date": start_str, "kind": "reminder"}
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
    day_rem = pd.DataFrame()
    if not current_reminders_df.empty:
        tmp = current_reminders_df.copy()
        tmp["Date"] = pd.to_datetime(tmp["Date"], errors="coerce")
        day_rem = tmp[tmp["Date"].dt.date == day].reset_index(drop=True)

    if day_df.empty and day_rem.empty:
        st.info("No records for this date.")
    else:
        idx_state_key = f"idx_{clicked_date}"
        if idx_state_key not in st.session_state:
            st.session_state[idx_state_key] = 0
        col1, col2, col3 = st.columns([6,1,1])
        if not day_df.empty:
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

            # First purchase product and live price via yfinance
            first_prod = None
            first_date = None
            first_price = None
            try:
                if tx_df is not None and not tx_df.empty:
                    col_client_id = "Client number"
                    if col_client_id in tx_df.columns:
                        client_id_str = str(row.get('Client', '')).strip()
                        sub = tx_df[tx_df[col_client_id].astype(str) == client_id_str].copy()
                        if not sub.empty:
                            date_cols = [c for c in sub.columns if 'date' in c.lower()]
                            if date_cols:
                                dcol = date_cols[0]
                                sub[dcol] = pd.to_datetime(sub[dcol], errors='coerce')
                                sub = sub[sub[dcol].notna()]
                                if not sub.empty:
                                    sub = sub.sort_values(dcol)
                                    first_row = sub.iloc[0]
                                    first_date = first_row[dcol]
                                    if pd.notna(first_date):
                                        try:
                                            first_date = pd.to_datetime(first_date).date()
                                        except Exception:
                                            pass
                                    # Prefer 'Product Name' for display and ticker; fall back to 'Product Type' only if needed.
                                    prod_col = None
                                    if "Product Name" in sub.columns:
                                        prod_col = "Product Name"
                                    elif "Product Type" in sub.columns:
                                        prod_col = "Product Type"

                                    if prod_col is not None:
                                        first_prod = str(first_row.get(prod_col, '')).strip()
                                        if first_prod:
                                            try:
                                                # Map to a Yahoo Finance symbol only when we have a clear mapping or a simple code.
                                                raw = first_prod.upper().strip()
                                                sym = TICKER_OVERRIDES.get(raw)
                                                # As a simple heuristic, treat short, no-space strings as potential tickers.
                                                if sym is None and " " not in raw and len(raw) <= 10:
                                                    sym = raw

                                                if sym is not None:
                                                    ticker = yf.Ticker(sym)
                                                    info = getattr(ticker, "fast_info", None)
                                                    price_val = None
                                                    if info is not None:
                                                        price_val = getattr(info, "last_price", None) or getattr(info, "lastClose", None)
                                                    if price_val is None:
                                                        hist = ticker.history(period="1d")
                                                        if not hist.empty and 'Close' in hist.columns:
                                                            price_val = float(hist['Close'].iloc[-1])
                                                    if price_val is not None:
                                                        first_price = round(float(price_val), 4)
                                            except Exception:
                                                first_price = None
            except Exception:
                # If anything goes wrong in the lookup, we leave first_price as None and continue
                first_price = None

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            first_date_txt = first_date if first_date is not None and first_date != "NaT" else "-"
            first_prod_txt = first_prod if first_prod else "-"
            price_txt = f"${first_price:,.4f}" if first_price is not None else "-"
            st.markdown(
                f"<div>First Purchase Product: <strong>{first_prod_txt}</strong></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div>First Purchase Date: <strong>{first_date_txt}</strong></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div>Live Price ({first_prod_txt}): <strong>{price_txt}</strong></div>",
                unsafe_allow_html=True,
            )

            # Market outlook (LLM-rewritten using writing profile) - Manual generation with editing
            if "market_outlook_text" not in st.session_state:
                st.session_state["market_outlook_text"] = "Click 'Generate Market Outlook' to create personalized outlook."

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            
            # Helper to check if MO is generated
            mo_val = st.session_state["market_outlook_text"]
            is_mo_generated = "Click 'Generate" not in mo_val and "Market outlook is not available" not in mo_val

            # Market outlook section with generate and edit buttons
            col_outlook, col_generate, col_edit = st.columns([3, 1, 1])
            with col_outlook:
                st.markdown("**Market outlook**")
            with col_generate:
                if st.button("Generate", key="generate_market_outlook", help="Generate personalized market outlook using writing profile"):
                    if _profile_text and _outlook_text:
                        with st.spinner("Generating market outlook..."):
                            st.session_state["market_outlook_text"] = generate_market_outlook(_profile_text, _outlook_text)
                            st.rerun()
                    else:
                        st.session_state["market_outlook_text"] = "Market outlook is not available (missing profile or source text)."
                        st.warning("Missing writing profile or source market outlook text.")
            with col_edit:
                if is_mo_generated:
                    if st.button("✏️", key="btn_edit_mo", help="Edit market outlook"):
                        st.session_state["is_editing_mo"] = True
                        st.rerun()
            
            # Check if market outlook is in edit mode
            if st.session_state.get("is_editing_mo", False):
                edited_outlook = st.text_area(
                    "Edit Market Outlook:",
                    value=st.session_state.get("market_outlook_text", ""),
                    key="ta_edit_outlook_text",
                    height=200
                )
                
                col_save, col_cancel = st.columns([1, 1])
                with col_save:
                    if st.button("💾 Save", key="save_outlook"):
                        st.session_state["market_outlook_text"] = edited_outlook
                        st.session_state["is_editing_mo"] = False
                        st.rerun()
                with col_cancel:
                    if st.button("❌ Cancel", key="cancel_outlook"):
                        st.session_state["is_editing_mo"] = False
                        st.rerun()
            else:
                st.markdown(st.session_state.get("market_outlook_text", "-"))

            # AI-generated future plan paragraph - Manual generation
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

            first_investment_date = row.get('First_Investment_Date', None)
            total_invested_sgd = row.get('Total_Invested_SGD', None)

            plan_context = {
                "client_name": client,
                "cluster": cluster,
                "transactions": tx_list,
                "recommended_product_type": rec_ptype,
                "confidence": conf_val,
                "predicted_amount_sgd": pred_amt,
                "avg_historical_amount": avg_hist,
                "total_transactions": total_tx,
                "first_investment_date": first_investment_date,
                "total_invested_sgd": total_invested_sgd,
                "available_product_types": available_product_types,
                "simple_language": not is_top,
            }

            if "client_plan_cache" not in st.session_state:
                st.session_state["client_plan_cache"] = {}
            cache = st.session_state["client_plan_cache"]
            cache_key = client_id or client
            plan_text = cache.get(cache_key)
            
            if not plan_text:
                plan_text = f"Click 'Generate Plan' to create personalized investment plan for {client}."

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            
            # Future plan section with generate and edit buttons
            is_plan_generated = "Click 'Generate Plan'" not in plan_text
            col_plan, col_generate, col_edit_plan = st.columns([3, 1, 1])
            with col_plan:
                st.markdown("**Future Plan (AI Advisor)**")
            with col_generate:
                if st.button("Generate", key=f"generate_client_plan_{cache_key}", help="Generate personalized investment plan"):
                    with st.spinner("Generating future plan..."):
                        plan_text = generate_client_plan(plan_context)
                        cache[cache_key] = plan_text
                        st.rerun()
            with col_edit_plan:
                if is_plan_generated:
                    if st.button("✏️", key=f"btn_edit_plan_{cache_key}", help="Edit future plan"):
                        st.session_state[f"is_editing_plan_{cache_key}"] = True
                        st.rerun()

            # Check if future plan is in edit mode
            if st.session_state.get(f"is_editing_plan_{cache_key}", False):
                edited_plan = st.text_area(
                    "Edit Future Plan:",
                    value=plan_text,
                    key=f"ta_edit_plan_{cache_key}",
                    height=200
                )
                
                col_save_plan, col_cancel_plan = st.columns([1, 1])
                with col_save_plan:
                    if st.button("💾 Save", key=f"save_plan_{cache_key}"):
                        cache[cache_key] = edited_plan
                        st.session_state[f"is_editing_plan_{cache_key}"] = False
                        st.rerun()
                with col_cancel_plan:
                    if st.button("❌ Cancel", key=f"cancel_plan_{cache_key}"):
                        st.session_state[f"is_editing_plan_{cache_key}"] = False
                        st.rerun()
            else:
                st.markdown(plan_text)

            # Email / WhatsApp sending section
            st.markdown("---")
            col_mo_chk, col_fp_chk, col_send_email, col_send_wa = st.columns([2, 2, 1.5, 1.5])
            with col_mo_chk:
                send_mo = st.checkbox("Include Market Outlook", key=f"send_mo_{clicked_date}", value=True)
            with col_fp_chk:
                send_fp = st.checkbox("Include Client Summary", key=f"send_fp_{clicked_date}", value=True)

            # -- helper to gather checked content --
            def _gather_send_content():
                mo_text = st.session_state.get("market_outlook_text") if send_mo else None
                if mo_text in ("Click 'Generate Market Outlook' to create personalized outlook.",
                               "Market outlook is not available (missing profile or source text)."):
                    mo_text = None
                fp_text = plan_text if send_fp else None
                if fp_text and "Click 'Generate Plan'" in fp_text:
                    fp_text = None
                return mo_text, fp_text

            with col_send_email:
                if st.button("Send via email", key=f"send_client_email_{clicked_date}", use_container_width=True):
                    client_email = str(row.get("Client_email", "")).strip()
                    if not client_email or client_email == 'nan':
                        st.error(f"Client email missing for {client}")
                    else:
                        mo_text, fp_text = _gather_send_content()
                        if not mo_text and not fp_text:
                            st.warning("Please select at least one generated section to send.")
                        else:
                            try:
                                with st.spinner("Sending email..."):
                                    email_sender.send_client_report(client_email, mo_text, fp_text)
                                st.success("Email sent successfully!")
                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"Failed to send: {str(e)}")

            with col_send_wa:
                if st.button("Send via WhatsApp", key=f"send_client_wa_{clicked_date}", use_container_width=True):
                    client_phone = str(row.get("Client_phone_number", "")).strip()
                    if not client_phone or client_phone == 'nan':
                        st.error(f"Client phone number missing for {client}")
                    else:
                        mo_text, fp_text = _gather_send_content()
                        if not mo_text and not fp_text:
                            st.warning("Please select at least one generated section to send.")
                        else:
                            try:
                                with st.spinner("Sending WhatsApp message..."):
                                    whatsapp_sender.send_client_report(client_phone, mo_text, fp_text)
                                st.success("WhatsApp message sent successfully!")
                            except ValueError as e:
                                st.error(str(e))
                            except Exception as e:
                                st.error(f"Failed to send: {str(e)}")
        if not day_df.empty:
            with col2:
                if st.button("Prev", key=f"prev-{clicked_date}"):
                    st.session_state[idx_state_key] = (st.session_state[idx_state_key] - 1) % len(day_df)
                    st.rerun()
            with col3:
                if st.button("Next", key=f"next-{clicked_date}"):
                    st.session_state[idx_state_key] = (st.session_state[idx_state_key] + 1) % len(day_df)
                    st.rerun()
            if st.button("Show all", key=f"showall-{clicked_date}"):
                st.dataframe(day_df[[c for c in day_df.columns if c not in {"EventDate"}]].sort_values("Recommended_Amount_P50", ascending=False))
                st.download_button(
                    label="Download shown (CSV)",
                    data=day_df.to_csv(index=False).encode("utf-8"),
                    file_name=f"calendar_{clicked_date}.csv",
                    mime="text/csv",
                )

        # Reminders for this day
        if not day_rem.empty:
            st.markdown("---")
            st.markdown("**Reminders**")

            # Bulk actions
            cols_rem_actions = st.columns([2, 2, 2, 2])
            with cols_rem_actions[0]:
                if st.button("Send via email", key=f"btn_send_bulk_{clicked_date}", use_container_width=True):
                    selected_idxs = []
                    for ridx in day_rem.index:
                        if st.session_state.get(f"chk_rem_{clicked_date}_{ridx}", False):
                            selected_idxs.append(ridx)
                    
                    if not selected_idxs:
                        st.warning("No reminders selected.")
                    else:
                        success_count = 0
                        errors = []
                        for ridx in selected_idxs:
                            sel_r = day_rem.loc[ridx]
                            subj = str(sel_r.get("Subject", "")).strip()
                            content = str(sel_r.get("Content", "")).strip()
                            rem_client_name = str(sel_r.get("Client", "")).strip()
                            
                            rem_client_email = ""
                            if rem_client_name:
                                match = df[df["Client"].astype(str).str.strip() == rem_client_name]
                                if not match.empty:
                                    rem_client_email = str(match["Client_email"].iloc[0]).strip()
                                
                            if not rem_client_email or rem_client_email == 'nan':
                                errors.append(f"Email missing for {rem_client_name or 'Unknown Client'}")
                                continue
                                
                            try:
                                email_sender.send_reminder_email(rem_client_email, subj, content)
                                success_count += 1
                            except Exception as e:
                                errors.append(str(e))
                                
                        if success_count > 0:
                            st.success(f"Sent {success_count} reminder(s).")
                        if errors:
                            for e in set(errors):
                                st.error(e)

            with cols_rem_actions[1]:
                if st.button("Send via WhatsApp", key=f"btn_wa_bulk_{clicked_date}", use_container_width=True):
                    selected_idxs = []
                    for ridx in day_rem.index:
                        if st.session_state.get(f"chk_rem_{clicked_date}_{ridx}", False):
                            selected_idxs.append(ridx)

                    if not selected_idxs:
                        st.warning("No reminders selected.")
                    else:
                        success_count = 0
                        errors = []
                        for ridx in selected_idxs:
                            sel_r = day_rem.loc[ridx]
                            subj = str(sel_r.get("Subject", "")).strip()
                            content = str(sel_r.get("Content", "")).strip()
                            rem_client_name = str(sel_r.get("Client", "")).strip()

                            rem_client_phone = ""
                            if rem_client_name:
                                match = df[df["Client"].astype(str).str.strip() == rem_client_name]
                                if not match.empty and "Client_phone_number" in match.columns:
                                    rem_client_phone = str(match["Client_phone_number"].iloc[0]).strip()

                            if not rem_client_phone or rem_client_phone == 'nan':
                                errors.append(f"Phone number missing for {rem_client_name or 'Unknown Client'}")
                                continue

                            try:
                                whatsapp_sender.send_reminder_message(rem_client_phone, subj, content)
                                success_count += 1
                            except Exception as e:
                                errors.append(str(e))

                        if success_count > 0:
                            st.success(f"Sent {success_count} WhatsApp message(s).")
                        if errors:
                            for e in set(errors):
                                st.error(e)

            with cols_rem_actions[2]:
                if st.button("Delete", key=f"btn_del_bulk_{clicked_date}", use_container_width=True):
                    selected_idxs = []
                    for ridx in day_rem.index:
                        if st.session_state.get(f"chk_rem_{clicked_date}_{ridx}", False):
                            selected_idxs.append(ridx)
                            
                    if not selected_idxs:
                        st.warning("No reminders selected.")
                    else:
                        rids_to_del = [str(day_rem.loc[x, "ReminderId"]) for x in selected_idxs]
                        base_rem_df = st.session_state.get("reminders_df", current_reminders_df).copy()
                        base_rem_df = base_rem_df[~base_rem_df["ReminderId"].astype(str).isin(rids_to_del)].reset_index(drop=True)
                        commit_reminders_to_excel(base_rem_df, rem_path)
                        st.session_state["reminders_df"] = base_rem_df
                        st.rerun()

            for ridx, r in day_rem.iterrows():
                rcols = st.columns([0.5, 6.5, 1])
                with rcols[0]:
                    st.checkbox("", key=f"chk_rem_{clicked_date}_{ridx}", label_visibility="collapsed")
                with rcols[1]:
                    reminder_id = str(r.get("ReminderId", ""))
                    
                    # Check if this reminder is in edit mode
                    edit_key = f"edit_reminder_{clicked_date}_{ridx}"
                    is_editing = st.session_state.get(edit_key, False)
                    
                    if is_editing:
                        # Edit mode - show input fields
                        edited_subject = st.text_input(
                            "Title:",
                            value=str(r.get("Subject", "")).strip() or "",
                            key=f"edit_subject_{edit_key}"
                        )
                        edited_content = st.text_area(
                            "Content:",
                            value=str(r.get("Content", "")).strip() or "",
                            key=f"edit_content_{edit_key}",
                            height=100
                        )
                        
                        col_save, col_cancel = st.columns([1, 1])
                        with col_save:
                            if st.button("💾", key=f"save_{edit_key}", help="Save changes"):
                                # Update the reminder
                                base_rem_df = st.session_state.get("reminders_df", current_reminders_df).copy()
                                if reminder_id:
                                    mask = base_rem_df["ReminderId"].astype(str) == reminder_id
                                    if mask.any():
                                        base_rem_df.loc[mask, "Subject"] = edited_subject
                                        base_rem_df.loc[mask, "Content"] = edited_content
                                        base_rem_df.loc[mask, "Edited"] = "1"
                                        base_rem_df.loc[mask, "Date of edit"] = pd.Timestamp.now()
                                        commit_reminders_to_excel(base_rem_df, rem_path)
                                        st.session_state["reminders_df"] = base_rem_df
                                        st.session_state[edit_key] = False
                                        st.rerun()
                        with col_cancel:
                            if st.button("❌", key=f"cancel_edit_{edit_key}", help="Cancel editing"):
                                st.session_state[edit_key] = False
                                st.rerun()
                    else:
                        # Display mode - show content with edit button
                        subj = str(r.get("Subject", "")).strip() or "(No subject)"
                        content = str(r.get("Content", "")).strip() or "(No content)"
                        
                        # Make title and content clickable for editing
                        col_title, col_edit_btn = st.columns([5, 1])
                        with col_title:
                            if st.markdown(f"**{subj}**"):
                                pass
                        with col_edit_btn:
                            if st.button("✏️", key=f"edit_title_{edit_key}", help="Edit title and content"):
                                st.session_state[edit_key] = True
                                st.rerun()
                        
                        st.markdown(content)
                    
                    # Check if this reminder has an active input box for generation
                    dialog_key = f"generate_dialog_{clicked_date}_{ridx}"
                    if dialog_key in st.session_state and st.session_state[dialog_key].get("show_input", False):
                        # Compact inline input with Send/Cancel buttons
                        col_input, col_send, col_cancel = st.columns([4, 1, 1])
                        with col_input:
                            user_prompt = st.text_input(
                                "Describe content to generate:",
                                key=f"prompt_{dialog_key}",
                                label_visibility="collapsed"
                            )
                        with col_send:
                            if st.button("📤", key=f"send_{dialog_key}", help="Send"):
                                if user_prompt.strip():
                                    with st.spinner("Generating..."):
                                        generated_content = generate_reminder_content(
                                            _profile_text, 
                                            str(r.get("Subject", "")).strip(), 
                                            user_prompt.strip()
                                        )
                                        
                                        # Update the reminder content
                                        base_rem_df = st.session_state.get("reminders_df", current_reminders_df).copy()
                                        if reminder_id:
                                            mask = base_rem_df["ReminderId"].astype(str) == reminder_id
                                            if mask.any():
                                                base_rem_df.loc[mask, "Content"] = generated_content
                                                commit_reminders_to_excel(base_rem_df, rem_path)
                                                st.session_state["reminders_df"] = base_rem_df
                                                
                                                # Close the input box
                                                st.session_state[dialog_key]["show_input"] = False
                                                st.rerun()
                                else:
                                    st.warning("Please enter a prompt")
                        with col_cancel:
                            if st.button("❌", key=f"cancel_{dialog_key}", help="Cancel"):
                                st.session_state[dialog_key]["show_input"] = False
                                st.rerun()
                        
                        st.markdown("---")  # Separator after input box
                        
                with rcols[2]:
                    if not st.session_state.get(f"edit_reminder_{clicked_date}_{ridx}", False):
                        if st.button("Generate", key=f"gen-rem-{clicked_date}-{ridx}", help="Generate content using AI"):
                            # Store the reminder info and show input box
                            st.session_state[f"generate_dialog_{clicked_date}_{ridx}"] = {
                                "reminder_id": reminder_id,
                                "subject": str(r.get("Subject", "")).strip(),
                                "content": str(r.get("Content", "")).strip(),
                                "show_input": True
                            }
                            st.rerun()

st.dataframe(fdf.sort_values(["EventDate","Recommended_Amount_P50"], ascending=[True, False]))

csv = fdf.to_csv(index=False).encode("utf-8")
st.download_button("Download filtered CSV", data=csv, file_name="filtered_recommendations.csv", mime="text/csv")
