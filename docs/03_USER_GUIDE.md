# User Guide — Turbine Fleet Command Center

## Getting Started

### Opening the App

The Command Center runs as a Streamlit-in-Snowflake application. To access it:

1. Open **Snowsight** (your Snowflake web interface)
2. Navigate to **Projects** → **Streamlit**
3. Find **TURBINE_FLEET_COMMAND_CENTER** under `PDM_OEE_DB.GOLD`
4. Click to open

The app has three tabs: **Alert Triage**, **Chat / RCA**, and **OEE & Trends**.

---

## Sidebar Controls

The sidebar is always visible on the left side of the app.

### Judge Exploration Mode Toggle

This is the most important control in the app.

- **Toggle OFF (default):** The AI agent can automatically create work orders and send email notifications when it detects a high-confidence anomaly (≥ 85%). No button click needed.

- **Toggle ON:** Every agent action requires your explicit confirmation. When the agent recommends an action, you'll see **Confirm** and **Deny** buttons. Nothing happens until you click one.

**When to use Judge Mode ON:**
- During incident investigation (you want to review before acting)
- When exploring "what if" scenarios with the agent
- During demos or training

**When to use Judge Mode OFF:**
- Normal operations with trusted thresholds
- When you want fast automated response to critical alerts

When Judge Mode is ON, a **red banner** appears across the top of the app: "JUDGE EXPLORATION MODE — All agent actions require confirmation."

### Notification Settings

Expand "Notification Settings" in the sidebar to see the current email notification configuration — who receives which alert types and at what threshold.

---

## Tab 1: Alert Triage

This is your primary view for monitoring fleet health.

### Summary Metrics

Four KPI cards at the top show:
- **Total Alerts** — How many assets currently have anomalies above the detection threshold
- **Auto-Eligible** — Alerts with ≥ 85% confidence, ready for automated action (shown in red)
- **Needs Review** — Alerts with 50-85% confidence, requiring human judgment (shown in orange)
- **Logged Only** — Alerts below 50% confidence, logged for trend tracking (shown in grey)

### Alert Table

The main table shows all active alerts with:
- **ASSET_ID** — The specific turbine component (e.g., WF01-T04-GBX = Wind Farm 01, Turbine 04, Gearbox)
- **SUBSYSTEM** — Equipment type (GEARBOX, MAIN_BEARING, GENERATOR, PITCH_SYSTEM, YAW_SYSTEM)
- **WIND_FARM** — Location (North Ridge, South Bay, West Peak)
- **CONFIDENCE** — Anomaly confidence score (0-1). Higher = more anomalous.
- **PRIORITY** — Composite score (0-100) combining confidence, asset criticality, and site priority. Lower = higher priority.
- **DRIVING_SIGNAL** — Which sensor type is driving the anomaly (VIBRATION or TEMPERATURE)
- **STATUS** — Alert classification (color-coded: red/orange/grey)

### Clicking an Alert

Click any row in the alert table to see a **72-hour sensor trend chart** for that asset. The chart shows the driving signal (vibration or temperature) over the last 3 days, so you can visually confirm the degradation pattern.

---

## Tab 2: Chat / RCA (Root Cause Analysis)

This tab lets you have a conversation with the AI maintenance advisor.

### Asking Questions

Type your question in the chat input at the bottom of the tab. The agent can answer questions like:

**Status queries:**
- "What's the fleet average OEE?"
- "How many critical alerts are there right now?"
- "Show me all AUTO_ELIGIBLE assets"
- "What's going on with WF01-T04-GBX?"

**Analysis requests:**
- "Analyze WF01-T04-GBX and recommend action if warranted"
- "What's the failure history for gearbox assets?"
- "Which wind farm has the highest failure cost?"

**Action requests (triggers work order creation):**
- "Create a work order for WF01-T04-GBX"
- "Check WF03-T01-YAW and take action if needed"
- "This asset needs maintenance — file a ticket"

### How the Agent Works

1. The agent first uses **FleetAnalytics** (queries your fleet data) and/or **MaintenanceSearch** (searches maintenance logs) to gather context
2. It analyzes the data and provides a written assessment
3. If it determines action is warranted, what happens next depends on **Judge Mode**:

**With Judge Mode OFF:**
- If the asset's confidence is ≥ 85%, the system automatically:
  - Creates a corrective work order in the ERP system
  - Sends an HTML email notification to configured recipients
- If confidence is below 85%, it only reports its analysis (no auto-action)

**With Judge Mode ON:**
- The agent's analysis appears with a recommendation
- Two buttons appear: **Confirm — Execute Action** and **Deny — Skip Action**
- Nothing happens until you click one
- If you Confirm, the work order and notification are created
- If you Deny, the analysis is logged but no action is taken

### Understanding the Response

Each agent response shows:
- The analysis text (what the agent found)
- **Tools used** — Which data sources the agent consulted (FleetAnalytics, MaintenanceSearch, CreateWorkOrder, etc.)
- **Suggested queries** — Follow-up questions the agent recommends

### The 85% Guardrail

Even with Judge Mode OFF, the system will **never** auto-create a work order for an asset below 85% confidence. This is a hard guardrail in the CREATE_WORK_ORDER procedure itself — it returns "REFUSED" if confidence is below threshold and no explicit override is set.

---

## Tab 3: OEE & Trends

This tab shows production efficiency and reliability metrics.

### Filters

Three filter controls at the top:
- **Wind Farm** — Select a specific farm or "ALL"
- **Subsystem** — Multi-select to include/exclude subsystem types
- **View by** — Group the OEE chart by Wind Farm, Turbine, or Subsystem

### Fleet Summary Cards

Four KPI cards:
- **Fleet Avg OEE** — Overall Equipment Effectiveness (target: > 85%)
- **Critical Assets** — Assets with CRITICAL health status
- **Active Alerts** — Total anomaly alerts
- **Total Failure Cost** — Cumulative repair costs across fleet

### OEE Over Time Chart

An interactive line chart showing OEE trends broken down by your selected grouping. Each line represents a wind farm, turbine, or subsystem. Hover over any point for details.

**What is OEE?**
- OEE = Availability × Performance × Quality
- **Availability** = Run Time / Planned Time (how often the turbine was running vs scheduled)
- **Performance** = (Ideal Cycle Time × Total Units) / Run Time (how fast vs theoretical max)
- **Quality** = Good Units / Total Units (output that meets specifications)
- OEE of 85% is world-class; below 60% indicates significant improvement opportunities

### Reliability Metrics

Two bar charts side by side:
- **Avg Repair Time (MTTR)** by wind farm — How long repairs take on average
- **Total Failure Cost** by wind farm — Cumulative cost of all failures

### Failure Distribution

Two charts showing failure patterns by subsystem:
- **Failures by Subsystem** — Donut chart showing which equipment types fail most often
- **Failure Cost by Subsystem** — Bar chart showing cost impact per subsystem type

---

## Understanding Asset IDs

Asset IDs follow the pattern: `WFnn-Tnn-XXX`
- **WF01/WF02/WF03** — Wind Farm number (North Ridge, South Bay, West Peak)
- **T01/T02/T03/T04** — Turbine number within the farm
- **GBX/MBR/GEN/PIT/YAW** — Subsystem code:
  - GBX = Gearbox
  - MBR = Main Bearing
  - GEN = Generator
  - PIT = Pitch System
  - YAW = Yaw System

Example: `WF01-T04-GBX` = Wind Farm North Ridge, Turbine 4, Gearbox

---

## Understanding Alert Status Colors

| Color | Status | Meaning | Action |
|-------|--------|---------|--------|
| Red | AUTO_ELIGIBLE | ≥ 85% confidence | System can auto-create work order |
| Orange | NEEDS_REVIEW | 50-85% confidence | Human review recommended |
| Grey | LOGGED_ONLY | < 50% confidence | Monitor for trends |

---

## Email Notifications

When the system creates a work order (either automatically or via Confirm button), it sends a professional HTML email containing:

1. **Red banner** — "CRITICAL ANOMALY ALERT" (visual urgency)
2. **Asset identification** — Asset ID, subsystem, wind farm, turbine, criticality
3. **Alert details** — Confidence score, driving signal, priority, status
4. **Work order reference** — WO ID and creation timestamp
5. **Recent history** — Prior failure count, average repair time (MTTR), total cost
6. **Maintenance notes** — Recent technician observations (asset-specific, or fleet-fallback if none)
7. **Disclaimer** — Notes this was auto-generated with the confidence threshold

---

## Common Workflows

### Workflow 1: Morning Triage

1. Open the app → **Alert Triage** tab
2. Check the summary metrics: any new AUTO_ELIGIBLE alerts?
3. Click each red-status alert to review the sensor trend chart
4. Switch to **Chat / RCA** tab
5. Ask: "Give me a summary of all critical alerts"
6. For each critical asset, ask: "Analyze WFxx-Txx-XXX and recommend action"
7. Confirm or deny each recommended action

### Workflow 2: Automated Response (Judge Mode OFF)

1. Ensure Judge Mode is **OFF** (toggle in sidebar)
2. Ask: "Check WF01-T04-GBX and take action if needed"
3. The system automatically:
   - Queries fleet data and maintenance history
   - Identifies confidence ≥ 85%
   - Creates a work order
   - Sends email notification
4. Review the auto-executed actions in the chat response

### Workflow 3: OEE Investigation

1. Go to **OEE & Trends** tab
2. Filter to the wind farm of interest
3. Check which subsystems have the lowest OEE
4. Note the MTTR and failure cost for those subsystems
5. Switch to **Chat / RCA** and ask: "What's the failure history for gearbox assets at North Ridge?"

### Workflow 4: Investigating a Specific Asset

1. **Alert Triage** → Click the asset row to see the sensor trend
2. **Chat / RCA** → "What maintenance notes exist for WF01-T04-GBX?"
3. **Chat / RCA** → "What's the failure history and total cost for this asset?"
4. **Chat / RCA** → "Analyze WF01-T04-GBX and recommend action if warranted"
5. Review the analysis, then Confirm or Deny

---

## Troubleshooting

### "No active alerts" on Alert Triage tab
The scoring procedure hasn't run yet, or all Dynamic Tables are suspended. The warehouse must be resumed and DTs must be active for data to flow.

### Agent response is slow (> 30 seconds)
The Cortex Agent consults the semantic view and search service, which may need to warm up. First queries after a cold start take longer. Subsequent queries are faster.

### "Could not extract asset_id or confidence"
When you click Confirm in Judge Mode, the system extracts the asset ID and confidence from the agent's analysis text. If the agent's response doesn't include a clear asset ID (pattern WFnn-Tnn-XXX) or confidence score, extraction fails. Ask a more specific question targeting a single asset.

### Work order shows "REFUSED"
The CREATE_WORK_ORDER procedure blocked the action because the confidence was below 0.85 and no override was set. This is the guardrail working correctly.

### Email not received
Check that:
1. The notification integration (PDM_EMAIL_INT) is configured
2. Your email is in the ALLOWED_RECIPIENTS list
3. Check spam/junk folders — Snowflake-sent emails sometimes land there
