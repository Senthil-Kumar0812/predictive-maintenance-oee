"""
Standalone test: Call PDM_COMMAND_CENTER_AGENT via Cortex Agent REST API.
Tests auth, request format, and response parsing before wiring into Streamlit.
"""

import json
import sys
import snowflake.connector
import requests

# Connect using default connection (from ~/.snowflake/connections.toml or env vars)
ACCOUNT = "<YOUR_SNOWFLAKE_ACCOUNT>"
USER = "<YOUR_SNOWFLAKE_USER>"
DATABASE = "PDM_OEE_DB"
SCHEMA = "GOLD"
WAREHOUSE = "COMPUTE_WH"
AGENT_NAME = "PDM_COMMAND_CENTER_AGENT"

def get_connection():
    """Connect to Snowflake using the configured connection."""
    print("[1] Connecting to Snowflake...")
    conn = snowflake.connector.connect(
        connection_name="<YOUR_CONNECTION_NAME>",
        database=DATABASE,
        schema=SCHEMA,
        warehouse=WAREHOUSE,
    )
    print(f"    Connected. Role: {conn.role}, Warehouse: {conn.warehouse}")
    return conn


def get_session_token(conn):
    """Extract the session token from an active connection."""
    print("[2] Extracting session token...")
    token = conn.rest.token
    print(f"    Token obtained (length={len(token)})"  )
    return token


def get_host(conn):
    """Get the REST API host."""
    host = conn.rest._host
    print(f"    Host: {host}")
    return host


def call_agent(host, token, query):
    """Call the Cortex Agent REST API."""
    url = f"https://{host}/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/agents/{AGENT_NAME}:run"
    print(f"[3] Calling agent REST API...")
    print(f"    URL: {url}")
    print(f"    Query: {query}")

    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query}
                ],
            }
        ],
        "stream": False,
    }

    resp = requests.post(url, headers=headers, json=body, timeout=120)
    print(f"    Status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"    ERROR: {resp.text[:500]}")
        return None

    return resp.json()


def parse_response(data):
    """Parse agent response to extract text, tool_use, and thinking."""
    print("[4] Parsing response...")

    if not data:
        print("    No data to parse.")
        return

    # Handle both streaming (list of events) and non-streaming (single object)
    content = data.get("content", [])
    if not content and isinstance(data, list):
        # SSE events might come as a list
        for event in data:
            content.extend(event.get("content", []))

    tools_used = []
    text_parts = []
    thinking_parts = []

    for item in content:
        item_type = item.get("type", "unknown")

        if item_type == "text":
            text_parts.append(item.get("text", ""))
        elif item_type == "tool_use":
            tool_info = item.get("tool_use", {})
            tools_used.append({
                "name": tool_info.get("name", "unknown"),
                "type": tool_info.get("type", "unknown"),
                "client_side_execute": tool_info.get("client_side_execute", False),
            })
        elif item_type == "thinking":
            thinking_parts.append(item.get("thinking", {}).get("text", "")[:200])
        elif item_type == "tool_result":
            pass  # Internal tool results

    print(f"\n    TOOLS USED ({len(tools_used)}):")
    for t in tools_used:
        print(f"      - {t['name']} (type={t['type']}, client_execute={t['client_side_execute']})")

    print(f"\n    THINKING ({len(thinking_parts)} blocks):")
    for i, t in enumerate(thinking_parts):
        print(f"      [{i}] {t}...")

    print(f"\n    RESPONSE TEXT:")
    full_text = "\n".join(text_parts)
    print(f"      {full_text[:500]}")

    # Check for warnings
    warnings = data.get("warnings", [])
    if warnings:
        print(f"\n    WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"      - [{w.get('code')}] {w.get('message', '')[:200]}")

    # Check for metadata
    metadata = data.get("metadata", {})
    if metadata:
        print(f"\n    METADATA: {json.dumps(metadata, indent=2)}")

    return {
        "text": full_text,
        "tools_used": tools_used,
        "thinking": thinking_parts,
        "warnings": warnings,
    }


def main():
    query = "What is the fleet average OEE?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    conn = get_connection()
    token = get_session_token(conn)
    host = get_host(conn)

    # Resume warehouse first
    print("[2.5] Resuming warehouse...")
    cur = conn.cursor()
    cur.execute("ALTER WAREHOUSE COMPUTE_WH RESUME IF SUSPENDED")
    cur.close()

    raw_response = call_agent(host, token, query)

    if raw_response:
        # Save raw response for debugging
        with open("agent_response_raw.json", "w") as f:
            json.dump(raw_response, f, indent=2, default=str)
        print("    Raw response saved to agent_response_raw.json")

        result = parse_response(raw_response)
        print("\n" + "=" * 60)
        print("TEST RESULT: SUCCESS" if result and result["text"] else "TEST RESULT: NO TEXT IN RESPONSE")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("TEST RESULT: FAILED - No response from agent")
        print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
