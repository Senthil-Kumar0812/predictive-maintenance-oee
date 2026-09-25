import re

# The EXACT format from the failing debug output
# The agent uses Markdown bold: **Confidence:** 0.949
# In the joined text this appears as: **Confidence:** 0.949

test_cases = [
    # The failing case — Markdown bold wrapping
    ("Real failure: **Confidence:** 0.949", "**Confidence:** 0.949 — above the 0.85 threshold"),
    ("Markdown bold with 4dp", "**Confidence:** 0.9487 — above threshold"),
    ("Markdown bold no space", "**Confidence:**0.949 status AUTO_ELIGIBLE"),
    # Varying decimal places
    ("1 decimal", "confidence: 0.9"),
    ("2 decimals", "confidence: 0.94"),
    ("3 decimals", "confidence: 0.949"),
    ("4 decimals", "confidence: 0.9487"),
    ("5 decimals", "confidence: 0.94870"),
    ("Integer 1", "confidence: 1"),
    # Our existing passing cases
    ("Plain 'is' format", "The confidence is 0.9487, well above"),
    ("Percentage", "confidence of 94.87% and qualifies"),
    ("Pct with colon", "Confidence: 95% (0.9487)"),
]

# Current deployed regex
pattern = r'confidence[\s:=]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?'

print("=== Current regex ===")
print(f"Pattern: {pattern}")
print()

for name, text in test_cases:
    lower = text.lower()
    m = re.search(pattern, lower)
    if m:
        val = float(m.group(1))
        normalized = val / 100.0 if val > 1 else val
        print(f"  {name:40s} | raw={m.group(1):10s} | norm={normalized:.4f} | MATCH")
    else:
        # Debug: show what's around 'confidence' in the lowered text
        idx = lower.find("confidence")
        if idx >= 0:
            after = lower[idx:idx+40]
            print(f"  {name:40s} | NO MATCH | context: '{after}'")
        else:
            print(f"  {name:40s} | NO MATCH | 'confidence' not found in text")

print()
print("=== Diagnosing the failure ===")
failing = "**confidence:** 0.949 — above the 0.85 threshold"
print(f"Text: {failing}")
print(f"Chars after 'confidence': {[c for c in failing[failing.find('confidence')+10:failing.find('confidence')+25]]}")

# The issue: after "confidence" we have ":"  then "*" then "*" then " " then "0.949"
# The regex expects [\s:=]* then optionally (is|of|score) then digits
# But "**" (two asterisks from Markdown close bold) comes between ":" and the space
# [\s:=]* matches ":" but then stops at "*" — the optional group doesn't match — then [0-9] doesn't match "*"
print()
print("Stepping through regex match attempt:")
print(f"  'confidence' matched at position")
print(f"  After 'confidence': '{failing[failing.find('confidence')+10:]}'")
print(f"  [\\s:=]* would eat: ':'")
print(f"  Next char: '*' — not \\s, not :, not =, not digit → FAIL")
print(f"  The Markdown '**' after ':' blocks the regex from reaching '0.949'")
