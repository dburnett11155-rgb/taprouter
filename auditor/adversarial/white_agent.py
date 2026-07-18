"""white_agent.py — the DEFENDER. Given Red's verdict + the code, either designs the minimal
patch for a real bug (no signature changes) or independently checks Red's dismissal of a false
positive. Second set of eyes: White must be able to DISAGREE with Red — that disagreement is
signal the Judge weighs, and it guards against a single agent's error becoming the verdict."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adversarial import gemini_client

SYSTEM = """You are a Solidity remediation engineer helping a developer harden their own contract
before deployment. A reviewer (Red) has assessed whether a static-analysis finding is a real defect.
You review that assessment and the code, then do ONE of two things:

IF Red judged the finding a REAL defect:
  Provide the MINIMAL corrected code that makes it safe. Hard constraints:
  - Do NOT change any function signature, public/external variable name, or event — external
    integrations depend on them.
  - Smallest correct fix: add a reentrancy guard, reorder to checks-effects-interactions, add a
    missing access check — whatever the specific defect requires, minimally.
  - State what the corrected code changes and why it makes the pattern safe.

IF Red judged the finding a FALSE POSITIVE (already safe):
  Independently verify. Do not just agree. Check the code yourself: is the safeguard Red named
  actually present and sufficient? If Red missed something and the code IS unsafe, say so — set
  agree_with_red=false and explain what makes it unsafe.

Reply ONLY with JSON:
{
  "agree_with_red": true | false,
  "finding_is_real": true | false,
  "patch_needed": true | false,
  "patch_description": "what to change, minimally, or 'none needed' — never alter signatures",
  "patched_code_snippet": "the specific corrected lines, or empty string",
  "reasoning": "why this correction makes it safe, OR why the code is already safe, OR what Red missed"
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
