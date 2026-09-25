import re

# Exact text from the real agent response (3 text entries joined)
text = """I'll check the alert details for WF01-T04-GBX.
The confidence is 0.9487, well above the 0.85 auto-create threshold, and the alert is flagged AUTO_ELIGIBLE. I'll create the corrective work order.
I found the anomaly and confirmed it warrants a work order, but the creation step failed.  **Anomaly details for WF01-T04-GBX (gearbox):** - **Confidence:** 0.9487 — above the 0.85 auto-create threshold - **Status:** AUTO_ELIGIBLE - **Driving signal:** TEMPERATURE - **Priority:** 97 - **Alert ID:** 5b806928-7732-4b5a-9ec7-94b458690e15  Because confidence exceeds 0.85, this qualifies for auto-creation. However, the work order could not be created — the `CREATE_WORK_ORDER` action returned an error (the function is not currently available/registered on this environment):  > Unknown function CREATE_WORK_ORDER.  This is a system/configuration issue rather than anything wrong with the alert itself. To proceed, an agent admin will need to enable or correctly register the work-order creation tool. Once that's fixed, I can retry immediately with the values above.  In the meantime, would you like me to: - Send a critical alert notification for this asset, or - Pull maintenance history / prior gearbox failures for WF01-T04-GBX to help scope the repair?"""

print("=== Full text length:", len(text))
print()

# Asset regex
asset_match = re.search(r'(WF\d{2}-T\d{2}-[A-Z]{3})', text)
print("Asset match:", asset_match.group(1) if asset_match else "NONE")

# Confidence regex (the one in the deployed code)
conf_match = re.search(r'confidence[\s:=]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?', text.lower())
print("Conf match:", conf_match.group(1) if conf_match else "NONE")

# Debug: show what's around "confidence" in the lowered text
lower = text.lower()
idx = lower.find("confidence")
if idx >= 0:
    snippet = lower[idx:idx+60]
    print(f"First 'confidence' context: ...{snippet}...")

# Check: the ** bold markers around "Confidence:" — does the regex handle **Confidence:**?
idx2 = lower.find("**confidence")
if idx2 >= 0:
    snippet2 = lower[idx2:idx2+60]
    print(f"Bold confidence context: ...{snippet2}...")

# The issue: "**confidence:**" — the ** before "confidence" means the regex
# starting with 'confidence[\s:=]' won't match because the character before
# 'confidence' is '*' — but that shouldn't matter since regex looks for the
# PATTERN, not what comes before it.
# BUT: "**Confidence:** 0.9487" in lowercase = "**confidence:** 0.9487"
# regex: confidence[\s:=]* matches "confidence:" then [\s:=]* eats the space
# then (?:is\s+|of\s+|score\s+)? doesn't match, then ([0-9]+\.?[0-9]*) should match "0.9487"
# Wait — there's "** " between ":" and "0.9487"
# Let me check the exact bytes

print()
print("=== Testing with the FIRST occurrence of 'confidence' ===")
# "The confidence is 0.9487" — this should match
first_conf = re.search(r'confidence[\s:=]*(?:is\s+|of\s+|score\s+)?([0-9]+\.?[0-9]*)\s*%?', "the confidence is 0.9487, well above")
print("Test 'the confidence is 0.9487':", first_conf.group(1) if first_conf else "NONE")
