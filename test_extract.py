import re

def extract(text):
    asset_match = re.search(r'(WF\d{2}-T\d{2}-[A-Z]{3})', text)
    conf_match = re.search(r'confidence[\s:=]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?', text.lower())
    asset_id = asset_match.group(1) if asset_match else None
    confidence = None
    if conf_match:
        val = float(conf_match.group(1))
        confidence = val / 100.0 if val > 1 else val
    return asset_id, confidence

tests = [
    ("Pct 94.87%",    "WF01-T04-GBX has a confidence of 94.87% and qualifies"),
    ("Pct 95%",       "WF01-T04-GBX - Confidence: 95% (0.9487), Status: AUTO_ELIGIBLE"),
    ("Decimal first", "WF01-T04-GBX has confidence: 0.9487 (roughly 95%). Recommend WO."),
    ("Two assets",    "WF01-T04-GBX (confidence: 0.9487, AUTO_ELIGIBLE) is critical. WF02-T03-GBX (confidence: 0.8124) also elevated."),
    ("Agent actual",  "The confidence is 0.9487, well above the 0.85 threshold. Proceed for WF01-T04-GBX."),
    ("No asset",      "The gearbox on turbine 4 has confidence of 0.9487"),
    ("No confidence", "WF01-T04-GBX has a critical anomaly alert"),
    ("Both missing",  "The fleet has several alerts that need attention"),
    ("Conf=0",        "WF01-T02-YAW confidence 0 LOGGED_ONLY"),
]

for name, text in tests:
    a, c = extract(text)
    ok = a is not None and c is not None
    action = "EXECUTE" if ok else "REFUSE"
    print(f"{name:18s} | asset={str(a):16s} | conf={str(c):8s} | {action}")
