"""mutation_gate.py — Phase 4: THE META-ORACLE. Decides mechanically which candidate
invariants are trustworthy.

An invariant is trusted ONLY if it DISCRIMINATES:
  - PASSES on clean baseline code (it isn't vacuously failing), AND
  - FAILS on >= 1 injected mutant (it actually detects bugs).
Invariants that pass on everything test nothing. Invariants that fail on everything are
artifacts. Both are DISCARDED — mechanically, no opinion involved.

Confidence is capped by mutation DIVERSITY: an invariant that caught 1 mutant is weaker
evidence than one that caught 3. Never report more confidence than the mutant set earned.
"""
import subprocess, tempfile, shutil
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from adversarial import invariant_harness, mutation_engine

FORGE = str(config.ANVIL_BIN).replace("anvil", "forge")
TOML = ('[profile.default]\nsrc = "src"\nout = "out"\nlibs = ["lib"]\n'
        '[invariant]\nruns = {runs}\ndepth = {depth}\nfail_on_revert = false\n')


def _run_campaign(source, target_file, target_name, invariants, runs, depth, only=None):
    """Run the invariant campaign. Returns (compiled, {invariant_name: 'pass'|'fail'})."""
    sbx = Path(tempfile.mkdtemp(prefix="mgate_"))
    try:
        subprocess.run([FORGE, "init", "--force", "--no-git"], cwd=sbx, capture_output=True)
        (sbx / "foundry.toml").write_text(TOML.format(runs=runs, depth=depth))
        (sbx / "src" / target_file).write_text(source)
        (sbx / "test" / "Invariants.t.sol").write_text(
            invariant_harness.assemble(target_file, target_name, invariants))
        cmd = [FORGE, "test", "--match-path", "test/Invariants.t.sol"]
        if only:
            cmd += ["--match-test", only]
        r = subprocess.run(cmd, cwd=sbx, capture_output=True, text=True, timeout=900)
        out = r.stdout
        if "Compiler run failed" in out or "Error (" in out:
            return False, {}
        # Forge emits STRUCTURED JSON failure events (stderr and/or stdout), one per failing
        # invariant: {"event":"failure","invariant":"invariant_x","reason":"..."}.
        # Parse those instead of scraping [FAIL: ...] lines — the bracket lines do NOT
        # contain the invariant name (it appears on a separate indented line).
        import json as _json
        blob = out + "\n" + (r.stderr or "")
        failed = set()
        for line in blob.splitlines():
            line = line.strip()
            if not (line.startswith("{") and '"event"' in line):
                continue
            try:
                ev = _json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "failure" and ev.get("invariant"):
                failed.add(ev["invariant"])
        results = {}
        for inv in invariants:
            name = inv.get("name") or ""
            if not name:
                continue
            results[name] = "fail" if name in failed else "pass"
        return True, results
    finally:
        shutil.rmtree(sbx, ignore_errors=True)


def validate(source, target_file, target_name, invariants, runs=32, depth=50, log=print):
    """Return per-invariant validation records. Only VALIDATED invariants may certify."""
    # 1. Clean baseline. If invariants fail on `source`, the source itself is buggy —
    #    mechanically patch it to get non-buggy baseline code to mutate.
    baseline_src, baseline_note = source, "target as-is"
    ok, res = _run_campaign(source, target_file, target_name, invariants, runs, depth)
    if not ok:
        return {"error": "baseline did not compile"}
    if any(v == "fail" for v in res.values()):
        from crucible import _mechanical_patch
        patched = _mechanical_patch(source)
        if patched and patched != source:
            ok2, res2 = _run_campaign(patched, target_file, target_name, invariants, runs, depth)
            if ok2 and not any(v == "fail" for v in res2.values()):
                baseline_src, res, baseline_note = patched, res2, "mechanically patched"
    log(f"  baseline ({baseline_note}): {res}")

    records = {}
    for inv in invariants:
        name = inv.get("name", "")
        records[name] = {
            "baseline": res.get(name, "missing"),
            "caught": [], "missed": [], "validated": False,
        }

    # 2. Mutate the CLEAN baseline; a good invariant must catch injected bugs.
    for op_name, mutant_src, desc in mutation_engine.all_mutants(baseline_src):
        ok_m, res_m = _run_campaign(mutant_src, target_file, target_name, invariants, runs, depth)
        if not ok_m:
            log(f"  mutant {op_name}: SKIP (no compile)")
            continue
        for inv in invariants:
            name = inv.get("name", "")
            if res_m.get(name) == "fail":
                records[name]["caught"].append(op_name)
            else:
                records[name]["missed"].append(op_name)
        log(f"  mutant {op_name}: {res_m}  ({desc})")

    # 3. Verdict: must pass clean baseline AND catch >= 1 mutant.
    for name, rec in records.items():
        rec["validated"] = (rec["baseline"] == "pass" and len(rec["caught"]) >= 1)
        rec["confidence_cap"] = len(rec["caught"])
    return records
