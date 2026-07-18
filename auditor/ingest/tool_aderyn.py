"""Aderyn wrapper — Rust access-control/permission scanner. Normalizes to Crucible schema.
Aderyn buckets findings as high/low only. Ground truth like Slither; triage is downstream.
Known detector weakness (documented from live TapVault run): reentrancy-state-change fires
on balanceOf VIEW calls and is guard-blind — the adversarial layer must exploit-test, not trust."""
import json, subprocess, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

def run(target_dir: str = None, foundry_root: str = None) -> dict:
    """Run Aderyn on the foundry project. Returns {tool, ok, findings, raw_path, error}."""
    foundry_root = foundry_root or str(config.FOUNDRY_ROOT)
    if not os.path.exists(config.ADERYN_BIN):
        return {"tool": "aderyn", "ok": False, "findings": [], "raw_path": None,
                "error": "aderyn binary not found — skipped"}
    out_json = os.path.join("/tmp", f"aderyn_{os.getpid()}.json")
    cmd = [config.ADERYN_BIN, ".", "-o", out_json]
    try:
        proc = subprocess.run(cmd, cwd=foundry_root, capture_output=True,
                              text=True, timeout=config.ADERYN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"tool": "aderyn", "ok": False, "findings": [], "raw_path": None,
                "error": f"timeout after {config.ADERYN_TIMEOUT}s"}
    if not os.path.exists(out_json):
        return {"tool": "aderyn", "ok": False, "findings": [], "raw_path": None,
                "error": f"no output; stderr: {proc.stderr[-500:]}"}
    data = json.load(open(out_json))
    findings = []
    for bucket, sev in (("high_issues", "high"), ("low_issues", "low")):
        for issue in data.get(bucket, {}).get("issues", []):
            for inst in issue.get("instances", []):
                fpath = inst.get("contract_path", "")
                if any(p in "/" + fpath for p in config.SKIP_PATTERNS):
                    continue
                findings.append({
                    "tool": "aderyn",
                    "severity": sev,
                    "confidence": "",  # aderyn doesn't report per-finding confidence
                    "check_id": issue.get("detector_name", ""),
                    "file": fpath,
                    "lines": [inst.get("line_no")] if inst.get("line_no") else [],
                    "description": (issue.get("title", "") + " — " + issue.get("description", "")).strip()[:400],
                })
    return {"tool": "aderyn", "ok": True, "findings": findings, "raw_path": out_json, "error": None}

if __name__ == "__main__":
    res = run()
    from collections import Counter
    if res["ok"]:
        sev = Counter(f["severity"] for f in res["findings"])
        print(f"aderyn: {len(res['findings'])} findings — high={sev['high']} low={sev['low']}")
        for f in res["findings"]:
            if f["severity"] == "high":
                print(f"  [high] {f['check_id']} @ {f['file']}:{f['lines']} — {f['description'][:60]}")
    else:
        print("aderyn:", res["error"])
