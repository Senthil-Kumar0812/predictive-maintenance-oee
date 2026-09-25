# Predictive Maintenance & OEE Command Center

A fully Snowflake-native system for wind turbine fleet monitoring, anomaly detection, and automated maintenance response — built for the Snowflake Hackathon.

## What It Does

Monitors 50 wind turbine assets across 3 wind farms, detecting anomalies in vibration and temperature sensor data using Snowflake ML. When anomalies exceed a statistically-grounded threshold, the system triages alerts, creates work orders, and sends HTML email notifications — all controlled through a Streamlit Command Center with an AI agent and human-in-the-loop guardrails.

**Validated Results:**
- **100% detection recall** — all 13 ground-truth anomalous assets detected
- **84.6% actionable recall** — 11 of 13 reach actionable status
- **73.3% precision** — intentionally favoring recall for safety-critical equipment
- **0.85 confidence guardrail** — blocks automated action below threshold

## Architecture

```
RAW → BRONZE → SILVER → GOLD
       4 DTs      3 DTs     1 DT     (8 Dynamic Tables, 15-min lag)
       cleanse    features   OEE      (all incremental)
       dedup      24h stats
                  PIT joins
```

### Snowflake Services Used

| Service | Usage |
|---------|-------|
| Dynamic Tables (8) | Medallion pipeline, all incremental, 15-min target lag |
| ML: ANOMALY_DETECTION (2) | Vibration + Temperature models, trained on 10-day baseline |
| Cortex Agent | 4-tool agent: semantic view, Cortex Search, 2 action procedures |
| Cortex Search | Semantic retrieval over maintenance logs |
| Semantic View | FleetAnalytics tool (OEE, alerts, failure stats) |
| DATA_AGENT_RUN | Agent invocation from Streamlit |
| Streamlit in Snowflake | Container runtime, 3-tab Command Center |
| SYSTEM$SEND_EMAIL | Professional HTML alert notifications |
| Tasks (5) | Scoring, alerting, fleet summary, retrain candidacy, replay |

## Streamlit Command Center

| Tab | Description |
|-----|-------------|
| **Alert Triage** | 27 alerts with status badges, confidence bars, expandable details |
| **Chat & RCA** | Agent chat with Judge Mode toggle + Confirm/Deny buttons |
| **OEE Dashboard** | Availability / Performance / Quality by wind farm and shift |

**Judge Mode ON:** Agent analyzes → human confirms via button → actions execute
**Judge Mode OFF:** Agent analyzes → auto-executes when confidence ≥ 0.85

## Anomaly Detection

- **Threshold:** k=13, derived from Binomial(576, 0.01) mean + 3σ = 5.76 + 7.17 ≈ 13
- **Confidence:** `sqrt((anomaly_count - 13) / 50)`, capped at 1.0
- **Classification:** AUTO_ELIGIBLE (≥0.85), NEEDS_REVIEW (0.50-0.85), LOGGED_ONLY (<0.50)

## Repository Structure

```
├── sql/
│   ├── 01_raw_tables/          # Database, schemas, base tables
│   ├── 02_dynamic_tables/      # 8 DTs: Bronze → Silver → Gold
│   ├── 03_ml_models/           # ML training, scoring procedure, alert queue
│   ├── 04_semantic_view_search/ # Semantic view + Cortex Search
│   ├── 05_agent_procedures/    # Agent definition + action procedures
│   └── 06_tasks_automation/    # 5 scheduled tasks
├── streamlit_app/              # Streamlit Command Center
│   └── streamlit_app.py
├── agent_test/                 # Agent API test scripts
├── docs/
│   ├── JUDGING_PACKET.md       # Technical summary for judges
│   └── DEMO_SCRIPT.md         # Demo narration + runbooks
├── .cortex-plugin/             # CoCo skill packaging
│   └── skills/                 # Setup, operate, demo skills
└── upload_to_stage.py          # Deployment helper
```

## Setup (Fresh Snowflake Account)

### Prerequisites
- Snowflake account with ACCOUNTADMIN role
- X-Small warehouse (Gen2 recommended)
- CPU compute pool for Streamlit container runtime
- Email notification integration (`SYSTEM$SEND_EMAIL`)

### Deploy in Order

1. **Create tables:** Run `sql/01_raw_tables/01_create_tables.sql`
2. **Load data:** Insert synthetic sensor, work order, maintenance, and production data into RAW tables
3. **Create pipeline:** Run `sql/02_dynamic_tables/01_medallion_pipeline.sql`
4. **Train models & score:** Run `sql/03_ml_models/01_models_and_scoring.sql`
5. **Create semantic layer:** Run `sql/04_semantic_view_search/01_semantic_view_and_search.sql`
6. **Create agent & procedures:** Run `sql/05_agent_procedures/01_agent_and_procedures.sql`
7. **Create tasks:** Run `sql/06_tasks_automation/01_tasks.sql`
8. **Deploy Streamlit:** Upload `streamlit_app/streamlit_app.py` to stage and create Streamlit object

### Configuration

Replace these placeholders in the SQL and Python files:
- `YOUR_NOTIFICATION_INTEGRATION` → your notification integration name
- `recipient@example.com` → your email address (must be in ALLOWED_RECIPIENTS)
- `COMPUTE_WH` → your warehouse name
- `<YOUR_CONNECTION_NAME>` → your `~/.snowflake/connections.toml` connection name

## Key Design Decisions

1. **Dynamic Tables over Streams+Tasks** — declarative, incremental, self-healing pipeline
2. **Binomial threshold** — statistically grounded, explainable to auditors (not arbitrary)
3. **Point-in-time joins in SILVER** — prevents data leakage from future work orders
4. **Judge Mode toggle** — human-in-the-loop for safety; production would use RBAC
5. **App calls procedures directly** — DATA_AGENT_RUN invokes tools as SELECT; DML requires direct CALL

## License

This project was built for the Snowflake Hackathon. All code is provided as-is.
