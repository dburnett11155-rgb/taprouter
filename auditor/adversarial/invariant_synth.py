"""invariant_synth.py — Phase 3 of Crucible's invariant engine. Synthesizes CANDIDATE
invariants for a contract via the controlled LLM. Candidates are NOT trusted — Phase 4's
mutation gate validates them (an invariant that doesn't catch the mutants it should is discarded).

Foundry invariant testing requires: a handler the fuzzer calls, and invariant_*() functions
asserting a property after every call sequence. The prompt below forces invariants that
reference REAL contract state and assert a GENUINE relationship — a vacuous invariant
(assertTrue(true)) would pass while testing nothing, so we instruct against it AND rely on
Phase 4 to catch any that slip through (they won't catch mutants -> discarded)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from adversarial import llm_client

SYSTEM = """You are a smart-contract invariant engineer. Given a Solidity contract, propose
SAFETY INVARIANTS: properties that must ALWAYS hold no matter what sequence of calls is made.

An invariant is good ONLY if it references real contract state and asserts a genuine relationship
that a bug would violate. Examples of GOOD invariants:
- "sum of all user balances <= total deposited" (accounting integrity)
- "contract token balance >= sum of recorded balances" (solvency)
- "no caller can withdraw more than they deposited" (no value creation)
- "only owner-set roles can reach privileged state" (access integrity)

FORBIDDEN: vacuous invariants that are trivially true (assertTrue(true), x == x). These pass
while testing nothing and are worthless.

For each invariant provide:
- name: a Foundry function name like invariant_solvency
- property: plain-English statement of what must hold and what bug it catches
- foundry_code: the complete invariant_*() function body asserting it, using real state vars
- tracked_vars: which contract state variables/mappings it reads

Return ONLY JSON: {"invariants": [{"name": "...", "property": "...", "foundry_code": "...", "tracked_vars": ["..."]}]}
Propose 2-5 invariants. Prefer fewer, stronger, genuinely-checkable ones over many weak ones."""


def normalize(code, abi, token_names=("usdc", "token", "asset", "currency")):
    """Rewrite invariant bodies written from INSIDE the contract into test-contract form.

    The model reliably proposes correct PROPERTIES but unreliably respects reference syntax:
    it emits bare `flashReserve` / `usdc.balanceOf(address(this))` as if inside the target.
    From the test contract those are undeclared identifiers. Prompting alone did not hold, so
    this is mechanical: every public view name from the ABI is rewritten to target.<name>(),
    address(this) becomes address(target), and a token-ish view used as a contract reference
    becomes the harness mock. Deterministic — independent of model formatting behaviour."""
    import re as _re
    views = [e["name"] for e in abi
             if e.get("type") == "function" and e.get("stateMutability") in ("view", "pure")]
    if not views:
        return code
    # The model's PROPERTIES are consistently sound; its PACKAGING is not — across runs it
    # has emitted bare asserts, wrapped functions, and inside-the-contract references. If the
    # function shell is missing, supply it deterministically rather than re-prompting.
    stripped = code.strip()
    if stripped and not stripped.startswith("function"):
        body = "\n".join("    " + ln for ln in stripped.splitlines())
        code = "function invariant_synthesized() public {\n%s\n}" % body
    out = code.replace("address(this)", "address(target)")
    # 1. token-ish view used as a contract handle: usdc.balanceOf(...) -> token.balanceOf(...)
    for v in views:
        if v.lower() in token_names:
            out = _re.sub(r'(?<![\w.])%s\s*\.' % _re.escape(v), "token.", out)
    # 2. any other view used as a handle: foo.bar() -> target.foo().bar() is ambiguous; skip.
    # 3. bare state reads -> accessor calls. Skip names already qualified (x.name / target.name)
    #    and names already being called (name(...)).
    for v in sorted(views, key=len, reverse=True):
        esc = _re.escape(v)
        # CALLED form first: accountedBalance() / shares(user) -> target.<same>(args).
        # A bare CALL is just as undeclared from the test contract as a bare read; the
        # lookbehind already protects anything already qualified (target.foo(), token.foo()).
        out = _re.sub(r'(?<![\w.])%s\s*\(' % esc, "target.%s(" % v, out)
        # then bare READS: flashReserve -> target.flashReserve()
        out = _re.sub(r'(?<![\w.])%s(?![\w(])' % esc, "target.%s()" % v, out)
    return out


def synthesize(contract_code, contract_name, run_dir=None):
    """Return list of candidate invariant dicts. Untrusted — Phase 4 validates."""
    user = f"""CONTRACT: {contract_name}
{contract_code}

Propose safety invariants for this contract. Each must reference real state and catch a real bug
class. Remember: a vacuous invariant is worse than none."""
    out = llm_client.call_json(SYSTEM, user, label="invariant_synth", run_dir=run_dir, temperature=0.2)
    invs = out.get("invariants", [])
    # basic sanity filter: drop obviously vacuous ones before they even reach Phase 4
    cleaned = []
    for inv in invs:
        code = inv.get("foundry_code", "")
        if "assertTrue(true)" in code.replace(" ", "") or not inv.get("name", "").startswith("invariant"):
            continue
        cleaned.append(inv)
    return cleaned


if __name__ == "__main__":
    vault = Path("/home/dburnett11155/taprouter/auditor/known_vulns/VulnerableVault.sol").read_text()
    cands = synthesize(vault, "VulnerableVault")
    print(f"=== {len(cands)} candidate invariants for VulnerableVault ===")
    for c in cands:
        print(f"\n[{c.get('name')}] tracks {c.get('tracked_vars')}")
        print(f"  property: {c.get('property')}")
        print(f"  code:\n{c.get('foundry_code')}")
