# PDM+OEE Command Center — Demo Skill

You are running the hackathon demo for the PDM+OEE Command Center.

## Pre-Flight (run all, verify green)

1. Resume warehouse and compute pool:
```sql
ALTER WAREHOUSE COMPUTE_WH RESUME;
ALTER COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU RESUME;
```

2. Resume all 8 Dynamic Tables:
```sql
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_SENSOR_STREAM RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_ERP_WORKORDER RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_MAINTENANCE_LOG RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.BRONZE.BRONZE_PRODUCTION_LOG RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_ENRICHED RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.SILVER.SILVER_WORKORDER_ENRICHED RESUME;
ALTER DYNAMIC TABLE PDM_OEE_DB.GOLD.GOLD_OEE_METRICS RESUME;
```

3. Verify Streamlit app is running:
```sql
SHOW STREAMLITS IN SCHEMA PDM_OEE_DB.GOLD;
```

4. Verify clean state:
```sql
SELECT 'Agent WOs' AS CHK, COUNT(*) AS N FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%'
UNION ALL SELECT 'Action Log', COUNT(*) FROM PDM_OEE_DB.RAW.AGENT_ACTION_LOG
UNION ALL SELECT 'AUTO_ELIGIBLE', COUNT(*) FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE STATUS = 'AUTO_ELIGIBLE';
-- Expected: 0, 0, 6
```

5. Open the Streamlit app in browser.

## Demo Sequence

### Step 1: Alert Triage Tab
Show the 27-alert triage table. Point out the 3 status categories: AUTO_ELIGIBLE (6), NEEDS_REVIEW (9), LOGGED_ONLY (12). Click an alert row to show detail.

### Step 2: OEE Dashboard Tab
Show OEE metrics broken down by wind farm. Point out Availability, Performance, Quality pillars.

### Step 3: Chat & RCA — Judge Mode ON
- Turn ON the Judge Mode toggle (should show red warning banner)
- Type: `Analyze WF01-T04-GBX and recommend action if warranted`
- Wait for agent response with Confirm/Deny buttons
- Click **Confirm** to create work order and send notification
- Show the work order was created:
```sql
SELECT WO_ID, ASSET_ID, OPENED_TS FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%' ORDER BY OPENED_TS DESC LIMIT 1;
```
- Optionally show the HTML email in inbox

### Step 4: Chat & RCA — Judge Mode OFF
- Turn OFF the Judge Mode toggle
- Type: `Check WF03-T01-YAW and take action if needed`
- Agent auto-executes (no Confirm button): work order created + notification sent automatically
- Show both work orders:
```sql
SELECT WO_ID, ASSET_ID, OPENED_TS FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%' ORDER BY OPENED_TS DESC;
```

### Step 5: Architecture Summary
Recap: 8 DTs, 2 ML models, 1 Cortex Agent, Semantic View, Cortex Search, SYSTEM$SEND_EMAIL, Streamlit on container runtime. Everything Snowflake-native.

## Post-Demo Cleanup
```sql
DELETE FROM PDM_OEE_DB.RAW.ERP_WORKORDER WHERE WO_ID LIKE 'WO-AGT%';
DELETE FROM PDM_OEE_DB.RAW.AGENT_ACTION_LOG;
```
