"""normalize.py — merge multi-tool findings into one ordered bundle for the adversarial layer.
Dedupes cross-tool overlaps (same file:line), ranks by severity, attaches triage_hints seeded
from documented detector weaknesses. Hints tell the Red agent WHERE TO AIM — they never
auto-dismiss. Ground truth severity is preserved; only exploit-testing downgrades a finding."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# Documented detector weaknesses (from live TapMarket/TapVault/TapRouter runs).
# Each: (check_id substring, hint for the Red agent's exploit attempt).
KNOWN_FP_PATTERNS = {
    "incorrect-equality": "strict == often a zero-init/first-time guard; exploitable only if a non-zero-but-distinct value can bypass it.",
    "reentrancy": "verify the 'external call' isn't a view (balanceOf); check CEI ordering and nonReentrant guard before attempting a reentrancy PoC.",
    "locks-ether": "check whether ETH is forwarded programmatically (fee-routing) rather than trapped; not a lock if a code path moves it out.",
    "weak-randomness": "only exploitable if the output must be UNPREDICTABLE; a unique-ID/nonce use with a collision guard is safe by design.",
    "naming-convention": "cosmetic; never security-relevant.",
    "solc-version": "informational pragma advisory; not a code defect.",
}

def _key(f):
    return (f["file"], tuple(f.get("lines", [])[:1]))  # dedupe on file + first line

def _hint(check_id):
    for pat, hint in KNOWN_FP_PATTERNS.items():
        if pat in (check_id or "").lower():
            return hint
    return None


# Bug-class families. Two findings merge ONLY if they share a family AND their line
# ranges overlap/are adjacent — proximity alone is never enough, or two different bugs
# on neighbouring lines would collapse into one and a real finding would be hidden.
_FAMILIES = {
    "reentrancy": ("reentrancy",),
    "tx-origin": ("tx-origin",),
    "unchecked-call": ("unchecked-lowlevel", "unchecked-low-level", "low-level-calls", "unchecked-transfer", "unchecked-return"),
    "eth-send": ("arbitrary-send-eth", "eth-send-unchecked"),
}

def _family(check_ids):
    """Return the bug family for a finding, or None if it has no known family."""
    ids = " ".join([c for c in (check_ids or []) if c]).lower()
    for fam, pats in _FAMILIES.items():
        if any(pat in ids for pat in pats):
            return fam
    return None

def _ranges_touch(a, b, slack=3):
    if not a or not b:
        return False
    return (min(a) - slack) <= max(b) and (min(b) - slack) <= max(a)

def _group_same_bug(findings):
    """Collapse findings that are the SAME bug reported by different tools at slightly
    different line ranges. Conservative by construction: requires a shared family."""
    out = []
    for f in findings:
        fam = _family(f.get("check_ids"))
        placed = False
        if fam:
            for g in out:
                if _family(g.get("check_ids")) == fam and _ranges_touch(g.get("lines"), f.get("lines")):
                    # merge into g: union lines/detectors/tools, keep highest severity
                    g["lines"] = sorted(set((g.get("lines") or []) + (f.get("lines") or [])))
                    for c in (f.get("check_ids") or []):
                        if c and c not in g["check_ids"]:
                            g["check_ids"].append(c)
                    for t in (f.get("tools") or []):
                        if t not in g["tools"]:
                            g["tools"].append(t)
                    if config.SEVERITY_RANK.get(f["severity"], 0) > config.SEVERITY_RANK.get(g["severity"], 0):
                        g["severity"] = f["severity"]
                    placed = True
                    break
        if not placed:
            out.append(dict(f))
    return out

def normalize(*tool_results) -> dict:
    """Takes N tool result dicts. Returns a unified, deduped, ranked bundle."""
    merged = {}
    tools_ran, tools_failed = [], []
    for res in tool_results:
        if not res.get("ok"):
            tools_failed.append({"tool": res.get("tool"), "error": res.get("error")})
            continue
        tools_ran.append(res["tool"])
        for f in res["findings"]:
            k = _key(f)
            if k in merged:
                # same site flagged by another tool — merge tool attribution, keep higher severity
                if config.SEVERITY_RANK.get(f["severity"], 0) > config.SEVERITY_RANK.get(merged[k]["severity"], 0):
                    merged[k]["severity"] = f["severity"]
                if f["tool"] not in merged[k]["tools"]:
                    merged[k]["tools"].append(f["tool"])
                merged[k]["check_ids"].append(f["check_id"])
            else:
                merged[k] = {
                    "severity": f["severity"], "tools": [f["tool"]],
                    "check_ids": [f["check_id"]], "file": f["file"],
                    "lines": f.get("lines", []), "description": f["description"],
                    "triage_hint": _hint(f["check_id"]),
                }
    findings = _group_same_bug(list(merged.values()))
    findings = sorted(findings,
                      key=lambda x: config.SEVERITY_RANK.get(x["severity"], 0), reverse=True)
    from collections import Counter
    sev = Counter(f["severity"] for f in findings)
    blocking = [f for f in findings if f["severity"] in config.BADGE_BLOCKS_ON]
    return {
        "tools_ran": tools_ran, "tools_failed": tools_failed,
        "total": len(findings), "by_severity": dict(sev),
        "badge_blocking_count": len(blocking),
        "findings": findings,
    }

if __name__ == "__main__":
    from ingest import tool_slither, tool_aderyn
    import os
    os.chdir(str(config.FOUNDRY_ROOT))
    sl = tool_slither.run("src/TapMarket.sol")
    ad = tool_aderyn.run()
    bundle = normalize(sl, ad)
    print(f"tools ran: {bundle['tools_ran']} | failed: {bundle['tools_failed']}")
    print(f"total findings: {bundle['total']} | by severity: {bundle['by_severity']}")
    print(f"badge-blocking (high/medium): {bundle['badge_blocking_count']}")
    print("--- blocking findings (would gate the badge until exploit-tested) ---")
    for f in bundle["findings"]:
        if f["severity"] in config.BADGE_BLOCKS_ON:
            print(f"  [{f['severity']}] {f['tools']} {f['check_ids']} @ {f['file']}:{f['lines'][:1]}")
            print(f"     hint: {f['triage_hint']}")
