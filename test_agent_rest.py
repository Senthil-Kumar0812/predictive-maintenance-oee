import snowflake.connector
import requests
import json

conn = snowflake.connector.connect(connection_name='<YOUR_CONNECTION_NAME>')
token = conn.rest.token
host = conn.rest._host
print(f"HOST: {host}")

url = f"https://{host}/api/v2/databases/PDM_OEE_DB/schemas/GOLD/agents/PDM_COMMAND_CENTER_AGENT:run"
headers = {
    "Authorization": f'Snowflake Token="{token}"',
    "Content-Type": "application/json",
    "Accept": "application/json",
}
body = {
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Call CREATE_WORK_ORDER for WF01-T04-GBX with confidence 0.9487 and description SHAFT_MISALIGNMENT."}]}],
    "stream": False,
}
resp = requests.post(url, headers=headers, json=body, timeout=180)
print(f"STATUS: {resp.status_code}")
data = resp.json()

for item in data.get("content", []):
    t = item.get("type")
    if t == "text":
        print(f"\nTEXT: {item['text'][:600]}")
    elif t == "tool_result":
        tr = item.get("tool_result", {})
        print(f"\nTOOL_RESULT [{tr.get('name')}] status={tr.get('status')}")
        for c in tr.get("content", []):
            print(f"  -> {json.dumps(c, indent=2)[:500]}")
    elif t == "tool_use":
        tu = item.get("tool_use", {})
        print(f"\nTOOL_USE [{tu.get('name')}] cse={tu.get('client_side_execute')}: {json.dumps(tu.get('input', {}))[:300]}")

conn.close()
