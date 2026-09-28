# Architecture Documentation

## System Overview

The PDM + OEE Command Center is a fully Snowflake-native predictive maintenance and production efficiency monitoring system for a wind turbine fleet. It monitors 50 turbine subsystem assets across 3 wind farms, detects anomalies in real-time sensor data, and enables automated or human-approved maintenance actions through an AI agent.

## High-Level Architecture

```
                        ┌──────────────────────────────────────────┐
                        │           STREAMLIT COMMAND CENTER       │
                        │  ┌──────────┬──────────┬──────────────┐  │
                        │  │  Alert   │  Chat /  │  OEE &       │  │
                        │  │  Triage  │  RCA     │  Trends      │  │
                        │  └────┬─────┴────┬─────┴──────┬───────┘  │
                        └───────┼──────────┼────────────┼──────────┘
                                │          │            │
                    ┌───────────┘     ┌────┘            └───────────┐
                    ▼                 ▼                              ▼
            ┌──────────────┐  ┌─────────────────┐           ┌──────────────┐
            │  ALERT_QUEUE │  │  CORTEX AGENT   │           │  GOLD_OEE    │
            │  (27 alerts) │  │  4 tools:       │           │  _METRICS    │
            └──────────────┘  │  - FleetAnalytics│          └──────────────┘
                              │  - Maint.Search  │
                              │  - CreateWO      │
                              │  - NotifyAlert   │
                              └────────┬─────────┘
                                       │
                    ┌──────────────────┬┴──────────────────┐
                    ▼                  ▼                    ▼
            ┌──────────────┐  ┌──────────────┐    ┌──────────────┐
            │  SEMANTIC    │  │  CORTEX      │    │  PROCEDURES  │
            │  VIEW        │  │  SEARCH      │    │  CREATE_WO   │
            │  (text→SQL)  │  │  (semantic)  │    │  NOTIFY      │
            └──────────────┘  └──────────────┘    └──────────────┘
```

## Data Pipeline Architecture (Medallion)

```
RAW                    BRONZE                  SILVER                    GOLD
────────────────       ────────────────        ─────────────────         ──────────────
SENSOR_STREAM    ──►   BRONZE_SENSOR     ──►   SILVER_SENSOR       ──►  GOLD_OEE
  768K rows            _STREAM                 _ENRICHED                _METRICS
                       (dedup, round)          (1h rolling stats,       (Availability
                                                PIT WO joins,           × Performance
                                                RPM delta)              × Quality)

ERP_WORKORDER    ──►   BRONZE_ERP        ──►   SILVER_SENSOR       
  25 rows              _WORKORDER               _STATS_24H         
                       (standardize)           (15-min buckets,    
                                                24h sliding windows)

MAINTENANCE_LOG  ──►   BRONZE_MAINT      ──►   SILVER_WORKORDER
  29 notes             _LOG                    _ENRICHED
                       (trim, dedup)           (WO + notes joined)

PRODUCTION_LOG   ──►   BRONZE_PROD
  1000 shifts          _LOG
                       (validate, dedup)

ASSET_MASTER           (reference table, 50 assets)
REPLAY_BUFFER          (Day 11 hourly drip, 24K rows)
AGENT_ACTION_LOG       (audit trail, auto-populated)
```

All 8 Dynamic Tables use `TARGET_LAG = '15 minutes'` and are incremental where possible.

## ML Anomaly Detection Architecture

```
SILVER_SENSOR_STATS_24H
        │
        ├───► V_ANOMALY_SCORE_VIB ───► VIB_ANOMALY_MODEL!DETECT_ANOMALIES
        │                                        │
        │                                        ▼
        │                              VIB_ANOMALY_RESULTS (17,600 rows)
        │                                        │
        └───► V_ANOMALY_SCORE_TEMP ──► TEMP_ANOMALY_MODEL!DETECT_ANOMALIES
                                                 │
                                                 ▼
                                       TEMP_ANOMALY_RESULTS (17,600 rows)
                                                 │
                                    ┌────────────┘
                                    ▼
                             SCORING_PROC
                        (combine, threshold k=13,
                         compute confidence,
                         materialize ALERT_QUEUE)
                                    │
                                    ▼
                             ALERT_QUEUE (27 alerts)
                             ├── 6 AUTO_ELIGIBLE (≥ 0.85)
                             ├── 9 NEEDS_REVIEW  (0.50-0.85)
                             └── 12 LOGGED_ONLY  (< 0.50)
```

### ML Models
- **VIB_ANOMALY_MODEL**: `SNOWFLAKE.ML.ANOMALY_DETECTION` trained on vibration bucket averages, Days 1-10 baseline
- **TEMP_ANOMALY_MODEL**: `SNOWFLAKE.ML.ANOMALY_DETECTION` trained on temperature bucket averages, Days 1-10 baseline
- Both use `prediction_interval = 0.99` for scoring

### Threshold: k = 13
- Derived from Binomial(n=576, p=0.01)
- 576 = scoring windows per asset (24h × 4 buckets/hr × ~6 feature channels)
- mean = 5.76, σ = 2.39
- k = mean + 3σ = 5.76 + 7.17 ≈ 13
- Assets with ≥ 13 anomaly flags are outside the 99.87th percentile of normal variation

### Confidence Formula
```
confidence = MIN(1.0, SQRT((total_anomalies - 13) / 50))
```

## Agent Architecture

```
User Query
    │
    ▼
DATA_AGENT_RUN (SQL function)
    │
    ▼
PDM_COMMAND_CENTER_AGENT
    │
    ├── FleetAnalytics (Semantic View → text-to-SQL)
    │   └── Queries: GOLD_OEE_METRICS, ALERT_QUEUE, FLEET_METRICS, ASSET_MASTER
    │
    ├── MaintenanceSearch (Cortex Search → semantic retrieval)
    │   └── Searches: SEARCH_CORPUS (maintenance logs, technician notes)
    │
    ├── CREATE_WORK_ORDER (generic tool → procedure)
    │   └── Guardrail: confidence ≥ 0.85 required (or explicit override)
    │   └── Creates WO in ERP_WORKORDER, logs to AGENT_ACTION_LOG
    │
    └── NOTIFY_CRITICAL_ALERT (generic tool → procedure)
        └── Sends HTML email via SYSTEM$SEND_EMAIL
        └── Includes: asset details, alert info, failure history, maintenance notes
```

**Key limitation:** DATA_AGENT_RUN invokes generic tools as SELECT (UDF context), but CREATE_WORK_ORDER and NOTIFY_CRITICAL_ALERT need DML (INSERT). The Streamlit app calls these procedures directly after the agent provides its analysis.

## Task Automation Architecture

```
Every 15 min:
    SCORING_TASK ──► SCORING_PROC() ──► ALERT_QUEUE refreshed
        │
        └──► CRITICAL_ALERT_TASK ──► CRITICAL_ALERT_PROC()
                                      └── Emails all AUTO_ELIGIBLE alerts

Every 60 min:
    REPLAY_TASK ──► REPLAY_BATCH_PROC()
                     └── Drips 1 hour of Day 11 data into SENSOR_STREAM

Daily at 6 AM:
    FLEET_SUMMARY_TASK ──► FLEET_SUMMARY_PROC()
                            └── Fleet OEE + alert digest email

Every 6 hours:
    RETRAIN_CANDIDACY_TASK ──► RETRAIN_CANDIDACY_PROC()
                                └── Checks if new data > 5% of baseline → suggest retrain
```

## Object Inventory

### RAW Schema (8 tables)
| Object | Type | Rows | Purpose |
|--------|------|------|---------|
| SENSOR_STREAM | Table | 768,000 | Sensor telemetry (vibration, temp, RPM) |
| ASSET_MASTER | Table | 50 | Asset registry (wind farm, subsystem, criticality) |
| ERP_WORKORDER | Table | 25 | Historical + agent-created work orders |
| MAINTENANCE_LOG | Table | 29 | Technician notes |
| PRODUCTION_LOG | Table | 1,000 | Shift-level production data (OEE source) |
| REPLAY_BUFFER | Table | 24,000 | Day 11 hourly batch drip |
| AGENT_ACTION_LOG | Table | 0 | Agent audit trail |
| DOCS | Table | 5 | Equipment documentation for search |

### BRONZE Schema (4 Dynamic Tables)
| Object | Rows | Refresh |
|--------|------|---------|
| BRONZE_SENSOR_STREAM | 768,000 | Incremental |
| BRONZE_ERP_WORKORDER | 27 | Incremental |
| BRONZE_MAINTENANCE_LOG | 29 | Incremental |
| BRONZE_PRODUCTION_LOG | 1,000 | Incremental |

### SILVER Schema (3 Dynamic Tables)
| Object | Rows | Refresh | Key Feature |
|--------|------|---------|-------------|
| SILVER_SENSOR_ENRICHED | 768,000 | Incremental | 1h rolling stats + PIT WO joins |
| SILVER_SENSOR_STATS_24H | 51,200 | Incremental | 15-min buckets + 24h windows |
| SILVER_WORKORDER_ENRICHED | 27 | Full | WOs joined with maintenance notes |

### GOLD Schema (1 DT + tables + views + services)
| Object | Type | Purpose |
|--------|------|---------|
| GOLD_OEE_METRICS | Dynamic Table (1,000 rows) | OEE = A × P × Q per asset per shift |
| ALERT_QUEUE | Table (27 rows) | Triaged alerts with confidence + priority |
| COMMAND_CENTER_WIDE | Table (50 rows) | Asset-level health summary |
| FLEET_METRICS | Table (16 rows) | Work order detail with MTBF/MTTR |
| VIB_ANOMALY_RESULTS | Table (17,600 rows) | Vibration scoring output |
| TEMP_ANOMALY_RESULTS | Table (17,600 rows) | Temperature scoring output |
| NOTIFICATION_CONFIG | Table (3 rows) | Email recipient configuration |
| SEARCH_CORPUS | Table (34 rows) | Maintenance notes + docs for search |
| V_ANOMALY_SCORE_VIB | View | Scoring input (vibration) |
| V_ANOMALY_SCORE_TEMP | View | Scoring input (temperature) |
| V_ANOMALY_TRAIN_VIB | View | Training input (vibration) |
| V_ANOMALY_TRAIN_TEMP | View | Training input (temperature) |
| PDM_OEE_COMMAND_CENTER | Semantic View | Natural language fleet data access |
| MAINTENANCE_SEARCH_SVC | Cortex Search | Semantic search over maintenance logs |
| PDM_COMMAND_CENTER_AGENT | Cortex Agent | 4-tool maintenance advisor |
| TURBINE_FLEET_COMMAND_CENTER | Streamlit App | 3-tab Command Center UI |
| VIB_ANOMALY_MODEL | ML Model | Vibration anomaly detection |
| TEMP_ANOMALY_MODEL | ML Model | Temperature anomaly detection |

### Procedures (9 total)
| Procedure | Schema | Purpose |
|-----------|--------|---------|
| GENERATE_SENSOR_DATA | RAW | Synthetic data: 768K sensor readings |
| GENERATE_REPLAY_BUFFER | RAW | Synthetic data: 24K Day 11 replay rows |
| REPLAY_BATCH_PROC | RAW | Drips 1 hour of replay data |
| REGEN_REPLAY_HOUR | RAW | Regenerates a specific replay hour |
| SCORING_PROC | GOLD | ML scoring + ALERT_QUEUE materialization |
| CRITICAL_ALERT_PROC | GOLD | Batch fleet notification |
| FLEET_SUMMARY_PROC | GOLD | Daily digest email |
| RETRAIN_CANDIDACY_PROC | GOLD | Model drift detection |
| CREATE_WORK_ORDER | GOLD | Agent action: create corrective WO |
| NOTIFY_CRITICAL_ALERT | GOLD | Agent action: HTML email notification |

### Tasks (5 total)
| Task | Schema | Schedule |
|------|--------|----------|
| SCORING_TASK | GOLD | Every 15 min |
| CRITICAL_ALERT_TASK | GOLD | After SCORING_TASK |
| FLEET_SUMMARY_TASK | GOLD | Daily 6 AM |
| RETRAIN_CANDIDACY_TASK | GOLD | Every 6 hours |
| REPLAY_TASK | RAW | Every 60 min |

## Infrastructure

| Component | Configuration |
|-----------|---------------|
| Warehouse | COMPUTE_WH (X-Small, Gen2, auto-suspend 300s) |
| Compute Pool | SYSTEM_COMPUTE_POOL_CPU (CPU_X64_S, 1-2 nodes) |
| Runtime | Container runtime (required for st.toggle, st.chat_input) |
| Notification | PDM_EMAIL_INT integration |
| Region | Azure Central India |
