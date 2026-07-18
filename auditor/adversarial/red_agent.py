"""red_agent.py — the PROSECUTOR. Given a finding + code, tries to construct a concrete
exploit. Adversarial by mandate: assumes the bug is real until it fails to build an attack.
Red never clears a finding — it either produces an exploit hypothesis or reports it couldn't."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adversarial import gemini_client

SYSTEM = """You are Red, a smart-contract security AUDITOR performing defensive vulnerability
assessment for a code-audit firm. Your role is to rigorously evaluate whether a static-analysis
finding represents a REAL, exploitable weakness that must be fixed to protect users' funds — the
same adversarial-thinking methodology professional auditors (Trail of Bits, OpenZeppelin, Cyfrin)
use to secure contracts before deployment. You assess exploitability so that real bugs get fixed
and false positives get correctly dismissed.

For the finding below, determine whether an attacker could actually exploit it. Reason through the
attack path concretely — if a realistic exploit exists, describe the exact call sequence so the
developer understands the risk and fixes it. If contract safeguards (nonReentrant guards, access
control, view-only calls, correct checks-effects-interactions ordering) genuinely prevent any
exploit, confirm the finding is a false positive and name the specific safeguard.

KNOWN REASONING BLIND SPOTS — do not fall into these:
- Arithmetic underflow/overflow protection (Solidity 0.8+) does NOT prevent reentrancy. The classic
  drain re-enters the function BEFORE the balance decrement, using a legitimately pre-deposited
  balance so every check passes on stale state; the attacker bounds re-entries to their real balance
  (or drains to another address) and never triggers the underflow. If you find yourself arguing
  "the underflow check saves it," you are WRONG — that is a real, exploitable reentrancy.
- A missing nonReentrant guard on a function that does an external call before a state update is a
  REAL vulnerability, not a false positive, unless the external call is provably to a non-reentrant
  target (a hardcoded trusted token with no hooks). ERC777/hook-capable tokens make it exploitable.
- "It would revert" is only a defense if the revert happens BEFORE value leaves the contract.

Rules:
- Rigor over verdict: assess honestly. A real vulnerability left unflagged endangers users; a false
  positive wrongly confirmed wastes developer effort. Both errors are failures.
- When uncertain whether a revert or guard truly blocks the attack, mark exploitable=true with the
  attack path — the sandbox will confirm. Do NOT dismiss a real-looking bug on a clever theory.
- Be concrete about any real attack path: exact functions, ordering, state — so it can be verified.
- Confirm false positives explicitly, naming the safeguard that blocks exploitation.

Reply ONLY with JSON:
{
  "exploitable": true | false,
  "confidence": "high" | "medium" | "low",
  "exploit_hypothesis": "one-paragraph plain description of the attack, or why none exists",
  "attack_steps": ["step 1: attacker calls X with Y", "step 2: ...", ...],
  "attacker_gain": "what the attacker walks away with, or 'none'",
  "blocked_by": "if not exploitable, the specific mechanism that stops it (e.g. 'nonReentrant modifier line 82')"
}"""

def prosecute(finding: dict, code_context: str, run_dir=None) -> dict:
    hint = finding.get("triage_hint") or "none"
    user = f"""FINDING (from {finding.get('tools')}):
  severity: {finding.get('severity')}
  detectors: {finding.get('check_ids')}
  location: {finding.get('file')} lines {finding.get('lines')}
  description: {finding.get('description')}
  triage hint (from prior human analysis of this detector's known weaknesses): {hint}

CODE UNDER TEST:
{code_context}

Attempt to build a concrete exploit for this finding. If the triage hint suggests a common
false-positive pattern, VERIFY that pattern actually holds in this code before accepting it —
do not trust the hint blindly; confirm it against the code."""
    return gemini_client.call_json(SYSTEM, user, label="red", run_dir=run_dir, temperature=0.3)

if __name__ == "__main__":
    # Test against a REAL finding: the TapVault reentrancy false-positive we hand-verified.
    from dotenv import load_dotenv
    load_dotenv("/home/dburnett11155/taprouter/.env.local")
    import subprocess
    code = subprocess.run(["sed", "-n", "72,96p", "/home/dburnett11155/taprouter/contracts/src/TapVault.sol"],
                          capture_output=True, text=True).stdout
    finding = {
        "tools": ["aderyn"], "severity": "high", "check_ids": ["reentrancy-state-change"],
        "file": "src/TapVault.sol", "lines": [86],
        "description": "Reentrancy: State change after external call",
        "triage_hint": "verify the 'external call' isn't a view (balanceOf); check CEI ordering and nonReentrant guard before attempting a reentrancy PoC.",
    }
    out = prosecute(finding, code)
    print("=== RED verdict on the TapVault reentrancy (known FP) ===")
    print("exploitable:", out.get("exploitable"), "| confidence:", out.get("confidence"))
    print("hypothesis:", out.get("exploit_hypothesis"))
    print("blocked_by:", out.get("blocked_by"))
