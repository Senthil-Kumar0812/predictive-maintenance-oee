"""
Turbine Fleet Command Center
Predictive Maintenance & OEE — Snowflake Hackathon 2026
"""

import json
import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(
    page_title="Turbine Fleet Command Center",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATABASE = "PDM_OEE_DB"
SCHEMA = "GOLD"
AGENT_NAME = "PDM_COMMAND_CENTER_AGENT"
AGENT_FQN = f"{DATABASE}.{SCHEMA}.{AGENT_NAME}"
WAREHOUSE = "COMPUTE_WH"

# ── Connection (SiS container runtime only) ──
@st.cache_resource
def get_session():
    from snowflake.snowpark.context import get_active_session
    return get_active_session()

def run_query(sql):
    return get_session().sql(sql).to_pandas()

def call_procedure(proc_call):
    return get_session().sql(proc_call).collect()[0][0]

# ── Agent via DATA_AGENT_RUN ──
def call_agent(query):
    payload = json.dumps({
        "messages": [{"role": "user", "content": [{"type": "text", "text": query}]}]
    })
    # Use $$ dollar-quoting to avoid all SQL string escaping issues
    sql = f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('{AGENT_FQN}', $${payload}$$)"
    row = get_session().sql(sql).collect()
    raw = row[0][0]
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {"error": str(raw)[:500]}


def parse_agent_response(data):
    if "error" in data:
        return {"text": data["error"], "tools": [], "thinking": [], "suggested": []}

    content = data.get("content", [])
    tools, texts, thinking, suggested = [], [], [], []

    for item in content:
        t = item.get("type")
        if t == "tool_use":
            tools.append(item.get("tool_use", {}).get("name", "?"))
        elif t == "text":
            texts.append(item.get("text", ""))
        elif t == "thinking":
            thinking.append(item.get("thinking", {}).get("text", ""))
        elif t == "suggested_queries":
            for sq in item.get("suggested_queries", []):
                suggested.append(sq.get("query", ""))

    return {
        "text": "\n".join(texts),
        "tools": list(dict.fromkeys(tools)),
        "thinking": thinking,
        "suggested": suggested,
    }


# ── Direct procedure calls (bypasses DATA_AGENT_RUN UDF limitation) ──
def execute_create_work_order(asset_id, confidence, description, override=False):
    override_str = "TRUE" if override else "FALSE"
    escaped = description.replace("'", "''")
    sql = f"CALL PDM_OEE_DB.GOLD.CREATE_WORK_ORDER('{asset_id}', {confidence}, '{escaped}', {override_str})"
    return call_procedure(sql)

def execute_notify_critical_alert(asset_id, confidence, message):
    escaped = message.replace("'", "''")
    sql = f"CALL PDM_OEE_DB.GOLD.NOTIFY_CRITICAL_ALERT('{asset_id}', {confidence}, '{escaped}')"
    return call_procedure(sql)

def extract_asset_from_analysis(text):
    import re
    asset_match = re.search(r'(WF\d{2}-T\d{2}-[A-Z]{3})', text)
    # Match "confidence" followed by optional filler words (is, of, :, =) then a number
    conf_match = re.search(r'confidence[\s:=*]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?', text.lower())
    asset_id = asset_match.group(1) if asset_match else None
    confidence = None
    if conf_match:
        val = float(conf_match.group(1))
        # Normalize: if > 1, treat as percentage
        confidence = val / 100.0 if val > 1 else val
    return asset_id, confidence


# ── Session state ──
for key, default in [
    ("chat_history", []),
    ("pending_action", None),
    ("processing", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Sidebar ──
with st.sidebar:
    st.title("Command Center")
    st.divider()
    # Single source of truth: the widget key IS the state variable.
    # No separate session_state copy — eliminates dual-state desync.
    judge = st.toggle("Judge Exploration Mode", key="judge_mode")
    if judge:
        st.warning("All agent actions require manual confirmation.")
    st.divider()

    with st.expander("Notification Settings"):
        try:
            notif_df = run_query("SELECT CONFIG_ID, REPORT_TYPE, RECIPIENT, THRESHOLD FROM PDM_OEE_DB.GOLD.NOTIFICATION_CONFIG ORDER BY REPORT_TYPE")
            st.dataframe(notif_df, hide_index=True)
        except Exception as e:
            st.error(f"Could not load config: {e}")

    st.caption("PDM OEE Command Center v2.0")

# ── Judge mode banner ──
if st.session_state.judge_mode:
    st.markdown(
        '<div style="background:#c0392b;color:white;padding:8px 16px;border-radius:4px;'
        'text-align:center;font-weight:bold;margin-bottom:16px;">'
        'JUDGE EXPLORATION MODE — All agent actions require confirmation</div>',
        unsafe_allow_html=True,
    )

# Resume warehouse silently
try:
    run_query("ALTER WAREHOUSE COMPUTE_WH RESUME IF SUSPENDED")
except Exception:
    pass

# ── Tabs ──
tab1, tab2, tab3 = st.tabs(["Alert Triage", "Chat / RCA", "OEE & Trends"])


# ========================================
# TAB 1 — Alert Triage Grid
# ========================================
with tab1:
    st.subheader("Alert Triage Grid")

    @st.cache_data(ttl=60)
    def load_alerts():
        return run_query("""
            SELECT a.ASSET_ID, m.SUBSYSTEM, m.WIND_FARM,
                   ROUND(a.CONFIDENCE, 3) AS CONFIDENCE,
                   a.PRIORITY, a.DRIVING_SIGNAL, a.STATUS
            FROM PDM_OEE_DB.GOLD.ALERT_QUEUE a
            JOIN PDM_OEE_DB.RAW.ASSET_MASTER m ON a.ASSET_ID = m.ASSET_ID
            ORDER BY a.PRIORITY DESC
        """)

    alerts_df = load_alerts()

    if alerts_df.empty:
        st.info("No active alerts.")
    else:
        auto_count = len(alerts_df[alerts_df["STATUS"] == "AUTO_ELIGIBLE"])
        review_count = len(alerts_df[alerts_df["STATUS"] == "NEEDS_REVIEW"])
        logged_count = len(alerts_df[alerts_df["STATUS"] == "LOGGED_ONLY"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Alerts", len(alerts_df))
        c2.metric("Auto-Eligible", auto_count)
        c3.metric("Needs Review", review_count)
        c4.metric("Logged Only", logged_count)

        def color_status(val):
            colors = {
                "AUTO_ELIGIBLE": "background-color: #e74c3c; color: white; font-weight: bold;",
                "NEEDS_REVIEW": "background-color: #f39c12; color: black; font-weight: bold;",
                "LOGGED_ONLY": "background-color: #95a5a6; color: white;",
            }
            return colors.get(val, "")

        styled = alerts_df.style.map(color_status, subset=["STATUS"])
        event = st.dataframe(
            styled, hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key="alert_grid",
        )

        selected_rows = event.selection.rows if event.selection else []
        if selected_rows:
            idx = selected_rows[0]
            row = alerts_df.iloc[idx]
            asset_id = row["ASSET_ID"]
            signal = row["DRIVING_SIGNAL"]
            signal_col = "VIBRATION_MM_S" if signal == "VIBRATION" else "TEMP_C"
            signal_label = "Vibration (mm/s)" if signal == "VIBRATION" else "Temperature (C)"

            st.markdown(f"**{asset_id}** — {signal_label} over last 72 hours")

            @st.cache_data(ttl=120)
            def load_sparkline(aid, col):
                return run_query(f"""
                    SELECT TS, {col} AS VALUE
                    FROM PDM_OEE_DB.BRONZE.BRONZE_SENSOR_STREAM
                    WHERE ASSET_ID = '{aid}'
                      AND TS >= DATEADD('hour', -72, (
                          SELECT MAX(TS) FROM PDM_OEE_DB.BRONZE.BRONZE_SENSOR_STREAM
                          WHERE ASSET_ID = '{aid}'))
                    ORDER BY TS
                """)

            spark_df = load_sparkline(asset_id, signal_col)
            if not spark_df.empty:
                chart = alt.Chart(spark_df).mark_line(strokeWidth=1.5).encode(
                    x=alt.X("TS:T", title="Time"),
                    y=alt.Y("VALUE:Q", title=signal_label, scale=alt.Scale(zero=False)),
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.caption("No sensor data available for this asset.")


# ========================================
# TAB 2 — Chat / RCA Panel
# ========================================
with tab2:
    st.subheader("Ask the Command Center Agent")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools"):
                st.caption(f"Tools used: {', '.join(msg['tools'])}")
            if msg.get("suggested"):
                for sq in msg["suggested"]:
                    st.caption(f"Suggested: {sq}")

    # Handle pending action confirmation (Judge Mode)
    if st.session_state.pending_action:
        pa = st.session_state.pending_action
        st.divider()
        st.error("ACTION CONFIRMATION REQUIRED", icon="🛑")
        with st.container(border=True):
            st.markdown(f"**The agent recommends an action based on this analysis:**")
            st.markdown(pa["analysis_text"][:800])
            if pa.get("analysis_tools"):
                st.caption(f"Tools used: {', '.join(pa['analysis_tools'])}")
            st.markdown("---")
            col_yes, col_no = st.columns(2)
            if col_yes.button("Confirm — Execute Action", type="primary", key="confirm_action"):
                analysis_text = pa["analysis_text"]
                asset_id, confidence = extract_asset_from_analysis(analysis_text)
                results = []

                if asset_id is not None and confidence is not None:
                    with st.spinner(f"Creating work order for {asset_id}..."):
                        wo_result = execute_create_work_order(
                            asset_id, confidence,
                            f"AGENT-RCA-{asset_id}",
                            override=False,
                        )
                        results.append(f"CreateWorkOrder: {wo_result}")

                    if confidence >= 0.85:
                        with st.spinner(f"Sending critical notification for {asset_id}..."):
                            notif_result = execute_notify_critical_alert(
                                asset_id, confidence,
                                f"Critical anomaly on {asset_id}, confidence={confidence}. Work order created.",
                            )
                            results.append(f"NotifyCriticalAlert: {notif_result}")

                    action_summary = "\n".join(f"- {r}" for r in results)
                else:
                    action_summary = (
                        f"Could not extract asset_id or confidence from the agent's analysis. "
                        f"Please ask the agent a more specific question about a single asset."
                    )

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": f"**Action executed (direct procedure call):**\n\n{action_summary}",
                    "tools": pa.get("analysis_tools", []) + ["CreateWorkOrder"],
                })
                st.session_state.pending_action = None
                st.rerun()

            if col_no.button("Deny — Skip Action", key="deny_action"):
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": f"Action denied by user.\n\nOriginal analysis:\n{pa['analysis_text']}",
                    "tools": pa.get("analysis_tools", []),
                })
                st.session_state.pending_action = None
                st.rerun()
        st.stop()  # Block further rendering — force user to Confirm or Deny before chatting

    prompt = st.chat_input("Ask about fleet health, alerts, maintenance, OEE...",
                            disabled=st.session_state.processing)
    if prompt:
        # Guard: prevent duplicate submissions while agent is processing
        if st.session_state.processing:
            st.warning("A request is already in progress.")
            st.stop()
        st.session_state.processing = True
        st.session_state.chat_history.append({"role": "user", "content": prompt})

        try:
            # Common: call agent
            is_judge = st.session_state.judge_mode
            spinner_msg = "Analyzing (Judge Mode)..." if is_judge else "Thinking..."
            with st.spinner(spinner_msg):
                raw = call_agent(prompt)
                parsed = parse_agent_response(raw)

            # Common: detect action intent
            action_signals = [
                "auto-eligible", "auto_eligible", "create a work order",
                "work order", "recommend creating", "should be created",
                "i'll create", "i will create", "proceed with",
                "notify", "send a critical", "alert notification",
                "action is warranted", "auto-action", "guardrail",
            ]
            agent_wants_action = any(s in parsed["text"].lower() for s in action_signals)

            if is_judge:
                # Judge ON: require human confirmation before any action
                if agent_wants_action:
                    st.session_state.pending_action = {
                        "query": prompt,
                        "analysis_text": parsed["text"],
                        "analysis_tools": parsed["tools"],
                    }
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": parsed["text"] + "\n\n*Awaiting your confirmation to execute the action.*",
                        "tools": parsed["tools"],
                    })
                else:
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": parsed["text"],
                        "tools": parsed["tools"],
                        "suggested": parsed.get("suggested", []),
                    })
            else:
                # Judge OFF: auto-execute if confidence >= 0.85
                asset_id, confidence = extract_asset_from_analysis(parsed["text"]) if agent_wants_action else (None, None)

                if agent_wants_action and asset_id is not None and confidence is not None and confidence >= 0.85:
                    results = []
                    wo_result = execute_create_work_order(asset_id, confidence, f"AGENT-RCA-{asset_id}", override=False)
                    results.append(f"CreateWorkOrder: {wo_result}")
                    notif_result = execute_notify_critical_alert(
                        asset_id, confidence,
                        f"Critical anomaly on {asset_id}, confidence={confidence}. Work order created.",
                    )
                    results.append(f"NotifyCriticalAlert: {notif_result}")
                    action_summary = "\n".join(f"- {r}" for r in results)
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": parsed["text"] + f"\n\n**Auto-executed (confidence {confidence:.4f} >= 0.85):**\n\n{action_summary}",
                        "tools": parsed["tools"] + ["CreateWorkOrder", "NotifyCriticalAlert"],
                    })
                else:
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": parsed["text"],
                        "tools": parsed["tools"],
                        "suggested": parsed.get("suggested", []),
                    })
        except Exception as e:
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": f"Error: {str(e)[:500]}",
            })
        finally:
            st.session_state.processing = False
        st.rerun()


# ========================================
# TAB 3 — OEE & Trends Dashboard
# ========================================
with tab3:
    st.subheader("OEE & Fleet Trends")

    filter_cols = st.columns(3)
    with filter_cols[0]:
        @st.cache_data(ttl=300)
        def get_wind_farms():
            df = run_query("SELECT DISTINCT WIND_FARM FROM PDM_OEE_DB.RAW.ASSET_MASTER ORDER BY WIND_FARM")
            return ["ALL"] + df["WIND_FARM"].tolist()
        farm = st.selectbox("Wind Farm", get_wind_farms(), key="oee_farm")

    with filter_cols[1]:
        @st.cache_data(ttl=300)
        def get_subsystems():
            df = run_query("SELECT DISTINCT SUBSYSTEM FROM PDM_OEE_DB.RAW.ASSET_MASTER ORDER BY SUBSYSTEM")
            return df["SUBSYSTEM"].tolist()
        subs = st.multiselect("Subsystem", get_subsystems(), default=get_subsystems(), key="oee_subs")

    with filter_cols[2]:
        view_by = st.selectbox("View by", ["Wind Farm", "Turbine", "Subsystem"], key="oee_view")

    # Fleet summary cards
    @st.cache_data(ttl=60)
    def fleet_summary():
        return run_query("""
            SELECT COUNT(*) AS TOTAL_ASSETS,
                   ROUND(AVG(AVG_OEE), 3) AS FLEET_OEE,
                   SUM(CASE WHEN HEALTH_STATUS='CRITICAL' THEN 1 ELSE 0 END) AS CRITICAL,
                   COUNT(ALERT_CONFIDENCE) AS ALERTS,
                   COALESCE(ROUND(SUM(TOTAL_FAILURE_COST)), 0) AS TOTAL_FAILURE_COST
            FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE
        """)

    summary = fleet_summary()
    if not summary.empty:
        r = summary.iloc[0]
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Fleet Avg OEE", f"{float(r['FLEET_OEE'])*100:.1f}%")
        mc2.metric("Critical Assets", int(r["CRITICAL"]))
        mc3.metric("Active Alerts", int(r["ALERTS"]))
        mc4.metric("Total Failure Cost", f"${int(r['TOTAL_FAILURE_COST']):,}")
        st.divider()

    # OEE Over Time
    st.markdown("#### OEE Over Time")

    farm_filter = f"AND m.WIND_FARM = '{farm}'" if farm != "ALL" else ""
    subs_list = ",".join(f"'{s}'" for s in subs)
    subs_filter = f"AND m.SUBSYSTEM IN ({subs_list})" if subs else "AND 1=0"
    group_col = {"Wind Farm": "m.WIND_FARM", "Turbine": "m.TURBINE_ID", "Subsystem": "m.SUBSYSTEM"}[view_by]
    group_alias = view_by.upper().replace(" ", "_")

    @st.cache_data(ttl=120)
    def load_oee_trend(gc, ga, ff, sf):
        return run_query(f"""
            SELECT o.SHIFT_DATE, {gc} AS {ga}, ROUND(AVG(o.OEE), 3) AS OEE
            FROM PDM_OEE_DB.GOLD.GOLD_OEE_METRICS o
            JOIN PDM_OEE_DB.RAW.ASSET_MASTER m ON o.ASSET_ID = m.ASSET_ID
            WHERE 1=1 {ff} {sf}
            GROUP BY o.SHIFT_DATE, {gc}
            ORDER BY o.SHIFT_DATE
        """)

    oee_df = load_oee_trend(group_col, group_alias, farm_filter, subs_filter)
    if not oee_df.empty:
        oee_chart = alt.Chart(oee_df).mark_line(point=True).encode(
            x=alt.X("SHIFT_DATE:T", title="Date"),
            y=alt.Y("OEE:Q", title="OEE", scale=alt.Scale(domain=[0.5, 1.0])),
            color=alt.Color(f"{group_alias}:N", title=view_by),
            tooltip=["SHIFT_DATE:T", f"{group_alias}:N", "OEE:Q"],
        ).properties(height=350).interactive()
        st.altair_chart(oee_chart, use_container_width=True)
    else:
        st.info("No OEE data for selected filters.")

    # Reliability metrics
    st.markdown("#### Reliability Metrics by Wind Farm")

    @st.cache_data(ttl=120)
    def load_reliability():
        return run_query("""
            SELECT WIND_FARM,
                   ROUND(AVG(AVG_REPAIR_HOURS), 1) AS AVG_REPAIR_HRS,
                   SUM(TOTAL_FAILURES) AS FAILURES,
                   ROUND(SUM(TOTAL_FAILURE_COST)) AS COST
            FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE
            WHERE TOTAL_FAILURES > 0
            GROUP BY WIND_FARM ORDER BY WIND_FARM
        """)

    rel_df = load_reliability()
    if not rel_df.empty:
        rc1, rc2 = st.columns(2)
        with rc1:
            mttr_chart = alt.Chart(rel_df).mark_bar().encode(
                x=alt.X("WIND_FARM:N", title="Wind Farm"),
                y=alt.Y("AVG_REPAIR_HRS:Q", title="Avg Repair Hours (MTTR)"),
                color="WIND_FARM:N",
                tooltip=["WIND_FARM", "AVG_REPAIR_HRS", "FAILURES"],
            ).properties(height=280, title="Avg Repair Time (MTTR)")
            st.altair_chart(mttr_chart, use_container_width=True)

        with rc2:
            cost_chart = alt.Chart(rel_df).mark_bar().encode(
                x=alt.X("WIND_FARM:N", title="Wind Farm"),
                y=alt.Y("COST:Q", title="Failure Cost ($)"),
                color="WIND_FARM:N",
                tooltip=["WIND_FARM", "COST", "FAILURES"],
            ).properties(height=280, title="Total Failure Cost")
            st.altair_chart(cost_chart, use_container_width=True)

    # Subsystem failure breakdown
    st.markdown("#### Failure Distribution by Subsystem")

    @st.cache_data(ttl=120)
    def load_subsystem_failures():
        return run_query("""
            SELECT SUBSYSTEM,
                   SUM(TOTAL_FAILURES) AS FAILURES,
                   ROUND(SUM(TOTAL_FAILURE_COST)) AS COST
            FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE
            WHERE TOTAL_FAILURES > 0
            GROUP BY SUBSYSTEM ORDER BY FAILURES DESC
        """)

    sub_df = load_subsystem_failures()
    if not sub_df.empty:
        sc1, sc2 = st.columns(2)
        with sc1:
            pie = alt.Chart(sub_df).mark_arc(innerRadius=50).encode(
                theta="FAILURES:Q",
                color=alt.Color("SUBSYSTEM:N", title="Subsystem"),
                tooltip=["SUBSYSTEM", "FAILURES", "COST"],
            ).properties(height=280, title="Failures by Subsystem")
            st.altair_chart(pie, use_container_width=True)

        with sc2:
            cost_bar = alt.Chart(sub_df).mark_bar().encode(
                x=alt.X("SUBSYSTEM:N", title="Subsystem"),
                y=alt.Y("COST:Q", title="Failure Cost ($)"),
                color="SUBSYSTEM:N",
                tooltip=["SUBSYSTEM", "COST", "FAILURES"],
            ).properties(height=280, title="Failure Cost by Subsystem")
            st.altair_chart(cost_bar, use_container_width=True)
