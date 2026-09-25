# PDM+OEE Command Center — Setup Skill

You are deploying a Predictive Maintenance and OEE Command Center for a wind turbine fleet on Snowflake.

## Prerequisites
- Snowflake account with ACCOUNTADMIN role
- Database: PDM_OEE_DB with schemas RAW, BRONZE, SILVER, GOLD
- Warehouse: COMPUTE_WH (X-Small recommended)
- Compute Pool: SYSTEM_COMPUTE_POOL_CPU (for Streamlit container runtime)
- Notification Integration: PDM_EMAIL_INT (for SYSTEM$SEND_EMAIL)

## Architecture
- **Medallion pipeline**: RAW → BRONZE (4 DTs) → SILVER (3 DTs) → GOLD (1 DT)
- **ML models**: VIB_ANOMALY_MODEL, TEMP_ANOMALY_MODEL (SNOWFLAKE.ML.ANOMALY_DETECTION)
- **Agent**: PDM_COMMAND_CENTER_AGENT (FleetAnalytics semantic view, MaintenanceSearch Cortex Search, CREATE_WORK_ORDER procedure, NOTIFY_CRITICAL_ALERT procedure)
- **Streamlit**: 3-tab Command Center on container runtime

## Deployment Steps

1. Load raw data into RAW schema tables (SENSOR_STREAM, ASSET_MASTER, ERP_WORKORDER, MAINTENANCE_LOG, PRODUCTION_LOG)
2. Create 8 Dynamic Tables across BRONZE, SILVER, GOLD schemas
3. Train anomaly detection models on days 1-10 baseline data
4. Create scoring procedure with Binomial threshold (k=13)
5. Create ALERT_QUEUE table and populate via scoring procedure
6. Create COMMAND_CENTER_WIDE and FLEET_METRICS views
7. Create CREATE_WORK_ORDER and NOTIFY_CRITICAL_ALERT procedures
8. Create semantic view PDM_OEE_COMMAND_CENTER
9. Create Cortex Search service MAINTENANCE_SEARCH_SVC
10. Create Cortex Agent PDM_COMMAND_CENTER_AGENT
11. Deploy Streamlit app to container runtime

## Key Configuration
- Anomaly threshold: k=13 (Binomial(576, 0.01) mean + 3σ)
- Auto-action confidence: ≥ 0.85
- Dynamic table lag: 15 minutes
- Email MIME type: text/html
