# How & Why Documentation

This document explains every design decision, why each component was built the way it was, and the reasoning behind the technical choices. It serves as a complete knowledge base for understanding the project.

---

## 1. Why a Medallion Architecture?

**Decision:** RAW → BRONZE → SILVER → GOLD using Dynamic Tables.

**Why not Streams + Tasks?** Dynamic Tables are declarative — you define the desired output, and Snowflake figures out incremental refresh. With Streams + Tasks, you must manually manage change tracking, task dependencies, and error recovery. DTs are self-healing: if data arrives late or is corrected, the pipeline automatically reconciles.

**Why 4 layers?**
- **RAW**: Immutable landing zone. Data arrives here exactly as generated/ingested. Never transformed in place.
- **BRONZE**: Cleansed and deduplicated. Each DT uses `QUALIFY ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` to eliminate exact duplicates. Values are trimmed, uppercased, and rounded for consistency.
- **SILVER**: Feature engineering. This is where the ML-relevant transformations happen — rolling statistics, point-in-time joins, and time-bucketed aggregates.
- **GOLD**: Business-level aggregates consumed by the Streamlit app and semantic view. OEE metrics, alert queue, fleet summary.

---

## 2. Why These Specific Features?

### 1-Hour Rolling Statistics (SILVER_SENSOR_ENRICHED)
```sql
AVG(VIBRATION_MM_S) OVER (PARTITION BY ASSET_ID ORDER BY TS ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
```
**Why 60 readings?** Sensor readings arrive every minute. A 60-reading window = 1 hour. This smooths noise while preserving degradation trends. Shorter windows (15 min) were too noisy; longer windows (4h) masked rapid-onset failures.

### Point-in-Time Work Order Joins
```sql
LAST_VALUE(WO_CLOSED_TS IGNORE NULLS) OVER (
    PARTITION BY ASSET_ID ORDER BY TS, ROW_ORD
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
```
**Why?** The feature `HOURS_SINCE_LAST_WO` tells the model how long since the last repair. Without PIT joins, the model could "see" a work order that was opened *after* the current timestamp — data leakage. The UNION ALL + ROW_ORD technique interleaves sensor readings with work order close events, so `LAST_VALUE(...IGNORE NULLS)` always picks the most recent *prior* repair.

### 15-Minute Buckets (SILVER_SENSOR_STATS_24H)
```sql
TIME_SLICE(s.TS, 15, 'MINUTE', 'START') AS BUCKET_TS
```
**Why 15 minutes?** This matches the Dynamic Table target lag. Each scoring window is one 15-minute bucket, giving the anomaly model 96 windows per day per asset (24h × 4 buckets/hr). This resolution balances granularity with computational cost.

### 24-Hour Sliding Windows
```sql
ROWS BETWEEN 95 PRECEDING AND CURRENT ROW  -- 96 buckets = 24 hours
```
**Why 24 hours?** Wind turbines have diurnal patterns (wind speed, load, temperature). A 24-hour window captures one full cycle, giving the model a stable reference for "normal" behavior at any time of day.

---

## 3. Why This Anomaly Threshold (k=13)?

**The problem:** ANOMALY_DETECTION returns a binary flag per 15-minute bucket. A single anomaly flag could be noise. We need to decide how many flags constitute a real problem.

**The math:**
- Under normal conditions, ~1% of buckets flag as anomalous (p=0.01)
- Each asset has 576 scoring windows (24h × 4 buckets/hr × ~6 feature channels)
- Anomaly counts follow Binomial(n=576, p=0.01)
- Mean = 5.76 flags (normal)
- σ = 2.39
- k = mean + 3σ = 5.76 + 7.17 ≈ 13

**Why 3σ?** This is the 99.87th percentile — only 0.13% chance of exceeding this under normal conditions. This makes the threshold conservative enough to avoid false positives while catching genuine degradation.

**Why not arbitrary (e.g., k=10 or k=20)?** An arbitrary threshold is unexplainable to auditors and operators. The Binomial derivation gives a statistically defensible answer: "This asset has more anomalies than 99.87% of what we'd expect from normal operation."

### Confidence Formula
```
confidence = MIN(1.0, SQRT((anomaly_count - 13) / 50))
```
**Why square root?** It creates a concave curve — confidence rises quickly for the first anomalies above threshold (from 0 to ~0.7), then flattens. An asset with 20 anomalies (just above k=13) gets confidence ~0.37 (LOGGED_ONLY). An asset with 49 anomalies gets ~0.85 (AUTO_ELIGIBLE). An asset with 63+ anomalies maxes at 1.0. This matches operational intuition: the difference between 13 and 20 anomalies is more meaningful than between 60 and 67.

### Alert Classification
| Status | Threshold | Operator Meaning |
|--------|-----------|-----------------|
| AUTO_ELIGIBLE | confidence ≥ 0.85 | High confidence — safe for automated action |
| NEEDS_REVIEW | 0.50 ≤ confidence < 0.85 | Medium confidence — human review required |
| LOGGED_ONLY | confidence < 0.50 | Low confidence — log for trend tracking |

---

## 4. Why Two Separate ML Models?

**Decision:** One model for vibration, one for temperature (not a single multivariate model).

**Why?** SNOWFLAKE.ML.ANOMALY_DETECTION accepts a single target column per model. By training separate models, we can:
1. Identify the **driving signal** — which physical phenomenon is degrading
2. Combine counts additively — `VIB_ANOM + TEMP_ANOM = TOTAL_ANOMALIES`
3. Retrain independently if one sensor type drifts

**Why not include RPM as a model?** RPM is an operational parameter (controlled by the turbine controller), not a degradation indicator. It's used as a feature in the SILVER enrichment (`RPM_DELTA`) but not as a direct anomaly target.

---

## 5. Why This Agent Design?

### 4 Tools — Separation of Concerns
| Tool | Type | Why Separate? |
|------|------|---------------|
| FleetAnalytics | Semantic View (text-to-SQL) | Structured data queries — OEE, alerts, costs |
| MaintenanceSearch | Cortex Search (semantic) | Unstructured data retrieval — technician notes |
| CREATE_WORK_ORDER | Procedure (generic tool) | DML action with guardrail |
| NOTIFY_CRITICAL_ALERT | Procedure (generic tool) | Side effect (email) |

**Why not a single "do everything" tool?** The agent needs to reason about *when* to act. Analysis tools (FleetAnalytics, MaintenanceSearch) are always safe. Action tools (CreateWO, Notify) have consequences. Separating them lets the agent's instructions say: "Use analysis tools freely; only use action tools when confidence ≥ 0.85."

### Why the App Calls Procedures Directly
DATA_AGENT_RUN invokes generic tools as `SELECT` (UDF context). But CREATE_WORK_ORDER and NOTIFY_CRITICAL_ALERT need `INSERT` statements (DML). DML is not allowed in UDF context. Solution: the agent *analyzes* and *recommends*, then the Streamlit app calls the procedures directly via `session.sql("CALL ...")`.

### Agent Instructions
```yaml
response: "For confidence >= 0.85, you may auto-create work orders.
           For 0.50-0.85, recommend but ask for confirmation.
           Below 0.50, advise monitoring only."
```
These instructions mirror the alert classification thresholds, creating consistency between the automated scoring pipeline and the agent's judgment.

---

## 6. Why Judge Mode?

**Problem:** In production, operators need different levels of autonomy depending on context. During normal operations, auto-execution saves time. During incident investigation, every action should be reviewed.

**Solution:** A single toggle in the sidebar:
- **Judge Mode ON:** Agent analyzes → Confirm/Deny buttons appear → human clicks → procedures execute
- **Judge Mode OFF:** Agent analyzes → auto-executes if confidence ≥ 0.85

**Implementation detail:** The toggle uses a single `key="judge_mode"` pattern:
```python
judge = st.toggle("Judge Exploration Mode", key="judge_mode")
```
This makes `st.session_state.judge_mode` the single source of truth. Early versions used a separate variable that copied the widget state, which caused a desync bug where the toggle appeared ON but the code path was OFF.

### Duplicate Submission Guard
```python
prompt = st.chat_input("...", disabled=st.session_state.processing)
```
When a request is in flight, `processing=True` disables the chat input. This prevents double-submission (which created duplicate work orders during testing).

---

## 7. Why This Email Format?

**Decision:** Professional HTML email via `SYSTEM$SEND_EMAIL` with `text/html` MIME type.

**Why HTML, not plain text?** Operators receive dozens of alerts. A structured HTML email with:
- Red banner header (visual urgency)
- Asset identification table (instant context)
- Alert details (confidence, signal, priority)
- Work order reference
- Recent failure history (pattern recognition)
- Maintenance notes (asset-specific or fleet-fallback)

...is scannable in 5 seconds. Plain text requires reading line by line.

**Maintenance notes fallback logic:**
1. Check for asset-specific notes from BRONZE_MAINTENANCE_LOG
2. If none, fall back to fleet-level notes for the same subsystem type
3. Fleet-fallback notes get a clear header: "(from fleet GEARBOX history — no asset-specific notes)"

This prevents the "no information available" dead end while being transparent about the source.

---

## 8. Why Synthetic Data With This Design?

### 18 Failure Events — Why These Specific Patterns?

| Category | Count | Purpose |
|----------|-------|---------|
| Scoring-window failures | 13 | Ground truth for precision/recall validation |
| Training-window-only failures | 3 | Tests that the model doesn't flag repaired assets |
| False positives (tent function) | 2 | Tests precision — temporary spikes that self-resolve |

**Quadratic degradation curve:** Real turbine degradation is not linear — it accelerates as damage compounds. `progress²` models this: slow at first, rapid near failure.

**Tent function for false positives:** Real-world "near-miss" events spike and recover. A tent function (ramp up, ramp down) over 2 days creates a signal that triggers some anomaly flags but self-resolves — exactly the scenario where an overly sensitive system would create unnecessary work orders.

### Replay Buffer — Why?
In production, sensor data arrives continuously from MQTT/Kafka via Snowpipe Streaming. For the hackathon, there's no external data source. The replay buffer simulates realistic data arrival:

1. Day 11 data (with WF02-T03-GBX degradation) is pre-generated into REPLAY_BUFFER
2. Each call to REPLAY_BATCH_PROC moves one hour of data from REPLAY_BUFFER → SENSOR_STREAM
3. Dynamic Tables detect the new data and refresh
4. Scoring re-runs, alert confidence values change
5. WF02-T03-GBX crosses from NEEDS_REVIEW (0.8124) → AUTO_ELIGIBLE (0.8832) after hour 15

This demonstrates the system's real-time detection capability without requiring external infrastructure.

---

## 9. Why These Precision/Recall Numbers?

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Detection recall | 100% (13/13) | All ground-truth anomalous assets appear in ALERT_QUEUE |
| Actionable recall | 84.6% (11/13) | 11 of 13 reach NEEDS_REVIEW or AUTO_ELIGIBLE |
| Precision | 73.3% (11/15) | 11 true positives out of 15 flagged above NEEDS_REVIEW |

**Why not 100% precision?** Precision of 73% means 4 out of 15 flagged assets are not true failures. These are:
- 2 false positives (tent-function near-misses) — the model correctly detected anomalous behavior, but the asset self-recovered
- 2 assets with elevated but not failure-level readings

For safety-critical rotating equipment, **recall matters more than precision**. Missing a real failure (false negative) causes downtime, cost, and safety risk. Investigating a false alarm (false positive) costs only inspection time. The 73% precision is intentionally conservative.

**The 2 "missed" detections (11/13 actionable):**
- WF01-T03-PIT: Subtle pitch system drift with low anomaly count. Present in ALERT_QUEUE as LOGGED_ONLY but hasn't accumulated enough anomalies to cross NEEDS_REVIEW.
- WF03-T02-YAW: Same pattern — genuine subtle signal that the threshold correctly identifies as not-yet-actionable.

These are not model failures; they're the threshold doing its job by not over-triggering on marginal signals. With more data (via replay), they would likely cross the threshold.

---

## 10. Why Container Runtime for Streamlit?

**Decision:** Deploy Streamlit to container runtime (SPCS compute pool) instead of the default warehouse runtime.

**Why?** The app uses:
- `st.toggle()` — requires Streamlit ≥ 1.31 (container runtime)
- `st.chat_input()` — requires container runtime for persistent chat state
- `st.chat_message()` — same requirement
- `st.dataframe(on_select="rerun")` — interactive row selection

The warehouse runtime ships an older Streamlit version that doesn't support these widgets. Container runtime runs the latest Streamlit with full widget support.

**Trade-off:** Container runtime is more expensive (dedicated compute pool vs shared warehouse). For a hackathon demo, the cost is acceptable ($264 of $400 trial remaining).

---

## 11. Why This Scoring Procedure Design?

SCORING_PROC does three things in sequence:
1. **Score vibration** → VIB_ANOMALY_RESULTS (CTAS)
2. **Score temperature** → TEMP_ANOMALY_RESULTS (CTAS)
3. **Combine + threshold + classify** → ALERT_QUEUE (CTAS)

**Why CTAS (CREATE OR REPLACE TABLE ... AS) instead of MERGE?** ALERT_QUEUE is small (27 rows). A full rebuild every 15 minutes is simpler, cheaper, and avoids merge conflicts. The entire scoring procedure runs in under 10 seconds on an X-Small warehouse.

**Priority scoring formula:**
```sql
(confidence * 0.5) + (criticality_weight * 0.3) + (site_priority_weight * 0.2)
```
This weighted composite ensures that a HIGH-criticality asset with moderate confidence ranks above a LOW-criticality asset with high confidence. The weights (50/30/20) were chosen to make confidence the primary driver while giving meaningful influence to business context.

---

## 12. Why This Task DAG?

```
SCORING_TASK (root, 15 min) → CRITICAL_ALERT_TASK (child)
FLEET_SUMMARY_TASK (standalone, daily)
RETRAIN_CANDIDACY_TASK (standalone, 6h)
REPLAY_TASK (standalone, 60 min)
```

**Why is CRITICAL_ALERT_TASK a child of SCORING_TASK?** Notifications should only fire after scoring completes. The `AFTER` clause guarantees this ordering.

**Why are the others standalone?** Fleet summary, retrain candidacy, and replay are independent of the scoring cycle. Running them on their own schedules avoids unnecessary coupling.

**Why are all tasks SUSPENDED?** For the hackathon, we control execution manually (via the Streamlit app and demo script). Resuming tasks would consume credits continuously.
