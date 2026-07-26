"""explain.py — plain-language explanation of Crucible findings, shared by both tiers."""
import sys, pathlib, json as _json
AUDITOR = pathlib.Path("/home/dburnett11155/taprouter/auditor")
sys.path.insert(0, str(AUDITOR))
from adversarial import llm_client

_SYSTEM = """You explain smart-contract security findings to a NON-technical contract owner.

Rules, in order of importance:
1. Explain ONLY the findings in the input. Never add, infer, or invent an issue not listed.
   If the list is empty, say plainly that the scanners found no issues, and do NOT imply that
   means the contract is safe.
2. CRITICAL — respect each finding's "disposition"/"adjudication" field. A finding marked
   CLEARED (cleared_by_debate, cleared_by_failed_exploit, INVARIANT_HELD) was raised by a
   scanner but DISMISSED by the engine's review — you MUST describe it as "flagged by the
   scanner but cleared on review as not exploitable," NEVER as a confirmed or real defect.
   Only findings whose disposition STANDS (UNRESOLVED, PROVEN_BY_EXPLOIT, INVARIANT_VIOLATED,
   disputed, error) are genuine concerns. If ALL findings are CLEARED, say the contract passed
   review with no confirmed defects — but still not an absolute guarantee. Your explanation
   MUST NOT contradict this: do not say a cleared finding "could lead to loss of funds" as if real.
3. Never overstate certainty. These are scanner/engine findings, not a guarantee. Do not tell
   the owner their contract "is safe" or "is secure." Say an issue "was flagged," "was cleared
   on review," or "remains unresolved" as appropriate to its disposition.
3. Plain language. No jargon without a one-clause plain gloss. Short sentences.
4. For each significant finding: what it is, what could go wrong in practical terms, how serious.
5. Group trivial/low findings briefly; spend words on high-severity items.

Return STRICT JSON, no markdown:
{"summary": "<2-3 sentence plain overview>", "findings_plain": [{"what": "<plain name>", "risk": "<what could go wrong>", "severity": "<high|medium|low>"}], "bottom_line": "<one honest sentence on what this scan does and does NOT guarantee>"}"""


def explain(audit_result, certified=False, run_dir=None):
    findings = audit_result.get("findings", [])
    scope = ("CERTIFICATION tier: full engine ran (adversarial review, exploit sandbox, "
             "invariants). The badge means no defect was mechanically confirmed as of this "
             "run; it is not an absolute guarantee of safety." if certified else
             "ADVISORY tier: automated scanners (Slither + Aderyn) only. No adjudication, no "
             "exploit testing, no certification. A starting point for review, NOT a proof of safety.")
    user = ("Scope for your bottom_line: " + scope + "\n\nFindings (JSON):\n" +
            _json.dumps({"total": audit_result.get("total_findings"),
                         "by_severity": audit_result.get("by_severity"),
                         "findings": findings}, indent=2))
    try:
        out = llm_client.call_json(_SYSTEM, user, label="explain", run_dir=run_dir, temperature=0.1)
        if not isinstance(out, dict) or "summary" not in out:
            return {"summary": "(explanation unavailable)", "findings_plain": [], "bottom_line": scope}
        out["bottom_line"] = out.get("bottom_line") or scope
        return out
    except Exception as e:
        return {"summary": "(explanation unavailable: %s)" % str(e)[:120],
                "findings_plain": [], "bottom_line": scope}
