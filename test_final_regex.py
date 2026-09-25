import re

pattern = r'confidence[\s:=*]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?'

test_cases = [
    ("REAL FAILURE: **Confidence:** 0.949",  "**Confidence:** 0.949 — above threshold"),
    ("Markdown bold 4dp",                    "**Confidence:** 0.9487 — above threshold"),
    ("Markdown bold no space",               "**Confidence:**0.949 status"),
    ("1 decimal",       "confidence: 0.9"),
    ("2 decimals",      "confidence: 0.94"),
    ("3 decimals",      "confidence: 0.949"),
    ("4 decimals",      "confidence: 0.9487"),
    ("5 decimals",      "confidence: 0.94870"),
    ("Integer 1",       "confidence: 1"),
    ("Plain 'is'",      "The confidence is 0.9487, well above"),
    ("Percentage",      "confidence of 94.87% and qualifies"),
    ("Pct colon",       "Confidence: 95% (0.9487)"),
    ("No asset",        "gearbox confidence of 0.9487"),
    ("Conf=0",          "confidence 0 LOGGED_ONLY"),
]

all_pass = True
for name, text in test_cases:
    m = re.search(pattern, text.lower())
    if m:
        val = float(m.group(1))
        norm = val / 100.0 if val > 1 else val
        print(f"  PASS  {name:42s} | {norm:.4f}")
    else:
        print(f"  FAIL  {name:42s} | NO MATCH")
        all_pass = False

print()
print("ALL PASS" if all_pass else "SOME FAILED")
