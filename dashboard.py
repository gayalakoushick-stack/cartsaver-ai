import os
import sys
import json
import time
import sqlite3
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import streamlit as st
import requests
import plotly.graph_objects as go

# Ensure UTF-8 stdout encoding on Windows console to prevent charmap UnicodeEncodeError
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
    except Exception:
        pass

def safe_log(message: str):
    """Safely print debug messages to stdout handling Windows charmap/cp1252 encoding."""
    try:
        print(message, flush=True)
    except (UnicodeEncodeError, Exception):
        try:
            safe_msg = message.encode("ascii", errors="backslashreplace").decode("ascii")
            print(safe_msg, flush=True)
        except Exception:
            pass

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------
BACKEND_BASE_URL = os.getenv("BACKEND_URL", "https://cartsaver-ai.onrender.com")
ACCENT_COLOR = "#6938EF"
COLOR_RECOVERED = "#12B76A"
COLOR_UNRECOVERED = "#667085"
COLOR_FAILED = "#F04438"

st.set_page_config(
    page_title="CartSaver AI",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------------------------------------------------------
# THEME & STYLESHEET (Streamlit native CSS variables + Inter font, NO emoji)
# -----------------------------------------------------------------------------
CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}}

#MainMenu {{visibility: hidden;}}
header {{visibility: hidden;}}
footer {{visibility: hidden;}}

.block-container {{
    padding-top: 1.5rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1280px !important;
}}

/* Card containers */
.cs-card {{
    background-color: var(--secondary-background-color);
    border: 1px solid rgba(102, 112, 133, 0.2);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 16px;
    color: var(--text-color);
}}

.cs-metric-card {{
    background-color: var(--secondary-background-color);
    border: 1px solid rgba(102, 112, 133, 0.2);
    border-radius: 10px;
    padding: 22px 20px;
    min-height: 128px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-sizing: border-box;
}}

.cs-hero-card {{
    background-color: var(--secondary-background-color);
    border: 1px solid rgba(105, 56, 239, 0.35);
    border-radius: 10px;
    padding: 22px 20px;
    min-height: 128px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-sizing: border-box;
}}

.cs-metric-label {{
    font-size: 12px;
    font-weight: 600;
    color: var(--text-color);
    opacity: 0.7;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}}

.cs-metric-val {{
    font-size: 26px;
    font-weight: 700;
    color: var(--text-color);
    line-height: 1.15;
    margin-top: 6px;
}}

.cs-hero-val {{
    font-size: 32px;
    font-weight: 800;
    color: {ACCENT_COLOR} !important;
    line-height: 1.15;
    margin-top: 6px;
}}

/* Pill badges with 10% opacity background */
.cs-pill-recovered {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 500;
    background-color: rgba(18, 183, 106, 0.1);
    color: {COLOR_RECOVERED};
    border: 1px solid rgba(18, 183, 106, 0.25);
    white-space: nowrap;
}}

.cs-pill-unrecovered {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 500;
    background-color: rgba(102, 112, 133, 0.1);
    color: {COLOR_UNRECOVERED};
    border: 1px solid rgba(102, 112, 133, 0.25);
    white-space: nowrap;
}}

.cs-pill-failed {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 500;
    background-color: rgba(240, 68, 56, 0.1);
    color: {COLOR_FAILED};
    border: 1px solid rgba(240, 68, 56, 0.25);
    white-space: nowrap;
}}

.cs-pill-stopped {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 500;
    background-color: rgba(102, 112, 133, 0.1);
    color: {COLOR_UNRECOVERED};
    border: 1px solid rgba(102, 112, 133, 0.25);
    white-space: nowrap;
}}

/* Progress bar for recovery score */
.cs-progress-track {{
    width: 100%;
    background-color: rgba(102, 112, 133, 0.15);
    border-radius: 6px;
    height: 7px;
    overflow: hidden;
}}

.cs-progress-fill {{
    height: 100%;
    background-color: {ACCENT_COLOR};
    border-radius: 6px;
}}

/* Table rows styling */
.cs-table-header {{
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-color);
    opacity: 0.65;
    padding: 10px 8px;
    border-bottom: 1px solid rgba(102, 112, 133, 0.2);
}}

.cs-table-row {{
    padding: 12px 8px;
    border-bottom: 1px solid rgba(102, 112, 133, 0.12);
    align-items: center;
}}

/* Button styling adhering to accent and native theme */
div.stButton > button {{
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 6px 14px !important;
    border: 1px solid rgba(102, 112, 133, 0.25) !important;
    background-color: transparent !important;
    color: var(--text-color) !important;
    transition: all 0.15s ease !important;
}}

div.stButton > button:hover {{
    border-color: {ACCENT_COLOR} !important;
    color: {ACCENT_COLOR} !important;
}}

div.stButton > button[kind="primary"] {{
    background-color: {ACCENT_COLOR} !important;
    border-color: {ACCENT_COLOR} !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}}

div.stButton > button[kind="primary"]:hover {{
    background-color: #5925dc !important;
    border-color: #5925dc !important;
    color: #ffffff !important;
}}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# ROBUST API CLIENT
# Wraps every request in a try/except block, checks response.status_code == 200,
# and returns (parsed_json, None) on success or (None, error_str) on failure.
# -----------------------------------------------------------------------------
def fetch_api(endpoint: str, method: str = "GET", params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[str]]:
    url = f"{BACKEND_BASE_URL}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=6)
        elif method == "POST":
            response = requests.post(url, json=json_data, timeout=10)
        else:
            return None, f"Unsupported HTTP method: {method}"

        if response.status_code == 200:
            try:
                return response.json(), None
            except Exception as parse_err:
                return None, f"Failed to parse JSON response from {endpoint}: {parse_err}"
        else:
            return None, f"Backend returned HTTP {response.status_code} for {endpoint}: {response.text}"
    except requests.exceptions.RequestException:
        return None, f"Unable to reach CartSaver AI backend at {BACKEND_BASE_URL}. Please verify the FastAPI service is running."
    except Exception as e:
        return None, f"Unexpected error during API call to {endpoint}: {e}"

# -----------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# -----------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "Overview"

if "selected_cart_id" not in st.session_state:
    st.session_state.selected_cart_id = None

if "flash_message" not in st.session_state:
    st.session_state.flash_message = None

if "explorer_page_num" not in st.session_state:
    st.session_state.explorer_page_num = 1

# -----------------------------------------------------------------------------
# FLASH NOTIFICATION BANNER (Post-action feedback)
# -----------------------------------------------------------------------------
if st.session_state.flash_message:
    msg = st.session_state.flash_message
    msg_type = msg.get("type", "info")
    msg_text = msg.get("text", "")
    if msg_type == "success":
        st.success(msg_text)
    elif msg_type == "warning":
        st.warning(msg_text)
    elif msg_type == "error":
        st.error(msg_text)
    else:
        st.info(msg_text)
    st.session_state.flash_message = None

# -----------------------------------------------------------------------------
# BACKEND WAKE-UP PING (Handles Render free-tier sleep mode gracefully)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def ping_backend(base_url: str) -> bool:
    """Ping /health or root endpoint with a 15-second timeout to wake up Render free-tier backend."""
    clean_base = base_url.rstrip("/")
    for endpoint in ["/health", "/"]:
        try:
            resp = requests.get(f"{clean_base}{endpoint}", timeout=15)
            if resp.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            continue
        except Exception:
            continue
    return False

with st.spinner("Connecting to CartSaver AI Secure Backend... (Waking up server if inactive)"):
    backend_is_online = ping_backend(BACKEND_BASE_URL)

if not backend_is_online:
    ping_backend.clear()
    st.warning(
        "CartSaver AI backend is taking longer than expected to respond (Render free-tier spin-up). "
        "The server may still be booting up. Please allow up to a minute and refresh the page."
    )

# -----------------------------------------------------------------------------
# TOP HEADER BAR
# "CartSaver AI" name on the left.
# Three nav items (Overview, Carts Explorer, Audit Trail) as buttons using st.session_state.page.
# Active one colored in the accent.
# Cart count on the right (plain text, e.g. "300 carts"), no avatar icons.
# Note: A failure here defaults to "-- carts" without halting other page sections.
# -----------------------------------------------------------------------------
header_summary, header_err = fetch_api("/analytics/summary")
cart_count_text = "-- carts"
if header_summary and isinstance(header_summary, dict) and "total_carts" in header_summary:
    cart_count_text = f"{header_summary['total_carts']} carts"

header_col1, header_col2, header_col3 = st.columns([2.2, 4.8, 1.8])

with header_col1:
    st.markdown(
        """
        <div style="padding: 6px 0;">
            <div style="font-size: 20px; font-weight: 700; letter-spacing: -0.4px; color: var(--text-color);">
                CartSaver AI
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_col2:
    nav_btn1, nav_btn2, nav_btn3, nav_spacer = st.columns([1.1, 1.4, 1.2, 1.0])
    
    with nav_btn1:
        is_active = (st.session_state.page == "Overview")
        if st.button("Overview", key="nav_overview", type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.page = "Overview"
            st.rerun()
            
    with nav_btn2:
        is_active = (st.session_state.page == "Carts Explorer")
        if st.button("Carts Explorer", key="nav_explorer", type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.page = "Carts Explorer"
            st.rerun()
            
    with nav_btn3:
        is_active = (st.session_state.page == "Audit Trail")
        if st.button("Audit Trail", key="nav_audit", type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.page = "Audit Trail"
            st.rerun()

with header_col3:
    st.markdown(
        f"""
        <div style="text-align: right; padding: 10px 0; font-size: 14px; font-weight: 500; color: var(--text-color); opacity: 0.85;">
            {cart_count_text}
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='border-bottom: 1px solid rgba(102, 112, 133, 0.2); margin-top: 4px; margin-bottom: 24px;'></div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# PAGE 1: OVERVIEW
# -----------------------------------------------------------------------------
if st.session_state.page == "Overview":
    overview_col_left, overview_col_right = st.columns([3.2, 1.8])

    with overview_col_left:
        st.markdown(
            """
            <div style="margin-bottom: 18px;">
                <div style="font-size: 22px; font-weight: 700; color: var(--text-color); margin-bottom: 4px;">Portfolio Overview</div>
                <div style="font-size: 14px; color: var(--text-color); opacity: 0.7;">Autonomous recovery insights and high-level risk engine telemetry.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with overview_col_right:
        run_pipeline = st.button("Run Full Pipeline", key="btn_run_pipeline", type="primary", use_container_width=True)
        st.markdown(
            """
            <div style="font-size: 11px; color: var(--text-color); opacity: 0.65; margin-top: 4px; line-height: 1.25; text-align: right;">
                This regenerates all cart data and will take 10-15 minutes.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if run_pipeline:
        workspace_dir = os.path.dirname(os.path.abspath(__file__))
        python_bin = sys.executable

        steps = [
            ("Generating cart data...", "generate_carts.py"),
            ("Scoring and prioritizing...", "score_carts.py"),
            ("Running recovery agent...", "recovery_agent.py"),
        ]

        pipeline_failed = False
        with st.status("Running full pipeline...", expanded=True) as status:
            for step_label, script_name in steps:
                st.write(step_label)
                script_path = os.path.join(workspace_dir, script_name)
                try:
                    proc = subprocess.run(
                        [python_bin, script_path],
                        cwd=workspace_dir,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace"
                    )
                    if proc.returncode != 0:
                        pipeline_failed = True
                        status.update(label=f"Pipeline failed at step: {script_name}", state="error", expanded=True)
                        st.error(f"Error executing {script_name} (Exit code: {proc.returncode})")
                        err_detail = proc.stderr.strip() if proc.stderr else proc.stdout.strip()
                        if err_detail:
                            st.code(err_detail, language="bash")
                        break
                except Exception as exc:
                    pipeline_failed = True
                    status.update(label=f"Pipeline error running {script_name}", state="error", expanded=True)
                    st.error(f"Failed to launch {script_name}: {exc}")
                    break

            if not pipeline_failed:
                final_rec_rate = None
                try:
                    db_path = os.path.join(workspace_dir, "cartsaver.db")
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*), SUM(CASE WHEN recovered = 1 THEN 1 ELSE 0 END) FROM carts")
                    r = cur.fetchone()
                    conn.close()
                    if r and r[0] and r[0] > 0:
                        final_rec_rate = (r[1] / r[0]) * 100.0
                except Exception as db_err:
                    safe_log(f"[DEBUG] Error querying recovery rate after pipeline: {db_err}")

                if final_rec_rate is not None:
                    success_msg = f"Pipeline complete — Final Recovery Rate: {final_rec_rate:.2f}%"
                else:
                    success_msg = "Pipeline complete"

                status.update(label=success_msg, state="complete", expanded=False)
                st.success(success_msg)
                st.session_state.flash_message = {
                    "type": "success",
                    "text": success_msg
                }
                time.sleep(1.0)
                st.rerun()

    # Use summary fetched in header if available, otherwise fetch
    summary_data, summary_err = (header_summary, header_err) if header_summary is not None else fetch_api("/analytics/summary")

    # Section: 4 Metric Cards (Checked safely without crashing)
    if summary_err or not summary_data or not isinstance(summary_data, dict):
        st.error(f"Unable to load portfolio summary metrics: {summary_err or 'Empty response from backend'}")
    else:
        m1, m2, m3, m4 = st.columns(4)

        with m1:
            total_carts_val = summary_data.get("total_carts", 0)
            st.markdown(
                f"""
                <div class="cs-metric-card">
                    <div class="cs-metric-label">Total Abandoned Carts</div>
                    <div class="cs-metric-val">{total_carts_val:,}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with m2:
            val_at_risk = summary_data.get("total_value_at_risk", 0.0)
            st.markdown(
                f"""
                <div class="cs-metric-card">
                    <div class="cs-metric-label">Cart Value at Risk</div>
                    <div class="cs-metric-val">₹{val_at_risk:,.2f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with m3:
            # Styled as hero — largest, accent-colored
            val_rec = summary_data.get("total_value_recovered", 0.0)
            st.markdown(
                f"""
                <div class="cs-hero-card">
                    <div class="cs-metric-label" style="color: {ACCENT_COLOR};">Total Value Recovered</div>
                    <div class="cs-hero-val">₹{val_rec:,.2f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with m4:
            rec_rate = summary_data.get("recovery_rate_percent", 0.0)
            st.markdown(
                f"""
                <div class="cs-metric-card">
                    <div class="cs-metric-label">Recovery Rate</div>
                    <div class="cs-metric-val">{rec_rate:.2f}%</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    # 3 Plotly charts with section-level error isolation
    chart_col1, chart_col2 = st.columns(2)

    # Chart 1: Bar chart of segment_breakdown (count per segment)
    with chart_col1:
        st.markdown("<div style='font-size: 15px; font-weight: 600; margin-bottom: 12px;'>Carts by Customer Segment</div>", unsafe_allow_html=True)
        
        if not summary_data or not isinstance(summary_data, dict) or "segment_breakdown" not in summary_data:
            st.error("Customer segment breakdown data is currently unavailable.")
        else:
            seg_data = summary_data.get("segment_breakdown", {})
            if not isinstance(seg_data, dict) or len(seg_data) == 0:
                st.info("No segment breakdown records found.")
            else:
                seg_names = list(seg_data.keys())
                seg_counts = [seg_data[s].get("count", 0) if isinstance(seg_data[s], dict) else 0 for s in seg_names]

                fig_seg = go.Figure()
                fig_seg.add_trace(go.Bar(
                    x=seg_names,
                    y=seg_counts,
                    marker_color=ACCENT_COLOR,
                    hovertemplate="<b>%{x}</b><br>Carts: %{y}<extra></extra>"
                ))
                fig_seg.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=30, l=40, r=20),
                    font=dict(family="Inter", size=12, color="#667085"),
                    xaxis=dict(showgrid=False, zeroline=False),
                    yaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(102, 112, 133, 0.15)", zeroline=False),
                    height=280
                )
                st.plotly_chart(fig_seg, use_container_width=True, config={"displayModeBar": False})

    # Chart 2: Bar chart of escalation_stage_breakdown
    with chart_col2:
        st.markdown("<div style='font-size: 15px; font-weight: 600; margin-bottom: 12px;'>Interventions by Escalation Stage</div>", unsafe_allow_html=True)
        
        if not summary_data or not isinstance(summary_data, dict) or "escalation_stage_breakdown" not in summary_data:
            st.error("Escalation stage breakdown data is currently unavailable.")
        else:
            stage_data = summary_data.get("escalation_stage_breakdown", {})
            if not isinstance(stage_data, dict) or len(stage_data) == 0:
                st.info("No escalation stage breakdown records found.")
            else:
                stage_names = list(stage_data.keys())
                stage_labels = [s.split(":")[0] if ":" in s else s for s in stage_names]
                stage_counts = [stage_data.get(s, 0) for s in stage_names]

                fig_stage = go.Figure()
                fig_stage.add_trace(go.Bar(
                    x=stage_labels,
                    y=stage_counts,
                    marker_color=ACCENT_COLOR,
                    hovertemplate="<b>%{x}</b><br>Interventions: %{y}<extra></extra>"
                ))
                fig_stage.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=30, l=40, r=20),
                    font=dict(family="Inter", size=12, color="#667085"),
                    xaxis=dict(showgrid=False, zeroline=False),
                    yaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(102, 112, 133, 0.15)", zeroline=False),
                    height=280
                )
                st.plotly_chart(fig_stage, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    # Chart 3: Donut chart of stopping_reason_breakdown / Agent Stopping Rules
    st.markdown("<div style='font-size: 15px; font-weight: 600; margin-bottom: 12px;'>Agent Stopping Rules Distribution</div>", unsafe_allow_html=True)
    
    # 1. Read stopping_reason_breakdown with fallback to alternative keys
    raw_stop_data = None
    if isinstance(summary_data, dict):
        for key_candidate in [
            "stopping_reason_breakdown",
            "stopping_reasons",
            "stopping_rules",
            "stopping_rule_breakdown",
            "agent_stopping_rules"
        ]:
            if key_candidate in summary_data and summary_data[key_candidate] is not None:
                raw_stop_data = summary_data[key_candidate]
                break

    # Debug print to console as requested
    safe_log(f"[DEBUG] Raw stopping_reason_breakdown data passed to donut chart: {raw_stop_data}")

    def _normalize_stop_category(name: Any) -> str:
        s = str(name).strip()
        s_lower = s.lower()
        if "low recovery score" in s_lower:
            return "Low Recovery Score (< 0.15)"
        elif "low cart value" in s_lower:
            return "Low Cart Value (< ₹300) & Low Score"
        elif "max 3 attempts" in s_lower or "max attempts" in s_lower:
            return "Max Attempts Exceeded"
        elif "already recovered" in s_lower:
            return "Already Recovered"
        elif "(" in s:
            return s.split("(")[0].strip()
        return s

    # 2. Robust normalization of category keys and counts across multiple data shapes
    normalized_stop_data: Dict[str, int] = {}
    if isinstance(raw_stop_data, dict):
        # Handle case where dict has separate "labels"/"reasons" and "values"/"counts" keys
        if ("labels" in raw_stop_data or "reasons" in raw_stop_data) and ("values" in raw_stop_data or "counts" in raw_stop_data):
            labels_list = raw_stop_data.get("labels") or raw_stop_data.get("reasons") or []
            values_list = raw_stop_data.get("values") or raw_stop_data.get("counts") or []
            for lab, val in zip(labels_list, values_list):
                cat = _normalize_stop_category(lab)
                cnt = 0
                if val is not None:
                    try:
                        cnt = int(val)
                    except (ValueError, TypeError):
                        cnt = 0
                if cnt > 0:
                    normalized_stop_data[cat] = normalized_stop_data.get(cat, 0) + cnt
        else:
            for k, v in raw_stop_data.items():
                cat = _normalize_stop_category(k)
                cnt = 0
                if isinstance(v, dict):
                    raw_val = v.get("count", v.get("value", v.get("total", 0)))
                else:
                    raw_val = v
                if raw_val is not None:
                    try:
                        cnt = int(raw_val)
                    except (ValueError, TypeError):
                        cnt = 0
                if cnt > 0:
                    normalized_stop_data[cat] = normalized_stop_data.get(cat, 0) + cnt
    elif isinstance(raw_stop_data, list):
        for item in raw_stop_data:
            if isinstance(item, dict):
                label = (
                    item.get("reason")
                    or item.get("category")
                    or item.get("label")
                    or item.get("name")
                    or item.get("stopping_reason")
                    or "Other"
                )
                cat = _normalize_stop_category(label)
                raw_val = item.get("count", item.get("value", item.get("total", 1)))
                cnt = 1
                if raw_val is not None:
                    try:
                        cnt = int(raw_val)
                    except (ValueError, TypeError):
                        cnt = 1
                if cnt > 0:
                    normalized_stop_data[cat] = normalized_stop_data.get(cat, 0) + cnt
            elif isinstance(item, str):
                cat = _normalize_stop_category(item)
                normalized_stop_data[cat] = normalized_stop_data.get(cat, 0) + 1

    safe_log(f"[DEBUG] Normalized stopping reason categories with counts: {normalized_stop_data}")

    if not normalized_stop_data:
        st.info("No stopping rule triggers recorded.")
    else:
        stop_reasons = list(normalized_stop_data.keys())
        stop_counts = [normalized_stop_data[r] for r in stop_reasons]
        total_stopped = sum(stop_counts)

        stop_palette = [
            ACCENT_COLOR, "#875BF7", "#9E77ED", "#B39BF7",
            "#D6BBFB", "#7F56D9", "#667085", "#98A2B3"
        ]
        slice_colors = [stop_palette[i % len(stop_palette)] for i in range(len(stop_reasons))]
        legend_labels = [f"{r} ({cnt})" for r, cnt in zip(stop_reasons, stop_counts)]

        fig_donut = go.Figure()
        fig_donut.add_trace(go.Pie(
            labels=legend_labels,
            values=stop_counts,
            hole=0.6,
            marker=dict(colors=slice_colors),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Proportion: %{percent}<extra></extra>"
        ))
        fig_donut.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=20, l=20, r=20),
            font=dict(family="Inter", size=12, color="#667085"),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.25,
                xanchor="center",
                x=0.5,
                font=dict(size=11)
            ),
            height=330,
            annotations=[
                dict(
                    text=f"<b>{total_stopped}</b><br><span style='font-size:10px; color:#667085;'>STOPPED</span>",
                    x=0.5, y=0.5,
                    font_size=15,
                    showarrow=False
                )
            ]
        )
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})

        # Category pill summary showing stopping reason categories with counts
        pills_html = "".join([
            f'<div style="display: inline-flex; align-items: center; background: rgba(105, 56, 239, 0.08); border: 1px solid rgba(105, 56, 239, 0.2); border-radius: 16px; padding: 4px 12px; margin: 4px 6px 4px 0; font-size: 12px; color: var(--text-color);">'
            f'<span style="font-weight: 500;">{reason}</span>'
            f'<span style="margin-left: 8px; background: {ACCENT_COLOR}; color: #ffffff; font-weight: 700; border-radius: 10px; padding: 1px 7px; font-size: 11px;">{count}</span>'
            f'</div>'
            for reason, count in normalized_stop_data.items()
        ])
        st.markdown(f"<div style='margin-top: 10px;'>{pills_html}</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# PAGE 2: CARTS EXPLORER
# -----------------------------------------------------------------------------
elif st.session_state.page == "Carts Explorer":
    st.markdown(
        """
        <div style="margin-bottom: 22px;">
            <div style="font-size: 22px; font-weight: 700; color: var(--text-color); margin-bottom: 4px;">Carts Explorer</div>
            <div style="font-size: 14px; color: var(--text-color); opacity: 0.7;">Filter abandoned checkouts, examine recovery viability, and trigger on-demand interventions.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3 filter dropdowns calling GET /carts with matching query params
    f_col1, f_col2, f_col3 = st.columns(3)

    segment_options = ["All Segments", "High-Value High-Intent", "Payment-Failed-Technical", "Price-Sensitive", "Low-Intent"]
    status_options = ["All Statuses", "Recovered", "Unrecovered"]
    failure_options = [
        "All Failure Reasons",
        "user exited at payment",
        "OTP failed",
        "payment declined",
        "bank timeout",
        "insufficient balance"
    ]

    with f_col1:
        sel_segment = st.selectbox("Customer Segment", segment_options)
    with f_col2:
        sel_status = st.selectbox("Recovery Status", status_options)
    with f_col3:
        sel_failure = st.selectbox("Failure Reason", failure_options)

    # Prepare query params
    api_params = {}
    if sel_segment != "All Segments":
        api_params["segment"] = sel_segment
    if sel_status == "Recovered":
        api_params["recovered"] = True
    elif sel_status == "Unrecovered":
        api_params["recovered"] = False
    if sel_failure != "All Failure Reasons":
        api_params["failure_reason"] = sel_failure

    carts_data, carts_err = fetch_api("/carts", params=api_params)

    # Safe handling: if carts request fails, display st.error in this section without crashing
    if carts_err or carts_data is None:
        st.error(f"Failed to fetch carts: {carts_err or 'Empty response from backend'}")
    elif not isinstance(carts_data, list):
        st.error("Unexpected response format from backend for carts list.")
    elif len(carts_data) == 0:
        st.markdown(
            """
            <div class="cs-card" style="text-align: center; padding: 40px 20px;">
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 6px;">No carts found</div>
                <div style="font-size: 13px; opacity: 0.7;">Try adjusting the filter criteria above.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        total_matched = len(carts_data)
        page_size = 15
        total_pages = max(1, (total_matched - 1) // page_size + 1)
        
        # Ensure page num is within bounds
        if st.session_state.explorer_page_num > total_pages:
            st.session_state.explorer_page_num = 1
            
        current_page = st.session_state.explorer_page_num
        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_matched)
        page_carts = carts_data[start_idx:end_idx]

        # Top summary line & pagination controls
        count_col, page_col = st.columns([3, 2])
        with count_col:
            st.markdown(
                f"<div style='font-size: 13px; color: var(--text-color); opacity: 0.8; padding-top: 6px;'>Showing {start_idx + 1}–{end_idx} of {total_matched} carts</div>",
                unsafe_allow_html=True
            )
        with page_col:
            p_prev, p_info, p_next = st.columns([1, 2, 1])
            with p_prev:
                if st.button("Previous", key="btn_prev_page", disabled=(current_page <= 1), use_container_width=True):
                    st.session_state.explorer_page_num -= 1
                    st.rerun()
            with p_info:
                st.markdown(
                    f"<div style='text-align: center; font-size: 13px; padding-top: 6px; color: var(--text-color); font-weight: 500;'>Page {current_page} of {total_pages}</div>",
                    unsafe_allow_html=True
                )
            with p_next:
                if st.button("Next", key="btn_next_page", disabled=(current_page >= total_pages), use_container_width=True):
                    st.session_state.explorer_page_num += 1
                    st.rerun()

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        # Table Header
        h_col1, h_col2, h_col3, h_col4, h_col5, h_col6, h_col7 = st.columns([2.2, 1.2, 1.8, 1.6, 1.2, 1.8, 1.1])
        with h_col1:
            st.markdown("<div class='cs-table-header'>Customer & ID</div>", unsafe_allow_html=True)
        with h_col2:
            st.markdown("<div class='cs-table-header' style='text-align: right;'>Value</div>", unsafe_allow_html=True)
        with h_col3:
            st.markdown("<div class='cs-table-header'>Segment</div>", unsafe_allow_html=True)
        with h_col4:
            st.markdown("<div class='cs-table-header'>Recovery Score</div>", unsafe_allow_html=True)
        with h_col5:
            st.markdown("<div class='cs-table-header'>Status</div>", unsafe_allow_html=True)
        with h_col6:
            st.markdown("<div class='cs-table-header'>Failure Reason</div>", unsafe_allow_html=True)
        with h_col7:
            st.markdown("<div class='cs-table-header' style='text-align: right;'>Action</div>", unsafe_allow_html=True)

        # Render Rows
        for cart in page_carts:
            if not isinstance(cart, dict):
                continue
            cid = cart.get("cart_id", "")
            short_id = f"{cid[:8]}...{cid[-4:]}" if len(cid) >= 12 else cid
            cname = cart.get("customer_name", "Unknown")
            cval_num = cart.get("cart_value", 0.0)
            cval = f"₹{cval_num:,.2f}"
            seg = cart.get("segment") or "N/A"
            rscore = cart.get("recovery_score") if cart.get("recovery_score") is not None else 0.0
            rscore_pct = int(min(max(rscore * 100, 0), 100))
            is_rec = bool(cart.get("recovered", False))
            freason = cart.get("failure_reason") or "N/A"

            r_col1, r_col2, r_col3, r_col4, r_col5, r_col6, r_col7 = st.columns([2.2, 1.2, 1.8, 1.6, 1.2, 1.8, 1.1])

            with r_col1:
                st.markdown(
                    f"""
                    <div style="padding: 6px 0;">
                        <div style="font-size: 14px; font-weight: 600; color: var(--text-color); line-height: 1.2;">{cname}</div>
                        <div style="font-family: monospace; font-size: 11px; opacity: 0.6; color: var(--text-color); margin-top: 2px;">{short_id}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with r_col2:
                st.markdown(
                    f"""
                    <div style="padding: 10px 0; text-align: right; font-size: 14px; font-weight: 600; color: var(--text-color);">
                        {cval}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with r_col3:
                st.markdown(
                    f"""
                    <div style="padding: 10px 0; font-size: 13px; color: var(--text-color);">
                        {seg}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with r_col4:
                st.markdown(
                    f"""
                    <div style="padding: 8px 0;">
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; font-weight: 600; color: var(--text-color); margin-bottom: 4px;">
                            <span>{rscore:.2f}</span>
                        </div>
                        <div class="cs-progress-track">
                            <div class="cs-progress-fill" style="width: {rscore_pct}%;"></div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with r_col5:
                status_html = (
                    f'<span class="cs-pill-recovered">Recovered</span>'
                    if is_rec
                    else f'<span class="cs-pill-unrecovered">Unrecovered</span>'
                )
                st.markdown(f"<div style='padding: 10px 0;'>{status_html}</div>", unsafe_allow_html=True)

            with r_col6:
                st.markdown(
                    f"""
                    <div style="padding: 10px 0; font-size: 13px; color: var(--text-color); opacity: 0.85;">
                        {freason}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with r_col7:
                # "Recover" button per row calling POST /carts/{cart_id}/recover
                recover_clicked = st.button("Recover", key=f"btn_rec_{cid}", use_container_width=True)
                if recover_clicked:
                    with st.spinner(f"Recovering cart {short_id}..."):
                        rec_res, rec_err = fetch_api(f"/carts/{cid}/recover", method="POST")
                        if rec_err or rec_res is None or not isinstance(rec_res, dict):
                            st.session_state.flash_message = {
                                "type": "error",
                                "text": f"Recovery request failed for {cname}: {rec_err or 'Empty response from backend'}"
                            }
                        else:
                            status = rec_res.get("status")
                            stopped = bool(rec_res.get("stopping_rule_triggered", False))
                            stop_reason = rec_res.get("stopping_reason")
                            cart_recovered = bool(rec_res.get("cart_recovered", False))
                            stage = rec_res.get("escalation_stage", "Escalation")
                            outcome = rec_res.get("simulated_outcome", "completed")

                            if stopped:
                                st.session_state.flash_message = {
                                    "type": "warning",
                                    "text": f"Agent Stopping Rule Triggered for {cname}: {stop_reason}"
                                }
                            elif cart_recovered:
                                st.session_state.flash_message = {
                                    "type": "success",
                                    "text": f"Cart for {cname} successfully recovered at {stage} (Outcome: {outcome})"
                                }
                            else:
                                st.session_state.flash_message = {
                                    "type": "info",
                                    "text": f"Attempt for {cname} executed at {stage}. Outcome: {outcome}."
                                }
                    st.rerun()

            st.markdown("<div style='border-bottom: 1px solid rgba(102, 112, 133, 0.1); margin: 2px 0;'></div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# PAGE 3: AUDIT TRAIL
# -----------------------------------------------------------------------------
elif st.session_state.page == "Audit Trail":
    st.markdown(
        """
        <div style="margin-bottom: 22px;">
            <div style="font-size: 22px; font-weight: 700; color: var(--text-color); margin-bottom: 4px;">Agent Audit Trail</div>
            <div style="font-size: 14px; color: var(--text-color); opacity: 0.7;">Inspect agent reasoning, escalation attempts, message drafts, and stopping decisions per cart.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    all_carts, all_carts_err = fetch_api("/carts")

    # Safe handling: dropdown population
    if all_carts_err or all_carts is None or not isinstance(all_carts, list):
        st.error(f"Failed to load carts list for audit trail: {all_carts_err or 'Empty response from backend'}")
    elif len(all_carts) == 0:
        st.info("No carts available for audit inspection.")
    else:
        # Build dropdown options safely
        cart_options = {}
        for c in all_carts:
            if isinstance(c, dict) and "cart_id" in c:
                cid = c["cart_id"]
                c_name = c.get("customer_name", "Unknown")
                c_val = c.get("cart_value", 0.0)
                label = f"{c_name} ({cid[:8]}...) - ₹{c_val:,.2f}"
                cart_options[cid] = label

        if not cart_options:
            st.info("No valid carts available in database.")
        else:
            # Default selection
            default_index = 0
            if st.session_state.selected_cart_id and st.session_state.selected_cart_id in cart_options:
                default_index = list(cart_options.keys()).index(st.session_state.selected_cart_id)

            selected_id = st.selectbox(
                "Select Cart to Inspect",
                options=list(cart_options.keys()),
                index=default_index,
                format_func=lambda x: cart_options[x],
                key="audit_cart_select"
            )
            st.session_state.selected_cart_id = selected_id

            # Fetch detail for selected cart
            detail_data, detail_err = fetch_api(f"/carts/{selected_id}")

            # Section error handling: Detail retrieval
            if detail_err or detail_data is None or not isinstance(detail_data, dict):
                st.error(f"Failed to fetch cart detail for {selected_id}: {detail_err or 'Empty response from backend'}")
            elif "cart" not in detail_data or not isinstance(detail_data.get("cart"), dict):
                st.error(f"Cart details missing from backend response for cart {selected_id}.")
            else:
                cart_info = detail_data["cart"]
                logs = detail_data.get("logs", [])

                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

                # Cart Info Card (All accesses using .get() with fallback defaults)
                is_recovered = bool(cart_info.get("recovered", False))
                rec_pill = (
                    f'<span class="cs-pill-recovered">Recovered</span>'
                    if is_recovered
                    else f'<span class="cs-pill-unrecovered">Unrecovered</span>'
                )

                items_list = cart_info.get("items", [])
                items_str = ", ".join(items_list) if isinstance(items_list, list) else str(items_list)
                c_val = cart_info.get("cart_value", 0.0)
                r_score = cart_info.get("recovery_score", 0.0)
                p_score = cart_info.get("priority_score", 0.0)

                st.markdown(
                    f"""
                    <div class="cs-card">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
                            <div>
                                <div style="font-size: 18px; font-weight: 700; color: var(--text-color);">{cart_info.get('customer_name', 'Unknown')}</div>
                                <div style="font-family: monospace; font-size: 12px; opacity: 0.6; color: var(--text-color); margin-top: 2px;">ID: {cart_info.get('cart_id', selected_id)}</div>
                            </div>
                            <div>
                                {rec_pill}
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; font-size: 13px;">
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Cart Value</div>
                                <div style="font-weight: 600; font-size: 15px; color: var(--text-color);">₹{c_val:,.2f}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Segment</div>
                                <div style="font-weight: 500; color: var(--text-color);">{cart_info.get('segment') or 'N/A'}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Payment Method</div>
                                <div style="font-weight: 500; color: var(--text-color);">{cart_info.get('payment_method_attempted') or 'N/A'}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Failure Reason</div>
                                <div style="font-weight: 500; color: var(--text-color);">{cart_info.get('failure_reason') or 'N/A'}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Recovery Score</div>
                                <div style="font-weight: 600; color: {ACCENT_COLOR};">{r_score:.4f}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Priority Score</div>
                                <div style="font-weight: 500; color: var(--text-color);">{p_score:.4f}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Customer Type</div>
                                <div style="font-weight: 500; color: var(--text-color);">{cart_info.get('customer_type', 'N/A')}</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; opacity: 0.6; margin-bottom: 3px;">Abandoned At</div>
                                <div style="font-weight: 500; color: var(--text-color);">{cart_info.get('abandoned_at', 'N/A')}</div>
                            </div>
                        </div>
                        <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(102, 112, 133, 0.15); font-size: 13px;">
                            <span style="font-weight: 600; opacity: 0.7;">Cart Items: </span>
                            <span style="opacity: 0.9;">{items_str}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.markdown("<div style='font-size: 16px; font-weight: 700; margin: 24px 0 14px 0; color: var(--text-color);'>Recovery Log History</div>", unsafe_allow_html=True)

                # Section error handling: Logs list
                if not isinstance(logs, list):
                    st.error("Invalid recovery log history format received from backend.")
                elif not logs:
                    st.markdown(
                        """
                        <div class="cs-card" style="text-align: center; padding: 28px 16px;">
                            <div style="font-size: 14px; opacity: 0.7;">No recovery logs recorded for this cart yet.</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    for idx, log in enumerate(logs, start=1):
                        if not isinstance(log, dict):
                            continue
                        stage_label = log.get("escalation_stage", "N/A")
                        ts = log.get("timestamp", "N/A")
                        channel = log.get("channel", "N/A")
                        diag = log.get("root_cause_diagnosis", "N/A")
                        reasoning = log.get("agent_reasoning", "N/A")
                        draft = log.get("message_draft", "N/A")
                        source = log.get("message_source", "gemini")
                        sim_outcome = log.get("simulated_outcome", "stopped")
                        stopped = bool(log.get("stopping_rule_triggered", False))
                        stop_reason = log.get("stopping_reason")

                        # Simulated outcome colored pill (green if recovered, red if attempt_failed, gray if stopped)
                        if sim_outcome == "recovered":
                            outcome_pill = '<span class="cs-pill-recovered">recovered</span>'
                        elif sim_outcome == "attempt_failed":
                            outcome_pill = '<span class="cs-pill-failed">attempt failed</span>'
                        else:
                            outcome_pill = '<span class="cs-pill-stopped">stopped</span>'

                        # Stopping rule vs Message draft display
                        if stopped:
                            body_content = f"""
                            <div style="background-color: rgba(102, 112, 133, 0.08); border-left: 4px solid {COLOR_UNRECOVERED}; padding: 12px 16px; border-radius: 4px; margin-top: 14px;">
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-color); opacity: 0.7;">Stopping Rule Triggered</div>
                                <div style="font-size: 13px; font-weight: 600; margin-top: 4px; color: var(--text-color); line-height: 1.4;">{stop_reason}</div>
                            </div>
                            """
                        else:
                            body_content = f"""
                            <div style="background-color: rgba(105, 56, 239, 0.06); border-left: 4px solid {ACCENT_COLOR}; padding: 12px 16px; border-radius: 4px; margin-top: 14px;">
                                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: {ACCENT_COLOR};">Message Draft (Source: {source})</div>
                                <div style="font-size: 13px; margin-top: 5px; color: var(--text-color); line-height: 1.5;">{draft}</div>
                            </div>
                            """

                        st.markdown(
                            f"""
                            <div class="cs-card">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                                    <div style="display: flex; align-items: center; gap: 10px;">
                                        <span style="font-size: 14px; font-weight: 700; color: var(--text-color);">{stage_label}</span>
                                        <span style="font-size: 12px; opacity: 0.6; color: var(--text-color);">Attempt #{log.get('attempt_number', idx)}</span>
                                    </div>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <span style="font-size: 12px; opacity: 0.6; color: var(--text-color);">{ts}</span>
                                        <span style="font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 4px; background: rgba(102, 112, 133, 0.1); color: var(--text-color);">Channel: {channel}</span>
                                        {outcome_pill}
                                    </div>
                                </div>
                                <div style="margin-top: 10px; font-size: 13px; line-height: 1.5;">
                                    <div style="margin-bottom: 8px;">
                                        <span style="font-weight: 600; opacity: 0.7;">Root Cause Diagnosis: </span>
                                        <span style="color: var(--text-color);">{diag}</span>
                                    </div>
                                    <div>
                                        <span style="font-weight: 600; opacity: 0.7;">Agent Reasoning: </span>
                                        <span style="color: var(--text-color);">{reasoning}</span>
                                    </div>
                                </div>
                                {body_content}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
