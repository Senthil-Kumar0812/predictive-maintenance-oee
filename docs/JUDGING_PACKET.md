# Predictive Maintenance + OEE Command Center
## Snowflake Hackathon — Technical Judging Packet

**Author:** Senthil Kumar G S
**Account:** YOUR_SNOWFLAKE_ACCOUNT (Azure Central India)
**Date:** September 2026

---

## 1. Problem Statement

Wind farm operators lack a unified view of asset health, anomaly detection, and production efficiency. Maintenance decisions are reactive — technicians respond to failures rather than predicting them. This project builds a fully Snowflake-native system that:

1. Ingests sensor telemetry (768K readings, 50 assets, 3 wind farms)
2. Detects anomalies using ML models trained on historical baselines
3. Prioritizes alerts with statistical guardrails
4. Enables operator action through an AI agent with human-in-the-loop controls
5. Tracks OEE (Overall Equipment Effectiveness) alongside maintenance health

---

## 2. Architecture

```
RAW → BRONZE → SILVER → GOLD
 │       │        │        │
 │  4 DTs (cleanse,  2 DTs (feature   2 DTs (OEE,
 │   deduplicate)    engineering,      work order
 │                   24h stats,        enrichment)
 │                   PIT joins)
 │
 ├── SENSOR_STREAM (768K rows)
 ├── ERP_WORKORDER (27 records)
 ├── MAINTENANCE_LOG (29 notes)
 ├── PRODUCTION_LOG (1000 shifts)
 ├── ASSET_MASTER (50 assets)
 ├── REPLAY_BUFFER (hourly drip)
 └── GROUND_TRUTH_BACKTEST (18 labeled events)
```

### Snowflake Services Used

| Service | Usage |
|---------|-------|
| **Dynamic Tables (8)** | Medallion pipeline, all 15-min lag, mostly incremental |
| **ML: ANOMALY_DETECTION (2)** | Vibration + Temperature models (v21), trained on 10-day baseline |
| **Cortex Agent** | PDM_COMMAND_CENTER_AGENT with 4 tools |
| **Cortex Search** | MAINTENANCE_SEARCH_SVC over maintenance logs |
| **Semantic View** | PDM_OEE_COMMAND_CENTER for FleetAnalytics tool |
| **DATA_AGENT_RUN** | Agent invocation from Streamlit |
| **Streamlit in Snowflake** | Container runtime, 3-tab Command Center UI |
| **SYSTEM$SEND_EMAIL** | HTML-formatted critical alert notifications |
| **Tasks (5)** | Scoring, alerting, fleet summary, retrain candidacy, replay |
| **Stored Procedures** | CREATE_WORK_ORDER, NOTIFY_CRITICAL_ALERT, scoring, replay |

---

## 3. Anomaly Detection & Threshold Design

### Model Architecture
- **Input features:** VIB_1H_AVG, VIB_1H_STD, TEMP_1H_AVG, TEMP_1H_STD, RPM_DELTA, HOURS_SINCE_LAST_WO
- **Training window:** Days 1-10 of sensor data (normal operations)
- **Scoring window:** Day 11 (degraded conditions for ground-truth assets)
- **Output:** Per-asset, per-15-min-bucket anomaly flag (0/1)

### Statistical Threshold (k=13)
- 576 scoring windows per asset (24h × 4 buckets/hr × 6 feature sets)
- Binomial(n=576, p=0.01): mean=5.76, σ=2.39
- Threshold: mean + 3σ = 5.76 + 7.17 ≈ 13
- Interpretation: An asset exceeding 13 anomaly flags in 24h is behaving outside the 99.87th percentile of normal variation

### Alert Classification
| Status | Threshold | Count |
|--------|-----------|-------|
| AUTO_ELIGIBLE | confidence ≥ 0.85 | 6 |
| NEEDS_REVIEW | 0.50 ≤ confidence < 0.85 | 9 |
| LOGGED_ONLY | confidence < 0.50 | 12 |
| **Total** | | **27** |

### Precision / Recall
- **Detection recall:** 100% — all 13 ground-truth anomalous assets appear in ALERT_QUEUE
- **Actionable recall:** 84.6% — 11 of 13 reach NEEDS_REVIEW or AUTO_ELIGIBLE
- **Precision:** 73.3% — 11 true positives out of 15 flagged above NEEDS_REVIEW threshold
- **Design intent:** Favor recall over precision for safety-critical rotating equipment

---

## 4. Agent Design

### Tools
1. **FleetAnalytics** — Semantic view over COMMAND_CENTER_WIDE (50 assets, failure history, cost, MTTR)
2. **MaintenanceSearch** — Cortex Search over BRONZE_MAINTENANCE_LOG (semantic retrieval)
3. **CREATE_WORK_ORDER** — Stored procedure: validates confidence ≥ 0.85 (or override), inserts into ERP_WORKORDER, logs to AGENT_ACTION_LOG
4. **NOTIFY_CRITICAL_ALERT** — Stored procedure: gathers asset/alert/history context, sends HTML email via SYSTEM$SEND_EMAIL

### Judge Mode (Human-in-the-Loop)
- **ON:** Agent analyzes → Confirm/Deny buttons → human clicks → procedures execute
- **OFF:** Agent analyzes → auto-execute when confidence ≥ 0.85 (no human step)
- **Guardrail:** Confidence < 0.85 blocks work order creation regardless of mode
- **Duplicate guard:** `processing` flag prevents double-submission

### Invocation
```python
raw = session.sql(f"""
    SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
        'PDM_OEE_DB.GOLD.PDM_COMMAND_CENTER_AGENT',
        $${prompt}$$
    )
""").collect()
```

---

## 5. Streamlit Command Center

Three-tab interface on container runtime (SYSTEM_COMPUTE_POOL_CPU):

| Tab | Content |
|-----|---------|
| **Alert Triage** | 27-alert table with status badges, confidence bars, priority sorting, expandable detail rows |
| **Chat & RCA** | Agent chat with Judge Mode toggle, Confirm/Deny buttons, auto-execute path |
| **OEE Dashboard** | Availability / Performance / Quality metrics by wind farm, turbine, shift |

---

## 6. Email Notification Format

Professional HTML email sent via SYSTEM$SEND_EMAIL with `text/html` MIME type:
- Red banner header: "CRITICAL ANOMALY ALERT"
- Asset identification table (ID, subsystem, wind farm, criticality)
- Alert details table (status, confidence, priority, driving signal)
- Work order table (WO ID, timestamp)
- Recent history section (prior failures, cost, MTTR, maintenance notes)
- Auto-generated disclaimer with threshold disclosure

Maintenance notes show asset-specific history when available, with clear fleet-fallback attribution when using subsystem-level notes.

---

## 7. Replay Mechanism

REPLAY_BUFFER contains 24 hours of Day 11 sensor data, dripped one hour at a time by REPLAY_TASK. This simulates real-time data arrival:
- Hours 0-15 consumed (current state)
- Hours 16-23 remaining
- WF02-T03-GBX crossed from 0.8124 (NEEDS_REVIEW) → 0.8832 (AUTO_ELIGIBLE) during hour 15

---

## 8. Key Design Decisions

1. **Dynamic Tables over Streams+Tasks for pipeline:** Declarative, incremental, self-healing
2. **Binomial threshold over arbitrary cutoff:** Statistically grounded, explainable to auditors
3. **Confidence = anomaly_count / k:** Intuitive 0-1 scale, threshold at 0.85 maps to ~11 anomalies
4. **Point-in-time joins in SILVER:** Prevents data leakage from future work orders into model features
5. **Judge Mode as toggle, not role-based:** Simpler for demo; production would use RBAC
6. **Agent invokes procedures via app, not natively:** DATA_AGENT_RUN invokes tools as SELECT (UDF), but CREATE_WORK_ORDER needs DML — so the app calls procedures directly after agent analysis
7. **Per-recipient email loop with try/catch:** Graceful failure if one recipient fails; production would expand ALLOWED_RECIPIENTS

---

## 9. Object Inventory

| Schema | Object | Type |
|--------|--------|------|
| RAW | SENSOR_STREAM | Table |
| RAW | ASSET_MASTER | Table |
| RAW | ERP_WORKORDER | Table |
| RAW | MAINTENANCE_LOG | Table |
| RAW | PRODUCTION_LOG | Table |
| RAW | REPLAY_BUFFER | Table |
| RAW | AGENT_ACTION_LOG | Table |
| RAW | GROUND_TRUTH_BACKTEST | Table |
| BRONZE | BRONZE_SENSOR_STREAM | Dynamic Table |
| BRONZE | BRONZE_ERP_WORKORDER | Dynamic Table |
| BRONZE | BRONZE_MAINTENANCE_LOG | Dynamic Table |
| BRONZE | BRONZE_PRODUCTION_LOG | Dynamic Table |
| SILVER | SILVER_SENSOR_ENRICHED | Dynamic Table |
| SILVER | SILVER_SENSOR_STATS_24H | Dynamic Table |
| SILVER | SILVER_WORKORDER_ENRICHED | Dynamic Table |
| GOLD | GOLD_OEE_METRICS | Dynamic Table |
| GOLD | ALERT_QUEUE | Table (materialized by procedure) |
| GOLD | COMMAND_CENTER_WIDE | View |
| GOLD | FLEET_METRICS | View |
| GOLD | PDM_OEE_COMMAND_CENTER | Semantic View |
| GOLD | MAINTENANCE_SEARCH_SVC | Cortex Search Service |
| GOLD | PDM_COMMAND_CENTER_AGENT | Cortex Agent |
| GOLD | TURBINE_FLEET_COMMAND_CENTER | Streamlit App |
| GOLD | CREATE_WORK_ORDER | Procedure |
| GOLD | NOTIFY_CRITICAL_ALERT | Procedure |
| GOLD | SCORING_PROC | Procedure |
| GOLD | CRITICAL_ALERT_PROC | Procedure |
| GOLD | FLEET_SUMMARY_PROC | Procedure |
| GOLD | RETRAIN_CANDIDACY_PROC | Procedure |
| RAW | REPLAY_BATCH_PROC | Procedure |
| GOLD | VIB_ANOMALY_MODEL | ML Model |
| GOLD | TEMP_ANOMALY_MODEL | ML Model |

---

## 10. Trial Budget

| Item | Value |
|------|-------|
| Credits allocated | $400 |
| Credits remaining | ~$264 |
| Days remaining | 29 |
| Primary cost driver | Compute pool (container runtime) |
| Warehouse size | X-Small (Gen2) |
