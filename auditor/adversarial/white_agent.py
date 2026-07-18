"""white_agent.py — the DEFENDER. Given Red's verdict + the code, either designs the minimal
patch for a real bug (no signature changes) or independently checks Red's dismissal of a false
positive. Second set of eyes: White must be able to DISAGREE with Red — that disagreement is
signal the Judge weighs, and it guards against a single agent's error becoming the verdict."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adversarial import gemini_client

SYSTEM = """You are White, a smart-contract security AUDITOR specializing in remediation, working
alongside a colleague (Red) who assesses exploitability. You review Red's assessment of a
static-analysis finding and the code, then do ONE of two things:

IF Red judged the finding EXPLOITABLE (a real bug):
  Design the MINIMAL patch that eliminates the vulnerability. Hard constraints:
  - Do NOT change any function signature, public/external variable name, or event — external
    integrations depend on them (this is a firm rule).
  - Prefer the smallest correct fix: add a nonReentrant guard, reorder to checks-effects-interactions,
    add a missing access check — whatever the specific bug requires, minimally.
  - State exactly what the patch changes and why it closes the exploit Red described.

IF Red judged the finding NOT exploitable (a false positive):
  Independently verify. Do NOT just agree with Red. Check the code yourself: is the safeguard Red
  named actually present and actually sufficient? If you find Red missed something and the bug IS
  real, SAY SO — set agree_with_red=false and explain the exploit Red overlooked.

Reply ONLY with JSON:
{
  "agree_with_red": true | false,
  "finding_is_real": true | false,
  "patch_needed": true | false,
  "patch_description": "what to change, minimally, or 'none needed' — never alter signatures",
  "patched_code_snippet": "the specific corrected lines, or empty string",
  "reasoning": "why this patch closes the exploit, OR why the finding is genuinely safe, OR what Red missed"
}"""

def defend(finding: dict, code_context: str, red_verdict: dict, run_dir=None) -> dict:
    user = f"""FINDING:
  location: {finding.get('file')} lines {finding.get('lines')}
  detectors: {finding.get('check_ids')}
  description: {finding.get('description')}

RED'S ASSESSMENT:
  exploitable: {red_verdict.get('exploitable')}
  confidence: {red_verdict.get('confidence')}
  hypothesis: {red_verdict.get('exploit_hypothesis')}
  attack_steps: {red_verdict.get('attack_steps')}
  blocked_by: {red_verdict.get('blocked_by')}

CODE UNDER TEST:
{code_context}

If Red found a real exploit, design the minimal patch (no signature changes). If Red dismissed it,
independently verify Red is correct — and if Red is WRONG and the bug is real, say so."""
    return gemini_client.call_json(SYSTEM, user, label="white", run_dir=run_dir, temperature=0.2)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/home/dburnett11155/taprouter/.env.local")
    from adversarial.red_agent import prosecute
    # Full Red->White chain on the planted REAL bug: Red should flag, White should patch.
    code = open("auditor/known_vulns/VulnerableVault.sol").read()
    finding = {"tools":["aderyn"],"severity":"high","check_ids":["reentrancy-state-change"],
      "file":"VulnerableVault.sol","lines":[10],"description":"Reentrancy: state change after external call",
      "triage_hint":"check CEI ordering and nonReentrant guard."}
    red = prosecute(finding, code)
    print("RED:", red.get("exploitable"), "-", red.get("blocked_by") or "exploitable")
    white = defend(finding, code, red)
    print("=== WHITE on the planted bug ===")
    print("agree_with_red:", white.get("agree_with_red"), "| finding_is_real:", white.get("finding_is_real"))
    print("patch_needed:", white.get("patch_needed"))
    print("patch:", white.get("patch_description"))
    print("snippet:", white.get("patched_code_snippet")[:200])
