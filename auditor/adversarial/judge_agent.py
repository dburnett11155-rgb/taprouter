"""judge_agent.py — the ARBITER. Reads the Red/White exchange and renders a verdict with
calibrated confidence. CRITICAL: the Judge does NOT have final dismissal authority. A verdict of
'not exploitable' means 'route to sandbox to confirm' — never 'cleared'. Only Layer 3 (running the
actual exploit) truly clears a real-severity finding. Judge decides what to sandbox, escalates
Red/White disagreement to human review, and preserves tool severity as immutable ground truth."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adversarial import gemini_client

SYSTEM = """You are the Judge, lead auditor arbitrating between two colleagues: Red (assesses
exploitability) and White (designs patches / independently verifies). You read their exchange and
the finding, and render a verdict for the audit report.

CRITICAL RULES:
- You do NOT have authority to finally CLEAR a real-severity (high/medium) finding by reasoning
  alone. Your verdict routes the finding, it does not absolve it. Only sandbox execution (running
  the actual exploit) can confirm a dismissal. So for any high/medium finding Red/White call safe,
  your verdict is "confirm_in_sandbox", NOT "dismissed".
- If Red and White DISAGREE, that is a red flag — set needs_human=true and verdict="disputed".
- Tool severity is ground truth; you never downgrade the recorded severity. You assess exploitability
  as a SEPARATE axis. A finding can be "high severity, sandbox-confirm exploitability".
- Cosmetic categories (naming-convention, solc-version pragma, unused informational) CAN be dismissed
  by reasoning — they carry no exploit path by nature.

Reply ONLY with JSON:
{
  "verdict": "exploitable_confirmed" | "confirm_in_sandbox" | "dismissed_cosmetic" | "disputed",
  "exploitability": "confirmed" | "likely" | "unlikely" | "unknown",
  "recorded_severity": "<the tool severity, unchanged>",
  "needs_sandbox": true | false,
  "needs_human": true | false,
  "patch_available": true | false,
  "summary": "one or two sentences for the audit report — what this finding is and its disposition",
  "reasoning": "why this verdict, citing Red and White specifically"
}"""

def arbitrate(finding: dict, red_verdict: dict, white_verdict: dict, run_dir=None) -> dict:
    user = f"""FINDING:
  severity (GROUND TRUTH, do not change): {finding.get('severity')}
  detectors: {finding.get('check_ids')}
  location: {finding.get('file')} lines {finding.get('lines')}
  description: {finding.get('description')}

RED (exploitability): exploitable={red_verdict.get('exploitable')}, confidence={red_verdict.get('confidence')}
  {red_verdict.get('exploit_hypothesis','')}

WHITE (defense/verification): agree_with_red={white_verdict.get('agree_with_red')}, finding_is_real={white_verdict.get('finding_is_real')}, patch_needed={white_verdict.get('patch_needed')}
  {white_verdict.get('reasoning','')}

Render your verdict. Remember: you cannot finally clear a high/medium finding by reasoning — route
it to sandbox. Only dismiss outright if it is a cosmetic category with no possible exploit path."""
    return gemini_client.call_json(SYSTEM, user, label="judge", run_dir=run_dir, temperature=0.1)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/home/dburnett11155/taprouter/.env.local")
    from adversarial.red_agent import prosecute
    from adversarial.white_agent import defend
    # Full three-agent chain on the planted REAL bug.
    code = open("auditor/known_vulns/VulnerableVault.sol").read()
    finding = {"tools":["aderyn"],"severity":"high","check_ids":["reentrancy-state-change"],
      "file":"VulnerableVault.sol","lines":[10],"description":"Reentrancy: state change after external call",
      "triage_hint":"check CEI ordering and nonReentrant guard."}
    red = prosecute(finding, code)
    white = defend(finding, code, red)
    judge = arbitrate(finding, red, white)
    print("=== FULL CHAIN on planted REAL bug ===")
    print("RED:", red.get("exploitable"), "| WHITE real:", white.get("finding_is_real"))
    print("JUDGE verdict:", judge.get("verdict"))
    print("  exploitability:", judge.get("exploitability"), "| recorded_severity:", judge.get("recorded_severity"))
    print("  needs_sandbox:", judge.get("needs_sandbox"), "| needs_human:", judge.get("needs_human"))
    print("  summary:", judge.get("summary"))
