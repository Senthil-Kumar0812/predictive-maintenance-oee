"""
Two-phase divergence test for Judge Mode.

Phase 1: Call agent with tool_choice restricting to analysis-only tools.
          Capture stated confidence, recommended action, and reasoning.
Phase 2: Call agent with full tool access (same query).
          Capture actual execution, compare to Phase 1.

Goal: Confirm Phase 1 preview matches Phase 2 execution exactly.
"""

import json
import snowflake.connector
import requests

DATABASE = "PDM_OEE_DB"
SCHEMA = "GOLD"
WAREHOUSE = "COMPUTE_WH"
AGENT_NAME = "PDM_COMMAND_CENTER_AGENT"

QUERY = (
    "WF01-T01-GEN has vibration anomalies with 94.5% confidence. "
    "Create a work order for it."
)


def connect():
    conn = snowflake.connector.connect(
        connection_name="<YOUR_CONNECTION_NAME>",
        database=DATABASE, schema=SCHEMA, warehouse=WAREHOUSE,
    )
    conn.cursor().execute("ALTER WAREHOUSE COMPUTE_WH RESUME IF SUSPENDED")
    return conn


def call_agent(host, token, query, tool_choice=None):
    url = f"https://{host}/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/agents/{AGENT_NAME}:run"
    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": query}]}],
        "stream": False,
    }
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    resp = requests.post(url, headers=headers, json=body, timeout=180)
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:500]}")
        return None
    return resp.json()


def extract_details(data, label):
    """Extract key details from agent response for comparison."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    content = data.get("content", [])
    tools_invoked = []
    action_tools = []
    text_parts = []
    thinking_parts = []
    tool_results = []

    for item in content:
        t = item.get("type")
        if t == "tool_use":
            tu = item["tool_use"]
            name = tu.get("name", "?")
            ttype = tu.get("type", "?")
            tools_invoked.append(name)
            if ttype == "generic":
                action_tools.append({
                    "name": name,
                    "input": tu.get("input", {}),
                })
        elif t == "tool_result":
            tr = item["tool_result"]
            if tr.get("type") == "generic":
                tool_results.append({
                    "name": tr.get("name", "?"),
                    "status": tr.get("status", "?"),
                    "content": tr.get("content", []),
                })
        elif t == "text":
            text_parts.append(item.get("text", ""))
        elif t == "thinking":
            thinking_parts.append(item.get("thinking", {}).get("text", ""))

    full_text = "\n".join(text_parts)

    print(f"\n  Tools invoked: {tools_invoked}")
    print(f"  Action tools called: {[a['name'] for a in action_tools]}")
    if action_tools:
        for a in action_tools:
            print(f"    {a['name']} input: {json.dumps(a['input'], indent=4)}")
    if tool_results:
        for tr in tool_results:
            print(f"    {tr['name']} result: status={tr['status']}")
    print(f"\n  Thinking:")
    for i, t in enumerate(thinking_parts):
        print(f"    [{i}] {t[:300]}")
    print(f"\n  Response text (first 600 chars):")
    print(f"    {full_text[:600]}")

    return {
        "tools_invoked": tools_invoked,
        "action_tools": action_tools,
        "tool_results": tool_results,
        "text": full_text,
        "thinking": thinking_parts,
    }


def main():
    conn = connect()
    token = conn.rest.token
    host = conn.rest._host

    # ── PHASE 1: Analysis only (exclude action tools) ──
    print("\n" + "#"*60)
    print("# PHASE 1: Analysis-only (tool_choice excludes action tools)")
    print("#"*60)

    # Strategy A: Use tool_choice to restrict to named analysis tools only
    phase1_choice = {
        "type": "auto",
        "name": ["FleetAnalytics", "MaintenanceSearch"],
    }
    phase1_data = call_agent(host, token, QUERY, tool_choice=phase1_choice)
    if not phase1_data:
        print("Phase 1 FAILED")
        return

    with open("phase1_response.json", "w") as f:
        json.dump(phase1_data, f, indent=2, default=str)

    p1 = extract_details(phase1_data, "PHASE 1 (analysis-only)")

    # ── PHASE 2: Full access (all tools available) ──
    print("\n\n" + "#"*60)
    print("# PHASE 2: Full access (all tools enabled)")
    print("#"*60)

    phase2_data = call_agent(host, token, QUERY)
    if not phase2_data:
        print("Phase 2 FAILED")
        return

    with open("phase2_response.json", "w") as f:
        json.dump(phase2_data, f, indent=2, default=str)

    p2 = extract_details(phase2_data, "PHASE 2 (full access)")

    # ── COMPARISON ──
    print("\n\n" + "#"*60)
    print("# COMPARISON: Phase 1 vs Phase 2")
    print("#"*60)

    # Check 1: Did Phase 2 use action tools?
    p2_actions = [a["name"] for a in p2["action_tools"]]
    print(f"\n  Phase 2 action tools: {p2_actions}")

    # Check 2: Did Phase 1 mention the same confidence/action in its text?
    p1_mentions_confidence = any(
        s in p1["text"].lower() for s in ["0.945", "94.5", "0.9451", "auto_eligible"]
    )
    p2_mentions_confidence = any(
        s in p2["text"].lower() for s in ["0.945", "94.5", "0.9451", "auto_eligible"]
    )
    print(f"  Phase 1 mentions confidence: {p1_mentions_confidence}")
    print(f"  Phase 2 mentions confidence: {p2_mentions_confidence}")

    # Check 3: Did Phase 1 recommend creating a work order?
    p1_recommends_wo = any(
        s in p1["text"].lower() for s in ["work order", "create a work order", "wo-"]
    )
    p2_created_wo = "CreateWorkOrder" in p2_actions
    print(f"  Phase 1 recommends work order: {p1_recommends_wo}")
    print(f"  Phase 2 actually created WO: {p2_created_wo}")

    # Check 4: Did Phase 1 flag the signal mismatch (VIBRATION vs TEMPERATURE)?
    p1_flags_mismatch = any(
        s in p1["text"].lower() for s in ["temperature", "driving signal", "mismatch"]
    )
    p2_flags_mismatch = any(
        s in p2["text"].lower() for s in ["temperature", "driving signal", "mismatch"]
    )
    print(f"  Phase 1 flags signal mismatch: {p1_flags_mismatch}")
    print(f"  Phase 2 flags signal mismatch: {p2_flags_mismatch}")

    # Extract WO parameters from Phase 2 action tools for comparison
    for a in p2["action_tools"]:
        if a["name"] == "CreateWorkOrder":
            print(f"\n  Phase 2 CreateWorkOrder params:")
            for k, v in a["input"].items():
                print(f"    {k} = {v}")

    # Verdict
    print("\n" + "="*60)
    if p1_recommends_wo and p2_created_wo and p1_mentions_confidence and p2_mentions_confidence:
        print("VERDICT: Phase 1 preview ALIGNS with Phase 2 execution")
    else:
        print("VERDICT: DIVERGENCE DETECTED between Phase 1 and Phase 2")
        print(f"  P1 recommends WO: {p1_recommends_wo}, P2 created WO: {p2_created_wo}")
        print(f"  P1 confidence: {p1_mentions_confidence}, P2 confidence: {p2_mentions_confidence}")
    print("="*60)

    conn.close()


if __name__ == "__main__":
    main()
