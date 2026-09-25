"""
Test the agent-response-inspection approach for Judge Mode gate detection.
Runs 4 queries with action tools restricted, checks if the agent's response
text triggers the Confirm/Deny gate.
"""

import json
import snowflake.connector
import requests

DATABASE = "PDM_OEE_DB"
SCHEMA = "GOLD"
AGENT_NAME = "PDM_COMMAND_CENTER_AGENT"

ACTION_SIGNALS = [
    "auto-eligible", "auto_eligible", "create a work order",
    "work order", "recommend creating", "should be created",
    "i'll create", "i will create", "proceed with",
    "notify", "send a critical", "alert notification",
    "action is warranted", "auto-action", "guardrail",
]

QUERIES = [
    ("Q1: Vague status check", "What's going on with WF01-T01-GEN?"),
    ("Q2: Indirect action hint", "Should we do anything about the generator on turbine 1 at North Ridge?"),
    ("Q3: Non-standard action phrasing", "File a maintenance ticket for this issue"),
    ("Q4: Purely informational", "What's the fleet average OEE?"),
]

EXPECTED_GATE = {
    "Q1: Vague status check": True,       # Agent should mention the alert -> action signals
    "Q2: Indirect action hint": True,      # Agent should recommend action
    "Q3: Non-standard action phrasing": True,  # Agent should reference work order
    "Q4: Purely informational": False,     # No action intent
}


def connect():
    conn = snowflake.connector.connect(
        connection_name="<YOUR_CONNECTION_NAME>",
        database=DATABASE, schema=SCHEMA, warehouse="COMPUTE_WH",
    )
    conn.cursor().execute("ALTER WAREHOUSE COMPUTE_WH RESUME IF SUSPENDED")
    return conn


def call_agent_restricted(host, token, query):
    url = f"https://{host}/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/agents/{AGENT_NAME}:run"
    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": query}]}],
        "stream": False,
        "tool_choice": {"type": "auto", "name": ["FleetAnalytics", "MaintenanceSearch"]},
    }
    resp = requests.post(url, headers=headers, json=body, timeout=180)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    return resp.json(), None


def extract_text(data):
    content = data.get("content", [])
    texts = [item.get("text", "") for item in content if item.get("type") == "text"]
    tools = [item["tool_use"]["name"] for item in content if item.get("type") == "tool_use"]
    return "\n".join(texts), tools


def check_gate(text):
    matched = [s for s in ACTION_SIGNALS if s in text.lower()]
    return len(matched) > 0, matched


def main():
    conn = connect()
    host = conn.rest._host
    token = conn.rest.token

    results = []

    for label, query in QUERIES:
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"  Query: \"{query}\"")
        print(f"{'='*70}")

        data, err = call_agent_restricted(host, token, query)
        if err:
            print(f"  ERROR: {err}")
            results.append((label, "ERROR", False, []))
            continue

        text, tools = extract_text(data)
        gate_triggered, matched_signals = check_gate(text)
        expected = EXPECTED_GATE[label]

        print(f"\n  Tools used: {tools}")
        print(f"\n  Response text (first 500 chars):")
        print(f"  {text[:500]}")
        print(f"\n  Matched action signals: {matched_signals}")
        print(f"  Gate triggered: {gate_triggered}")
        print(f"  Expected gate: {expected}")
        print(f"  RESULT: {'PASS' if gate_triggered == expected else 'FAIL'}")

        results.append((label, text[:200], gate_triggered, matched_signals))

    # Summary
    print(f"\n\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    all_pass = True
    for label, _, gate, signals in results:
        expected = EXPECTED_GATE[label]
        status = "PASS" if gate == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {status}  {label:40s}  gate={gate}  expected={expected}  signals={signals}")

    print(f"\n  OVERALL: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print(f"{'='*70}")

    conn.close()


if __name__ == "__main__":
    main()
