/*
  Phase 6: Tasks & Automation
  - SCORING_TASK (every 15 min)
  - CRITICAL_ALERT_TASK (after scoring)
  - FLEET_SUMMARY_TASK (daily at 6 AM)
  - RETRAIN_CANDIDACY_TASK (every 6 hours)
  - REPLAY_TASK (every 60 min)
*/

-- ============================================================
-- Scoring Task (root of the task DAG)
-- ============================================================

CREATE OR REPLACE TASK PDM_OEE_DB.GOLD.SCORING_TASK
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = '15 MINUTE'
    COMMENT = 'Scores sensor data against ML baseline, refreshes ALERT_QUEUE every 15 min'
AS
CALL PDM_OEE_DB.GOLD.SCORING_PROC();

-- ============================================================
-- Critical Alert Task (runs after scoring)
-- ============================================================

CREATE OR REPLACE TASK PDM_OEE_DB.GOLD.CRITICAL_ALERT_TASK
    WAREHOUSE = COMPUTE_WH
    AFTER PDM_OEE_DB.GOLD.SCORING_TASK
AS
CALL PDM_OEE_DB.GOLD.CRITICAL_ALERT_PROC();

-- ============================================================
-- Fleet Summary Task (daily digest)
-- ============================================================

CREATE OR REPLACE TASK PDM_OEE_DB.GOLD.FLEET_SUMMARY_TASK
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = 'USING CRON 0 6 * * * America/Los_Angeles'
AS
CALL PDM_OEE_DB.GOLD.FLEET_SUMMARY_PROC();

-- ============================================================
-- Retrain Candidacy Task (drift detection)
-- ============================================================

CREATE OR REPLACE TASK PDM_OEE_DB.GOLD.RETRAIN_CANDIDACY_TASK
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = 'USING CRON 0 0/6 * * * America/Los_Angeles'
AS
CALL PDM_OEE_DB.GOLD.RETRAIN_CANDIDACY_PROC();

-- ============================================================
-- Replay Task (hourly data drip)
-- ============================================================

CREATE OR REPLACE TASK PDM_OEE_DB.RAW.REPLAY_TASK
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = '60 MINUTE'
    COMMENT = 'Drips one hour of Day 11 replay data into SENSOR_STREAM per execution'
AS
CALL PDM_OEE_DB.RAW.REPLAY_BATCH_PROC();

-- ============================================================
-- Resume tasks (run manually when ready)
-- Note: Resume child tasks BEFORE parent tasks
-- ============================================================
-- ALTER TASK PDM_OEE_DB.GOLD.CRITICAL_ALERT_TASK RESUME;
-- ALTER TASK PDM_OEE_DB.GOLD.FLEET_SUMMARY_TASK RESUME;
-- ALTER TASK PDM_OEE_DB.GOLD.RETRAIN_CANDIDACY_TASK RESUME;
-- ALTER TASK PDM_OEE_DB.RAW.REPLAY_TASK RESUME;
-- ALTER TASK PDM_OEE_DB.GOLD.SCORING_TASK RESUME;  -- parent last
