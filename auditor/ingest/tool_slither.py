"""Slither wrapper — runs slither, normalizes findings to Crucible's schema.
Findings are GROUND TRUTH: severity from the tool, never overridden by an LLM.
Exploitability triage happens later in the adversarial layer, not here."""
import json, subprocess, sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# Slither impact -> Crucible severity
_SEV = {"High": "high", "Medium": "medium", "Low": "low",
        "Informational": "informational", "Optimization": "optimization"}

def run(target: str, foundry_root: str = None) -> dict:
    """Run Slither on a target (file or dir). Returns:
       {tool, ok, findings:[...], raw_path, error}"""
    foundry_root = foundry_root or str(config.FOUNDRY_ROOT)
    out_json = os.path.join("/tmp", f"slither_{os.getpid()}_{next(tempfile._get_candidate_names())}.json")
    cmd = [config.SLITHER_BIN, target, "--json", out_json]
    try:
        proc = subprocess.run(cmd, cwd=foundry_root, capture_output=True,
                              text=True, timeout=config.SLITHER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"tool": "slither", "ok": False, "findings": [], "raw_path": None,
                "error": f"timeout after {config.SLITHER_TIMEOUT}s"}
    # Slither exits non-zero WHEN IT FINDS ISSUES — that's success, not failure.
    # Real failure = no JSON produced.
    if not os.path.exists(out_json) or os.path.getsize(out_json) == 0:
        return {"tool": "slither", "ok": False, "findings": [], "raw_path": None,
                "error": f"no output; stderr: {proc.stderr[-500:]}"}
    data = json.load(open(out_json))
    dets = data.get("results", {}).get("detectors", [])
    findings = []
    for r in dets:
        elems = r.get("elements", [])
        src = elems[0].get("source_mapping", {}) if elems else {}
        if any(p in "/" + (src.get("filename_relative","") or "") for p in config.SKIP_PATTERNS):
            continue
        findings.append({
            "tool": "slither",
            "severity": _SEV.get(r.get("impact"), "informational"),
            "confidence": r.get("confidence", "").lower(),
            "check_id": r.get("check", ""),
            "file": src.get("filename_relative", ""),
            "lines": src.get("lines", []),
            "description": r.get("description", "").strip(),
        })
    return {"tool": "slither", "ok": True, "findings": findings,
            "raw_path": out_json, "error": None}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="src/TapMarket.sol")
    a = ap.parse_args()
    res = run(a.target)
    from collections import Counter
    if res["ok"]:
        sev = Counter(f["severity"] for f in res["findings"])
        print(f"slither: {len(res['findings'])} findings — "
              f"high={sev['high']} medium={sev['medium']} low={sev['low']} info={sev['informational']}")
        for f in res["findings"]:
            if f["severity"] in ("high", "medium"):
                print(f"  [{f['severity']}] {f['check_id']} @ {f['file']}:{f['lines'][:2]} — {f['description'][:70]}")
    else:
        print("slither FAILED:", res["error"])
