/*
  Phase 5: Agent & Action Procedures
  - CREATE_WORK_ORDER (with 0.85 confidence guardrail)
  - NOTIFY_CRITICAL_ALERT (HTML email with history)
  - CRITICAL_ALERT_PROC (batch notification for fleet)
  - FLEET_SUMMARY_PROC (daily digest)
  - RETRAIN_CANDIDACY_PROC (model drift detection)
  - REPLAY_BATCH_PROC (hourly data drip)
  - Cortex Agent definition
*/

-- ============================================================
-- CREATE_WORK_ORDER
-- Guardrail: confidence >= 0.85 required (or explicit override)
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.GOLD.CREATE_WORK_ORDER(
    P_ASSET_ID VARCHAR, P_CONFIDENCE FLOAT, P_DESCRIPTION VARCHAR, P_OVERRIDE BOOLEAN DEFAULT FALSE
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
BEGIN
    IF (:P_CONFIDENCE < 0.85 AND :P_OVERRIDE = FALSE) THEN
        LET refuse_msg VARCHAR := 'Confidence ' || :P_CONFIDENCE || ' below 0.85 threshold. Override not set.';
        INSERT INTO PDM_OEE_DB.RAW.AGENT_ACTION_LOG (ACTION_TYPE, ASSET_ID, CONFIDENCE, DETAILS)
        VALUES ('WO_REFUSED', :P_ASSET_ID, :P_CONFIDENCE, :refuse_msg);
        RETURN 'REFUSED: ' || :refuse_msg;
    END IF;

    LET wo_id VARCHAR := 'WO-AGT-' || LEFT(REPLACE(UUID_STRING(), '-', ''), 12);
    INSERT INTO PDM_OEE_DB.RAW.ERP_WORKORDER (WO_ID, ASSET_ID, TYPE, OPENED_TS, FAILURE_CODE)
    VALUES (:wo_id, :P_ASSET_ID, 'CORRECTIVE', CURRENT_TIMESTAMP(), :P_DESCRIPTION);

    LET log_msg VARCHAR := 'Work order ' || :wo_id || ' created. Override=' || :P_OVERRIDE::VARCHAR;
    INSERT INTO PDM_OEE_DB.RAW.AGENT_ACTION_LOG (ACTION_TYPE, ASSET_ID, CONFIDENCE, DETAILS)
    VALUES ('WO_CREATED', :P_ASSET_ID, :P_CONFIDENCE, :log_msg);

    RETURN 'SUCCESS: Work order ' || :wo_id || ' created for ' || :P_ASSET_ID || ' (confidence=' || :P_CONFIDENCE || ')';
END;

-- ============================================================
-- NOTIFY_CRITICAL_ALERT
-- Professional HTML email via SYSTEM$SEND_EMAIL
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.GOLD.NOTIFY_CRITICAL_ALERT(
    P_ASSET_ID VARCHAR, P_CONFIDENCE FLOAT, P_MESSAGE VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
BEGIN
    LET v_subsystem VARCHAR := (SELECT SUBSYSTEM FROM PDM_OEE_DB.RAW.ASSET_MASTER WHERE ASSET_ID = :P_ASSET_ID);
    LET v_wind_farm VARCHAR := (SELECT WIND_FARM FROM PDM_OEE_DB.RAW.ASSET_MASTER WHERE ASSET_ID = :P_ASSET_ID);
    LET v_turbine VARCHAR := (SELECT TURBINE_ID FROM PDM_OEE_DB.RAW.ASSET_MASTER WHERE ASSET_ID = :P_ASSET_ID);
    LET v_criticality VARCHAR := (SELECT ASSET_CRITICALITY FROM PDM_OEE_DB.RAW.ASSET_MASTER WHERE ASSET_ID = :P_ASSET_ID);
    LET v_priority INT := (SELECT PRIORITY FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE ASSET_ID = :P_ASSET_ID);
    LET v_signal VARCHAR := (SELECT DRIVING_SIGNAL FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE ASSET_ID = :P_ASSET_ID);
    LET v_status VARCHAR := (SELECT STATUS FROM PDM_OEE_DB.GOLD.ALERT_QUEUE WHERE ASSET_ID = :P_ASSET_ID);
    LET v_wo_id VARCHAR := (
        SELECT WO_ID FROM PDM_OEE_DB.RAW.ERP_WORKORDER
        WHERE ASSET_ID = :P_ASSET_ID AND WO_ID LIKE 'WO-AGT%'
        ORDER BY OPENED_TS DESC LIMIT 1
    );
    LET v_failures INT := (SELECT COALESCE(TOTAL_FAILURES, 0) FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE WHERE ASSET_ID = :P_ASSET_ID);
    LET v_cost INT := (SELECT COALESCE(TOTAL_FAILURE_COST, 0) FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE WHERE ASSET_ID = :P_ASSET_ID);
    LET v_mttr VARCHAR := (SELECT COALESCE(ROUND(AVG_REPAIR_HOURS, 1)::VARCHAR, 'N/A') FROM PDM_OEE_DB.GOLD.COMMAND_CENTER_WIDE WHERE ASSET_ID = :P_ASSET_ID);

    -- Maintenance notes: asset-specific first, fleet-fallback second
    LET v_notes_html VARCHAR := '';
    LET v_asset_notes VARCHAR := (
        SELECT LISTAGG('<li>' || LEFT(NOTE_TEXT, 120) || '</li>', '') WITHIN GROUP (ORDER BY TS DESC)
        FROM (SELECT NOTE_TEXT, TS FROM PDM_OEE_DB.BRONZE.BRONZE_MAINTENANCE_LOG WHERE ASSET_ID = :P_ASSET_ID ORDER BY TS DESC LIMIT 2)
    );
    IF (:v_asset_notes IS NOT NULL AND :v_asset_notes != '') THEN
        v_notes_html := '<strong>Maintenance Notes (' || :P_ASSET_ID || '):</strong><ul style="margin:4px 0 0 16px;padding:0;">' || :v_asset_notes || '</ul>';
    ELSE
        LET v_fleet_notes VARCHAR := (
            SELECT LISTAGG('<li>' || LEFT(ml.NOTE_TEXT, 120) || '</li>', '') WITHIN GROUP (ORDER BY ml.TS DESC)
            FROM (
                SELECT ml.NOTE_TEXT, ml.TS
                FROM PDM_OEE_DB.BRONZE.BRONZE_MAINTENANCE_LOG ml
                JOIN PDM_OEE_DB.RAW.ASSET_MASTER am ON ml.ASSET_ID = am.ASSET_ID
                WHERE am.SUBSYSTEM = :v_subsystem ORDER BY ml.TS DESC LIMIT 2
            ) ml
        );
        IF (:v_fleet_notes IS NOT NULL AND :v_fleet_notes != '') THEN
            v_notes_html := '<strong>Maintenance Notes</strong> <span style="color:#888;font-size:12px;">(from fleet ' || :v_subsystem || ' history)</span>:<ul style="margin:4px 0 0 16px;padding:0;">' || :v_fleet_notes || '</ul>';
        END IF;
    END IF;

    LET v_pct VARCHAR := ROUND(:P_CONFIDENCE * 100, 1)::VARCHAR;
    LET v_ts VARCHAR := TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS UTC');
    LET v_subject VARCHAR := '[CRITICAL] Turbine Alert - ' || :P_ASSET_ID || ' (Priority ' || COALESCE(:v_priority::VARCHAR, 'N/A') || ')';

    -- Build HTML body (abbreviated for readability — see deployed version for full template)
    LET v_body VARCHAR := '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;">'
        || '<div style="background:#c0392b;color:#fff;padding:14px 20px;border-radius:6px 6px 0 0;">'
        || '<h2 style="margin:0;font-size:18px;">CRITICAL ANOMALY ALERT</h2></div>'
        || '<div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 6px 6px;">'
        || '<p><strong>Asset:</strong> ' || :P_ASSET_ID || ' (' || COALESCE(:v_subsystem, 'N/A') || ')</p>'
        || '<p><strong>Confidence:</strong> ' || :v_pct || '% | <strong>Signal:</strong> ' || COALESCE(:v_signal, 'N/A') || '</p>'
        || '<p><strong>Work Order:</strong> ' || COALESCE(:v_wo_id, 'Pending') || '</p>'
        || '<p style="margin:18px 0 0;padding:10px;background:#fef9e7;border-left:4px solid #f39c12;font-size:12px;color:#7d6608;">'
        || 'Auto-generated by PDM OEE Command Center.</p></div></div>';

    INSERT INTO PDM_OEE_DB.RAW.AGENT_ACTION_LOG (ACTION_TYPE, ASSET_ID, CONFIDENCE, DETAILS)
    VALUES ('NOTIFICATION_SENT', :P_ASSET_ID, :P_CONFIDENCE, :P_MESSAGE);

    -- Replace 'YOUR_NOTIFICATION_INTEGRATION' and 'recipient@example.com' with your values
    CALL SYSTEM$SEND_EMAIL(
        'YOUR_NOTIFICATION_INTEGRATION',
        'recipient@example.com',
        :v_subject,
        :v_body,
        'text/html'
    );

    RETURN 'SUCCESS: Critical alert notification sent for ' || :P_ASSET_ID;
EXCEPTION
    WHEN OTHER THEN
        INSERT INTO PDM_OEE_DB.RAW.AGENT_ACTION_LOG (ACTION_TYPE, ASSET_ID, CONFIDENCE, DETAILS)
        VALUES ('NOTIFICATION_FAILED', :P_ASSET_ID, :P_CONFIDENCE, 'Email failed: ' || SQLERRM);
        RETURN 'WARNING: Alert logged but email delivery failed: ' || SQLERRM;
END;

-- ============================================================
-- REPLAY_BATCH_PROC (hourly data drip)
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.RAW.REPLAY_BATCH_PROC()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
BEGIN
    LET next_hour INT := (SELECT MIN(REPLAY_HOUR) FROM PDM_OEE_DB.RAW.REPLAY_BUFFER);
    IF (:next_hour IS NULL) THEN
        RETURN 'REPLAY_COMPLETE: No more data in REPLAY_BUFFER.';
    END IF;
    LET batch_rows INT := (SELECT COUNT(*) FROM PDM_OEE_DB.RAW.REPLAY_BUFFER WHERE REPLAY_HOUR = :next_hour);

    INSERT INTO PDM_OEE_DB.RAW.SENSOR_STREAM (READING_ID, ASSET_ID, TS, VIBRATION_MM_S, TEMP_C, RPM)
    SELECT READING_ID, ASSET_ID, TS, VIBRATION_MM_S, TEMP_C, RPM
    FROM PDM_OEE_DB.RAW.REPLAY_BUFFER WHERE REPLAY_HOUR = :next_hour;

    DELETE FROM PDM_OEE_DB.RAW.REPLAY_BUFFER WHERE REPLAY_HOUR = :next_hour;
    LET remaining INT := (SELECT COUNT(DISTINCT REPLAY_HOUR) FROM PDM_OEE_DB.RAW.REPLAY_BUFFER);
    RETURN 'Replayed hour ' || :next_hour || ' (' || :batch_rows || ' rows). ' || :remaining || ' hours remaining.';
END;

-- ============================================================
-- Cortex Agent
-- ============================================================

CREATE OR REPLACE AGENT PDM_OEE_DB.GOLD.PDM_COMMAND_CENTER_AGENT
    COMMENT = 'Wind turbine fleet maintenance advisor'
FROM SPECIFICATION $$
models:
  orchestration: "auto"
instructions:
  response: >
    You are a wind turbine fleet maintenance advisor. Always check confidence
    scores before recommending work orders. For confidence >= 0.85, you may
    auto-create work orders. For 0.50-0.85, recommend but ask for confirmation.
    Below 0.50, advise monitoring only.
  orchestration: >
    Use FleetAnalytics for OEE metrics, alert data, and failure statistics.
    Use MaintenanceSearch for maintenance history and equipment manuals.
    Use CREATE_WORK_ORDER only when confidence >= 0.85 or user explicitly
    overrides. Use NOTIFY_CRITICAL_ALERT for urgent notifications.
tools:
  - tool_spec:
      type: "cortex_analyst_text_to_sql"
      name: "FleetAnalytics"
      description: "Queries OEE metrics, alert queue, fleet health, and failure statistics"
  - tool_spec:
      type: "cortex_search"
      name: "MaintenanceSearch"
      description: "Searches maintenance logs, technician notes, and equipment manuals"
  - tool_spec:
      type: "generic"
      name: "CREATE_WORK_ORDER"
      description: "Creates a corrective work order. Only call when confidence >= 0.85 or user explicitly overrides."
      input_schema:
        type: "object"
        properties:
          P_ASSET_ID: { type: "string", description: "Asset ID" }
          P_CONFIDENCE: { type: "number", description: "Confidence score (0-1)" }
          P_DESCRIPTION: { type: "string", description: "Failure description" }
          P_OVERRIDE: { type: "boolean", description: "Override threshold" }
        required: ["P_ASSET_ID", "P_CONFIDENCE", "P_DESCRIPTION"]
  - tool_spec:
      type: "generic"
      name: "NOTIFY_CRITICAL_ALERT"
      description: "Sends critical alert email notification"
      input_schema:
        type: "object"
        properties:
          P_ASSET_ID: { type: "string", description: "Asset ID" }
          P_CONFIDENCE: { type: "number", description: "Confidence score" }
          P_MESSAGE: { type: "string", description: "Alert message" }
        required: ["P_ASSET_ID", "P_CONFIDENCE", "P_MESSAGE"]
tool_resources:
  FleetAnalytics:
    semantic_view: "PDM_OEE_DB.GOLD.PDM_OEE_COMMAND_CENTER"
    execution_environment:
      type: "warehouse"
      warehouse: "COMPUTE_WH"
  MaintenanceSearch:
    search_service: "PDM_OEE_DB.GOLD.MAINTENANCE_SEARCH_SVC"
    max_results: "10"
  CREATE_WORK_ORDER:
    type: "procedure"
    procedure: "PDM_OEE_DB.GOLD.CREATE_WORK_ORDER"
    execution_environment:
      type: "warehouse"
      warehouse: "COMPUTE_WH"
  NOTIFY_CRITICAL_ALERT:
    type: "procedure"
    procedure: "PDM_OEE_DB.GOLD.NOTIFY_CRITICAL_ALERT"
    execution_environment:
      type: "warehouse"
      warehouse: "COMPUTE_WH"
$$;
