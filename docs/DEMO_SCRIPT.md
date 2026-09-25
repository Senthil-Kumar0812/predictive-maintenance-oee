# PDM + OEE Command Center - Demo Script

## Pre-Demo Checklist (5 min before)

```sql
-- 1. Resume compute
ALTER WAREHOUSE COMPUTE_WH RESUME;
ALTER COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU RESUME;

-- 2. Resume Dynamic Tables (run all 8)
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_SENSOR_STREAM RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_ERP_WORKORDER RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_MAINTENANCE_LOG RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_PRODUCTION_LOG RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_ENRICHED RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_WORKORDER_ENRICHED RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.GOLD.GOLD_OEE_METRICS RESUME;

-- 3. Verify Streamlit is RUNNING
SHOW STREAMLITS IN SCHEMA PDM_OEE_DB.GOLD;
-- If not running, redeploy:
-- DROP STREAMLIT IF EXISTS PDM_OEE_DB.GOLD.TURBINE_FLEET_COMMAND_CENTER;
-- CREATE STREAMLIT ... (see upload_to_stage.py for full DDL)

-- 4. Verify clean state
SELECT COUNT(*) FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%';  -- should be 0
SELECT COUNT(*) FROM PDM_OEE_DB.RAW.AGENT_ACTION_LOG;  -- should be 0
SELECT COUNT(*) FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE STATUS = 'AUTO_ELIGIBLE';  -- should be 6
```

---

## Demo Flow (Target: 6-7 minutes)

### Opening (30 sec)

> "This is a Predictive Maintenance and OEE Command Center for a wind turbine fleet.
> It monitors 50 assets across 3 wind farms, detects anomalies using Snowflake ML,
> and lets operators act through a Cortex Agent with built-in safety guardrails."

### Act 1: The Pipeline (60 sec)

Open Snowsight, show the database structure briefly.

> "The architecture follows a medallion pattern — RAW to BRONZE to SILVER to GOLD —
> implemented entirely with 8 Dynamic Tables, all incremental, 15-minute target lag.
>
> Sensor data flows through feature engineering: 1-hour rolling statistics, 24-hour
> aggregates, and point-in-time joins against work order history so the model never
> sees future data.
>
> Two Snowflake ML anomaly detection models — vibration and temperature — score every
> 15-minute window. The scoring procedure applies a statistically-derived threshold
> (k=13, from Binomial(576, 0.01) mean plus 3 sigma) and classifies each asset into
> AUTO_ELIGIBLE, NEEDS_REVIEW, or LOGGED_ONLY."

Show ALERT_QUEUE briefly:
```sql
SELECT STATUS, COUNT(*), ROUND(AVG(CONFIDENCE), 3) AS AVG_CONF
FROM PDM_OEE_DB.GOLD.ALERT_QUEUE GROUP BY STATUS ORDER BY 1;
```

### Act 2: The Command Center (90 sec)

Open the Streamlit app. Three tabs are visible.

**Tab 1 — Alert Triage:**
> "27 alerts triaged automatically. 6 are AUTO_ELIGIBLE — high confidence, ready
> for automated action. 9 need human review. 12 are logged for trend tracking."

Click into an alert row to show detail.

**Tab 3 — OEE Dashboard:**
> "OEE metrics computed from production logs — Availability, Performance, Quality —
> broken down by wind farm, turbine, and shift. This gives operations a single pane
> of glass across maintenance health and production efficiency."

### Act 3: The Agent — Judge Mode ON (120 sec)

Switch to Tab 2 (Chat & RCA). Turn ON the Judge Mode toggle.

> "Judge Mode is the safety guardrail. When it's on, the agent analyzes but never
> acts without human confirmation."

Type:
```
Analyze WF01-T04-GBX and recommend action if warranted
```

> "The agent uses the FleetAnalytics semantic view and MaintenanceSearch Cortex Search
> to pull context. It identifies this gearbox has a 94.9% anomaly confidence driven by
> temperature, and recommends a work order."

**Confirm button appears.** Click Confirm.

> "Only after human approval does the system create the work order and send a
> professional HTML notification email — with asset details, alert history, and
> maintenance context."

Show the email in inbox if possible. Show the work order:
```sql
SELECT WO_ID, ASSET_ID, TYPE, OPENED_TS FROM PDM_OEE_DB.RAW.ERP_WORKORDER
WHERE WO_ID LIKE 'WO-AGT%' ORDER BY OPENED_TS DESC LIMIT 1;
```

### Act 4: The Agent — Judge Mode OFF (60 sec)

Turn OFF Judge Mode.

> "In production, operators can disable Judge Mode for auto-action. When confidence
> exceeds 85%, the system creates the work order and sends notification automatically
> — no button click needed."

Type:
```
Check WF03-T01-YAW and take action if needed
```

> "This yaw system has 94.9% confidence. Judge Mode is off, so the agent auto-executes:
> work order created, email sent, no human in the loop. The 85% threshold is the
> guardrail — below that, the agent only reports."

### Act 5: Closing / Architecture Recap (60 sec)

> "To summarize the Snowflake-native stack:
> - 8 Dynamic Tables (medallion pipeline, all incremental)
> - 2 ML anomaly detection models (vibration + temperature)
> - 1 Cortex Agent with 4 tools (semantic view, Cortex Search, 2 procedures)
> - DATA_AGENT_RUN for agent invocation
> - Streamlit in Snowflake on container runtime
> - SYSTEM$SEND_EMAIL for HTML notifications
> - Statistically-grounded threshold (Binomial model, k=13)
> - 100% detection recall on ground truth, 73% precision (intentionally conservative)
>
> Everything runs inside Snowflake. No external services, no API keys, no infrastructure."

---

## Backup Talking Points

**If asked about false positives:**
> "Precision is 73% — we intentionally favor recall over precision for safety-critical
> equipment. The Judge Mode guardrail catches false positives before action is taken."

**If asked about the 2 missed detections (11/13 actionable):**
> "Two assets — WF01-T03-PIT and WF03-T02-YAW — have genuine subtle signals that
> haven't accumulated enough anomaly counts to cross the threshold yet. Detection recall
> is 100% (all 13 appear in the alert queue). Actionable recall is 85% — the threshold
> is doing its job by not over-triggering on marginal signals."

**If asked about replay:**
> "We use a replay buffer with hourly batch drip to simulate real-time data arrival.
> During testing, WF02-T03-GBX crossed from NEEDS_REVIEW to AUTO_ELIGIBLE as more
> data accumulated — exactly the behavior we'd see in production."

**If asked about cost:**
> "Running on X-Small warehouse, trial account. Dynamic tables with 15-minute lag
> keep compute minimal. Container runtime for Streamlit is the main cost driver."

---

## Post-Demo Cleanup

```sql
-- Delete any work orders created during demo
DELETE FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%';
DELETE FROM PDM_OEE_DB.RAW.AGENT_ACTION_LOG;

-- Suspend everything
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_SENSOR_STREAM SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_ERP_WORKORDER SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_MAINTENANCE_LOG SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_PRODUCTION_LOG SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_ENRICHED SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_WORKORDER_ENRICHED SUSPEND;
ALTER DYNAMIC TABLE PDM_OEE_DB.GOLD.GOLD_OEE_METRICS SUSPEND;

ALTER WAREHOUSE COMPUTE_WH SUSPEND;
ALTER COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU STOP ALL;
ALTER COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU SUSPEND;
```
