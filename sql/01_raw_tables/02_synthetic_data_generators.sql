/*
  Synthetic Data Generation Procedures
  - GENERATE_SENSOR_DATA: 768K sensor readings (10 days, 50 assets)
  - GENERATE_REPLAY_BUFFER: 24K Day 11 replay rows (hourly batches)
  
  Run these after creating RAW tables to populate the system.
*/

-- ============================================================
-- GENERATE_SENSOR_DATA
-- Creates 10 days of sensor data with 18 injected failure events:
--   13 scoring-window failures (detectable by ML)
--   3 training-window-only failures (repaired before scoring)
--   2 false positives (tent function, self-recovering)
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.RAW.GENERATE_SENSOR_DATA()
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS CALLER
AS
$$
import random, math
from datetime import datetime, timedelta

def run(session):
    random.seed(42)

    # Subsystem baselines: (vib_mu, vib_sig, temp_mu, temp_sig, rpm_mu, rpm_sig)
    BASELINES = {
        'GBX': (3.5, 0.5, 55, 3, 1750, 15),
        'MBR': (2.8, 0.4, 50, 2.5, 1750, 15),
        'GEN': (2.0, 0.3, 65, 3, 1800, 10),
        'PIT': (1.5, 0.3, 40, 2, 120, 5),
        'YAW': (1.8, 0.3, 45, 2, 8, 1),
    }

    # 18 failure events: (asset_id, failure_start_day, duration_days, vib_mult, temp_mult, is_false_positive)
    FAILURES = [
        # --- 13 scoring-window failures (degradation visible in Days 8-10) ---
        ('WF01-T01-GEN', 6, 3, 2.5, 1.4, False),   # GENERATOR_OVERTEMP
        ('WF01-T01-PIT', 7, 3, 2.0, 1.3, False),   # HYDRAULIC_LEAK
        ('WF01-T03-PIT', 6, 3, 2.2, 1.3, False),   # BLADE_ANGLE_DRIFT
        ('WF02-T01-YAW', 7, 3, 2.8, 1.5, False),   # YAW_MOTOR_BURNOUT
        ('WF02-T02-PIT', 7, 3, 2.3, 1.4, False),   # PITCH_ACTUATOR_WEAR
        ('WF02-T03-MBR', 6, 3, 2.6, 1.5, False),   # BEARING_CAGE_FAILURE
        ('WF03-T01-YAW', 7, 3, 2.4, 1.4, False),   # YAW_BEARING_SEIZURE
        ('WF03-T02-GEN', 6, 3, 2.3, 1.3, False),   # BRUSH_WEAR
        ('WF03-T02-YAW', 6, 3, 2.7, 1.5, False),   # YAW_GEAR_SLIPPAGE
        ('WF03-T03-GBX', 6, 3, 2.5, 1.4, False),   # SEAL_LEAK
        # 3 moved from training-window to scoring window
        ('WF01-T02-GBX', 7, 3, 2.4, 1.4, False),   # GEAR_TOOTH_WEAR
        ('WF01-T04-GBX', 7, 3, 2.6, 1.5, False),   # SHAFT_MISALIGNMENT
        ('WF03-T01-MBR', 7, 3, 2.3, 1.3, False),   # LUBRICATION_FAILURE
        # --- 3 training-window-only failures (repaired before scoring) ---
        ('WF01-T03-MBR', 3, 3, 2.5, 1.4, False),   # BEARING_OVERHEAT
        ('WF02-T01-GBX', 4, 3, 2.4, 1.4, False),   # OIL_CONTAMINATION
        ('WF02-T02-GEN', 4, 3, 2.2, 1.3, False),   # WINDING_INSULATION
        # --- 2 false positives (tent function, no work order) ---
        ('WF01-T04-MBR', 5, 2, 1.5, 1.15, True),   # Near-miss, self-recovers
        ('WF02-T03-GEN', 5, 2, 1.6, 1.2, True),    # Near-miss, self-recovers
    ]

    failure_map = {}
    for (aid, start_day, dur, vm, tm, is_fp) in FAILURES:
        start_min = (start_day - 1) * 1440
        end_min = start_min + dur * 1440
        failure_map[aid] = (start_min, end_min, vm, tm, is_fp)

    assets = session.sql("SELECT ASSET_ID, SUBSYSTEM_CODE FROM PDM_OEE_DB.RAW.ASSET_MASTER ORDER BY ASSET_ID").collect()

    TOTAL_MINUTES = 10 * 1440  # 10 days
    BASE_TS = datetime(2026, 1, 1)
    BATCH_SIZE = 50000
    reading_id = 0
    batch = []
    total_inserted = 0

    for row in assets:
        aid = row['ASSET_ID']
        code = row['SUBSYSTEM_CODE']
        vib_mu, vib_sig, temp_mu, temp_sig, rpm_mu, rpm_sig = BASELINES[code]

        has_failure = aid in failure_map
        if has_failure:
            f_start, f_end, vib_mult, temp_mult, is_fp = failure_map[aid]

        for minute in range(TOTAL_MINUTES):
            reading_id += 1
            ts = BASE_TS + timedelta(minutes=minute)

            # Base sensor values
            vib = max(0.1, random.gauss(vib_mu, vib_sig))
            temp = max(10, random.gauss(temp_mu, temp_sig))
            rpm = max(0, random.gauss(rpm_mu, rpm_sig))

            # Apply failure degradation
            if has_failure and f_start <= minute < f_end:
                duration = f_end - f_start
                progress = (minute - f_start) / duration

                if is_fp:
                    # Tent function: ramp up then down
                    if progress < 0.5:
                        scale = progress * 2
                    else:
                        scale = (1 - progress) * 2
                    vib = max(0.1, random.gauss(vib_mu * (1 + (vib_mult - 1) * scale), vib_sig * 1.2))
                    temp = max(10, random.gauss(temp_mu * (1 + (temp_mult - 1) * scale), temp_sig * 1.2))
                else:
                    # Quadratic degradation curve
                    vib = max(0.1, random.gauss(vib_mu * (1 + (vib_mult - 1) * progress ** 2), vib_sig * (1 + progress)))
                    temp = max(10, random.gauss(temp_mu * (1 + (temp_mult - 1) * progress ** 2), temp_sig * (1 + progress)))

            batch.append((reading_id, aid, ts.strftime('%Y-%m-%d %H:%M:%S'), round(vib, 4), round(temp, 2), round(rpm, 2)))

            if len(batch) >= BATCH_SIZE:
                df = session.create_dataframe(batch, schema=['READING_ID','ASSET_ID','TS','VIBRATION_MM_S','TEMP_C','RPM'])
                df.write.mode('append').save_as_table('PDM_OEE_DB.RAW.SENSOR_STREAM')
                total_inserted += len(batch)
                batch = []

    if batch:
        df = session.create_dataframe(batch, schema=['READING_ID','ASSET_ID','TS','VIBRATION_MM_S','TEMP_C','RPM'])
        df.write.mode('append').save_as_table('PDM_OEE_DB.RAW.SENSOR_STREAM')
        total_inserted += len(batch)

    return f'Generated {total_inserted} sensor readings for {len(assets)} assets'
$$;

-- ============================================================
-- GENERATE_REPLAY_BUFFER
-- Creates 24 hours of Day 11 data for simulated streaming.
-- WF02-T03-GBX gets quadratic degradation (oil contamination).
-- ============================================================

CREATE OR REPLACE PROCEDURE PDM_OEE_DB.RAW.GENERATE_REPLAY_BUFFER()
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS CALLER
AS
$$
import random, math
from datetime import datetime, timedelta

def run(session):
    random.seed(99)

    BASELINES = {
        'GBX': (3.5, 0.5, 55, 3, 1750, 15),
        'MBR': (2.8, 0.4, 50, 2.5, 1750, 15),
        'GEN': (2.0, 0.3, 65, 3, 1800, 10),
        'PIT': (1.5, 0.3, 40, 2, 120, 5),
        'YAW': (1.8, 0.3, 45, 2, 8, 1),
    }

    # WF02-T03-GBX develops oil contamination on Day 11
    DEGRADE_ASSET = 'WF02-T03-GBX'
    VIB_MULT = 2.8
    TEMP_MULT = 1.5

    assets = session.sql("SELECT ASSET_ID, SUBSYSTEM_CODE FROM PDM_OEE_DB.RAW.ASSET_MASTER ORDER BY ASSET_ID").collect()

    BASE_TS = datetime(2026, 1, 11)
    TOTAL_MINUTES = 1440  # 24 hours
    BATCH_SIZE = 50000
    max_reading = session.sql("SELECT COALESCE(MAX(READING_ID), 0) FROM PDM_OEE_DB.RAW.SENSOR_STREAM").collect()[0][0]
    reading_id = max_reading
    batch = []
    total = 0

    for row in assets:
        aid = row['ASSET_ID']
        code = row['SUBSYSTEM_CODE']
        vib_mu, vib_sig, temp_mu, temp_sig, rpm_mu, rpm_sig = BASELINES[code]

        for minute in range(TOTAL_MINUTES):
            reading_id += 1
            ts = BASE_TS + timedelta(minutes=minute)
            hour = minute / 60.0

            vib = max(0.1, random.gauss(vib_mu, vib_sig))
            temp = max(10, random.gauss(temp_mu, temp_sig))
            rpm = max(0, random.gauss(rpm_mu, rpm_sig))

            # Apply degradation to WF02-T03-GBX
            if aid == DEGRADE_ASSET:
                progress = min(1.0, hour / 24.0)
                vib = max(0.1, random.gauss(vib_mu * (1 + (VIB_MULT - 1) * progress ** 2), vib_sig * (1 + progress)))
                temp = max(10, random.gauss(temp_mu * (1 + (TEMP_MULT - 1) * progress ** 2), temp_sig * (1 + progress)))

            batch.append((reading_id, aid, ts.strftime('%Y-%m-%d %H:%M:%S'), round(vib, 4), round(temp, 2), round(rpm, 2), int(hour)))

            if len(batch) >= BATCH_SIZE:
                df = session.create_dataframe(batch, schema=['READING_ID','ASSET_ID','TS','VIBRATION_MM_S','TEMP_C','RPM','REPLAY_HOUR'])
                df.write.mode('append').save_as_table('PDM_OEE_DB.RAW.REPLAY_BUFFER')
                total += len(batch)
                batch = []

    if batch:
        df = session.create_dataframe(batch, schema=['READING_ID','ASSET_ID','TS','VIBRATION_MM_S','TEMP_C','RPM','REPLAY_HOUR'])
        df.write.mode('append').save_as_table('PDM_OEE_DB.RAW.REPLAY_BUFFER')
        total += len(batch)

    return f'Generated {total} replay rows for {len(assets)} assets (Day 11, 24h). WF02-T03-GBX degrading.'
$$;

-- ============================================================
-- To populate data from scratch, run in order:
-- ============================================================
-- CALL PDM_OEE_DB.RAW.GENERATE_SENSOR_DATA();     -- ~2 min, 768K rows
-- CALL PDM_OEE_DB.RAW.GENERATE_REPLAY_BUFFER();   -- ~30 sec, 24K rows
