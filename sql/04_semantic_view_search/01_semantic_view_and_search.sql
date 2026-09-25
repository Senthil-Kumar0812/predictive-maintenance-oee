/*
  Phase 4: Semantic View, Cortex Search Service, Search Corpus
*/

-- ============================================================
-- Search Corpus (source for Cortex Search)
-- ============================================================

CREATE OR REPLACE TABLE PDM_OEE_DB.GOLD.SEARCH_CORPUS (
    DOC_ID VARCHAR,
    ASSET_ID VARCHAR(12),
    SUBSYSTEM VARCHAR(20),
    DOC_TYPE VARCHAR(20),
    TITLE VARCHAR,
    SEARCH_TEXT VARCHAR(5000)
);

-- ============================================================
-- Cortex Search Service
-- ============================================================

CREATE OR REPLACE CORTEX SEARCH SERVICE PDM_OEE_DB.GOLD.MAINTENANCE_SEARCH_SVC
    ON SEARCH_TEXT
    ATTRIBUTES ASSET_ID, SUBSYSTEM, DOC_TYPE, TITLE
    WAREHOUSE = 'COMPUTE_WH'
    TARGET_LAG = '1 hour'
    REFRESH_MODE = INCREMENTAL
AS (SELECT * FROM PDM_OEE_DB.GOLD.SEARCH_CORPUS);

-- ============================================================
-- Semantic View
-- ============================================================

CREATE OR REPLACE SEMANTIC VIEW PDM_OEE_DB.GOLD.PDM_OEE_COMMAND_CENTER
    TABLES (
        OEE AS PDM_OEE_DB.GOLD.GOLD_OEE_METRICS PRIMARY KEY (ASSET_ID, SHIFT_DATE, SHIFT),
        FM AS PDM_OEE_DB.GOLD.FLEET_METRICS PRIMARY KEY (WO_ID),
        ALERTS AS PDM_OEE_DB.GOLD.ALERT_QUEUE PRIMARY KEY (ALERT_ID),
        ASSETS AS PDM_OEE_DB.RAW.ASSET_MASTER PRIMARY KEY (ASSET_ID)
    )
    RELATIONSHIPS (
        OEE_TO_ASSETS AS OEE(ASSET_ID) REFERENCES ASSETS(ASSET_ID),
        FM_TO_ASSETS AS FM(ASSET_ID) REFERENCES ASSETS(ASSET_ID),
        ALERTS_TO_ASSETS AS ALERTS(ASSET_ID) REFERENCES ASSETS(ASSET_ID)
    )
    DIMENSIONS (
        OEE.SHIFT_DATE AS SHIFT_DATE COMMENT 'Production shift date',
        OEE.SHIFT AS SHIFT COMMENT 'Shift period' SAMPLE_VALUES ('DAY', 'NIGHT') IS_ENUM,
        FM.FAILURE_CODE_DIM AS FAILURE_CODE COMMENT 'Failure type from ERP',
        FM.SEVERITY_DIM AS SEVERITY COMMENT 'Failure severity' SAMPLE_VALUES ('LOW', 'MEDIUM', 'HIGH') IS_ENUM,
        ALERTS.STATUS_DIM AS STATUS COMMENT 'Alert tier' SAMPLE_VALUES ('AUTO_ELIGIBLE', 'NEEDS_REVIEW', 'LOGGED_ONLY') IS_ENUM,
        ALERTS.DRIVING_SIGNAL_DIM AS DRIVING_SIGNAL COMMENT 'Primary anomaly signal' SAMPLE_VALUES ('VIBRATION', 'TEMPERATURE') IS_ENUM,
        ASSETS.WIND_FARM AS WIND_FARM COMMENT 'Wind farm name',
        ASSETS.TURBINE_ID AS TURBINE_ID COMMENT 'Turbine identifier',
        ASSETS.SUBSYSTEM AS SUBSYSTEM COMMENT 'Subsystem type' SAMPLE_VALUES ('GEARBOX', 'MAIN_BEARING', 'GENERATOR', 'PITCH_SYSTEM', 'YAW_SYSTEM') IS_ENUM,
        ASSETS.ASSET_CRITICALITY AS ASSET_CRITICALITY COMMENT 'Asset criticality' SAMPLE_VALUES ('HIGH', 'MEDIUM', 'LOW') IS_ENUM,
        ASSETS.ASSET_ID_DIM AS ASSET_ID COMMENT 'Unique asset identifier'
    )
    METRICS (
        OEE.AVG_OEE AS AVG(oee.OEE) COMMENT 'Average OEE (0-1)',
        OEE.AVG_AVAILABILITY AS AVG(oee.AVAILABILITY) COMMENT 'Average availability',
        OEE.AVG_PERFORMANCE AS AVG(oee.PERFORMANCE) COMMENT 'Average performance',
        OEE.AVG_QUALITY AS AVG(oee.QUALITY) COMMENT 'Average quality',
        OEE.TOTAL_SHIFTS AS COUNT(oee.SHIFT) COMMENT 'Number of shifts',
        FM.TOTAL_FAILURES AS COUNT(fm.WO_ID) COMMENT 'Number of failures',
        FM.TOTAL_FAILURE_COST AS SUM(fm.FAILURE_COST) COMMENT 'Total failure cost ($)',
        FM.AVG_REPAIR_HOURS AS AVG(fm.REPAIR_HOURS) COMMENT 'Average repair time (MTTR)',
        FM.TOTAL_DOWNTIME AS SUM(fm.FAILURE_DOWNTIME_HOURS) COMMENT 'Total downtime hours',
        ALERTS.TOTAL_ALERTS AS COUNT(alerts.ALERT_ID) COMMENT 'Active alert count',
        ALERTS.AVG_CONFIDENCE AS AVG(alerts.CONFIDENCE) COMMENT 'Average confidence',
        ALERTS.CRITICAL_COUNT AS COUNT_IF(alerts.STATUS = 'AUTO_ELIGIBLE') COMMENT 'Critical alert count',
        ALERTS.AVG_PRIORITY AS AVG(alerts.PRIORITY) COMMENT 'Average alert priority'
    )
    COMMENT = 'Predictive Maintenance & OEE Command Center';
