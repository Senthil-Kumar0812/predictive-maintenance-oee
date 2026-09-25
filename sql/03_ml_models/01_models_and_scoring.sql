/*
  Phase 3: ML Models & Scoring
  - Scoring views (input to ANOMALY_DETECTION)
  - Model training (vibration + temperature)
  - Scoring procedure with Binomial threshold (k=13)
  - ALERT_QUEUE materialization
*/

-- ============================================================
-- Scoring Views (input to ML models)
-- ============================================================

CREATE OR REPLACE VIEW PDM_OEE_DB.GOLD.V_ANOMALY_SCORE_VIB AS
SELECT ASSET_ID AS SERIES, BUCKET_TS AS TS, VIB_BUCKET_AVG AS Y
FROM PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H
WHERE BUCKET_TS >= '2026-01-08';

CREATE OR REPLACE VIEW PDM_OEE_DB.GOLD.V_ANOMALY_SCORE_TEMP AS
SELECT ASSET_ID AS SERIES, BUCKET_TS AS TS, TEMP_BUCKET_AVG AS Y
FROM PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H
WHERE BUCKET_TS >= '2026-01-08';

-- ============================================================
-- ML Model Training
-- Trained on Days 1-10 (normal operations baseline)
-- ============================================================

-- Training views (Days 1-10 only)
CREATE OR REPLACE VIEW PDM_OEE_DB.GOLD.V_ANOMALY_TRAIN_VIB AS
SELECT ASSET_ID AS SERIES, BUCKET_TS AS TS, VIB_BUCKET_AVG AS Y
FROM PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H
WHERE BUCKET_TS < '2026-01-11';

CREATE OR REPLACE VIEW PDM_OEE_DB.GOLD.V_ANOMALY_TRAIN_TEMP AS
SELECT ASSET_ID AS SERIES, BUCKET_TS AS TS, TEMP_BUCKET_AVG AS Y
FROM PDM_OEE_DB.SILVER.SILVER_SENSOR_STATS_24H
WHERE BUCKET_TS < '2026-01-11';

-- Train vibration anomaly model
CREATE OR REPLACE SNOWFLAKE.ML.ANOMALY_DETECTION PDM_OEE_DB.GOLD.VIB_ANOMALY_MODEL(
    INPUT_DATA => TABLE(PDM_OEE_DB.GOLD.V_ANOMALY_TRAIN_VIB),
    SERIES_COLNAME => 'SERIES',
    TIMESTAMP_COLNAME => 'TS',
    TARGET_COLNAME => 'Y',
    LABEL_COLNAME => ''
);

-- Train temperature anomaly model
CREATE OR REPLACE SNOWFLAKE.ML.ANOMALY_DETECTION PDM_OEE_DB.GOLD.TEMP_ANOMALY_MODEL(
    INPUT_DATA => TABLE(PDM_OEE_DB.GOLD.V_ANOMALY_TRAIN_TEMP),
    SERIES_COLNAME => 'SERIES',
    TIMESTAMP_COLNAME => 'TS',
    TARGET_COLNAME => 'Y',
    LABEL_COLNAME => ''
);

-- ============================================================
-- Scoring Procedure
-- Threshold: k=13 from Binomial(576, 0.01) mean + 3σ
-- Confidence: sqrt((anomaly_count - 13) / 50), capped at 1.0
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.GOLD.SCORING_PROC()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
BEGIN
    -- Score vibration anomalies
    CREATE OR REPLACE TABLE PDM_OEE_DB.GOLD.VIB_ANOMALY_RESULTS AS
    SELECT * FROM TABLE(PDM_OEE_DB.GOLD.VIB_ANOMALY_MODEL!DETECT_ANOMALIES(
        INPUT_DATA => TABLE(PDM_OEE_DB.GOLD.V_ANOMALY_SCORE_VIB),
        SERIES_COLNAME => 'SERIES', TIMESTAMP_COLNAME => 'TS', TARGET_COLNAME => 'Y',
        CONFIG_OBJECT => {'prediction_interval': 0.99}
    ));

    -- Score temperature anomalies
    CREATE OR REPLACE TABLE PDM_OEE_DB.GOLD.TEMP_ANOMALY_RESULTS AS
    SELECT * FROM TABLE(PDM_OEE_DB.GOLD.TEMP_ANOMALY_MODEL!DETECT_ANOMALIES(
        INPUT_DATA => TABLE(PDM_OEE_DB.GOLD.V_ANOMALY_SCORE_TEMP),
        SERIES_COLNAME => 'SERIES', TIMESTAMP_COLNAME => 'TS', TARGET_COLNAME => 'Y',
        CONFIG_OBJECT => {'prediction_interval': 0.99}
    ));

    -- Materialize ALERT_QUEUE with combined scoring
    CREATE OR REPLACE TABLE PDM_OEE_DB.GOLD.ALERT_QUEUE AS
    WITH anomaly_counts AS (
        SELECT v.SERIES AS ASSET_ID, COUNT_IF(v.IS_ANOMALY) AS VIB_ANOM,
            MIN(CASE WHEN v.IS_ANOMALY THEN v.TS END) AS VIB_FIRST_ANOM
        FROM PDM_OEE_DB.GOLD.VIB_ANOMALY_RESULTS v GROUP BY v.SERIES
    ),
    temp_counts AS (
        SELECT t.SERIES AS ASSET_ID, COUNT_IF(t.IS_ANOMALY) AS TEMP_ANOM,
            MIN(CASE WHEN t.IS_ANOMALY THEN t.TS END) AS TEMP_FIRST_ANOM
        FROM PDM_OEE_DB.GOLD.TEMP_ANOMALY_RESULTS t GROUP BY t.SERIES
    ),
    combined AS (
        SELECT a.ASSET_ID, am.ASSET_CRITICALITY, am.SITE_PRIORITY,
            a.VIB_ANOM, t.TEMP_ANOM, a.VIB_ANOM + t.TEMP_ANOM AS TOTAL_ANOMALIES,
            CASE WHEN a.VIB_ANOM >= t.TEMP_ANOM THEN 'VIBRATION' ELSE 'TEMPERATURE' END AS DRIVING_SIGNAL,
            LEAST(COALESCE(a.VIB_FIRST_ANOM, t.TEMP_FIRST_ANOM),
                  COALESCE(t.TEMP_FIRST_ANOM, a.VIB_FIRST_ANOM)) AS FIRST_ANOM_TS
        FROM anomaly_counts a
        JOIN temp_counts t ON a.ASSET_ID = t.ASSET_ID
        JOIN PDM_OEE_DB.RAW.ASSET_MASTER am ON a.ASSET_ID = am.ASSET_ID
        WHERE a.VIB_ANOM + t.TEMP_ANOM >= 13  -- Binomial threshold
    ),
    with_oee AS (
        SELECT c.*, AVG(o.OEE) AS AVG_OEE FROM combined c
        LEFT JOIN PDM_OEE_DB.GOLD.GOLD_OEE_METRICS o ON c.ASSET_ID = o.ASSET_ID
        GROUP BY c.ASSET_ID, c.ASSET_CRITICALITY, c.SITE_PRIORITY,
                 c.VIB_ANOM, c.TEMP_ANOM, c.TOTAL_ANOMALIES,
                 c.DRIVING_SIGNAL, c.FIRST_ANOM_TS
    )
    SELECT UUID_STRING() AS ALERT_ID, ASSET_ID,
        DATEADD('hour', 48, FIRST_ANOM_TS) AS PREDICTED_FAILURE_TS,
        ROUND(LEAST(1.0, POWER((TOTAL_ANOMALIES - 13.0) / 50.0, 0.5)), 4)::FLOAT AS CONFIDENCE,
        DRIVING_SIGNAL,
        ROUND(AVG_OEE, 4)::FLOAT AS CURRENT_OEE,
        ROUND((LEAST(1.0, POWER((TOTAL_ANOMALIES - 13.0) / 50.0, 0.5)) * 0.5 +
               CASE ASSET_CRITICALITY WHEN 'HIGH' THEN 1.0 WHEN 'MEDIUM' THEN 0.6 ELSE 0.3 END * 0.3 +
               (1.0 - (SITE_PRIORITY - 1.0) / 2.0) * 0.2) * 100)::INT AS PRIORITY,
        CASE WHEN LEAST(1.0, POWER((TOTAL_ANOMALIES - 13.0) / 50.0, 0.5)) >= 0.85 THEN 'AUTO_ELIGIBLE'
             WHEN LEAST(1.0, POWER((TOTAL_ANOMALIES - 13.0) / 50.0, 0.5)) >= 0.50 THEN 'NEEDS_REVIEW'
             ELSE 'LOGGED_ONLY' END AS STATUS,
        CURRENT_TIMESTAMP() AS CREATED_AT
    FROM with_oee;

    LET alert_count INT := (SELECT COUNT(*) FROM PDM_OEE_DB.GOLD.ALERT_QUEUE);
    LET critical_count INT := (SELECT COUNT(*) FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE STATUS = 'AUTO_ELIGIBLE');
    RETURN 'Scoring complete: ' || :alert_count || ' alerts (' || :critical_count || ' critical)';
END;

-- ============================================================
-- GOLD Views (consumed by semantic view and Streamlit)
-- ============================================================

-- Note: COMMAND_CENTER_WIDE and FLEET_METRICS are materialized tables
-- populated by the scoring procedure. Their schemas are:

-- COMMAND_CENTER_WIDE: 50 assets with alert status, OEE, failure history
-- FLEET_METRICS: Work order detail with MTBF, MTTR, severity classification
