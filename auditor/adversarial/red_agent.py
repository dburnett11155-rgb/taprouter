"""red_agent.py — the PROSECUTOR. Given a finding + code, tries to construct a concrete
exploit. Adversarial by mandate: assumes the bug is real until it fails to build an attack.
Red never clears a finding — it either produces an exploit hypothesis or reports it couldn't."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adversarial import gemini_client

SYSTEM = """You are a Solidity security code reviewer helping a developer harden their own
contract before deployment. A static analyzer has flagged a pattern. Your job is to determine
whether it represents a REAL defect that needs fixing to protect the developer's users, or a
false positive that is already safe.

Assess the flagged code against safe patterns (checks-effects-interactions ordering, reentrancy
guards, access control, safe arithmetic). To explain WHY a real defect matters, describe the
scenario a malicious actor could use if it were left unfixed — this justifies the fix to the
developer. If existing safeguards already make the pattern safe, confirm it is a false positive
and name the specific safeguard.

KNOWN REVIEW BLIND SPOTS — do not fall into these:
- Arithmetic underflow/overflow protection (Solidity 0.8+) does NOT by itself prevent reentrancy.
  A function that sends value via an external call BEFORE updating state can be re-entered while
  the stale state still passes checks. If the withdraw sends the FULL balance before zeroing it,
  a re-entrant call sees the full balance again and drains beyond the caller's deposit.
- A missing reentrancy guard on a function doing an external call before a state update is a REAL
  defect unless the external call is provably to a non-reentrant target.
- "It would revert" is only a safeguard if the revert happens BEFORE value leaves the contract.

Reply ONLY with JSON:
{
  "exploitable": true | false,
  "confidence": "high" | "medium" | "low",
  "exploit_hypothesis": "the scenario a fix would prevent, or why the code is already safe",
  "attack_steps": ["step 1", "step 2", ...],
  "attacker_gain": "what an attacker could gain if unfixed, or 'none'",
  "blocked_by": "if safe, the specific safeguard that makes it a false positive"
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
