"""crucible.py — the orchestrator. One call audits a contract suite end to end:
  Layer 1 (scan) -> Layer 2 (Red/White/Judge triage) -> Layer 3 (generate + sandbox-prove)
  -> per-finding verdict + overall badge decision.
Ground truth preserved throughout; a badge issues ONLY if zero high/medium defects remain
sandbox-confirmed-exploitable and nothing is disputed/unresolved."""
import sys, json, time, shutil, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, logging_setup
from ingest import runner as ingest_runner
from adversarial.red_agent import prosecute
from adversarial.white_agent import defend
from adversarial.judge_agent import arbitrate
from adversarial import exploit_generator

def _code_context(finding, foundry_root):
    """Read the flagged file (full — contracts are small enough) for the agents."""
    fp = Path(foundry_root) / finding["file"]
    try:
        return fp.read_text()
    except Exception:
        return f"// could not read {finding['file']}"

def _sandbox_prove(finding, code, red, run_dir, log):
    """Generate a proving test and run it against the current (unpatched) target.
    Returns ('confirmed'|'not_confirmed'|'inconclusive', detail)."""
    gen = exploit_generator.generate(finding, code, red, run_dir=run_dir)
    if not gen.get("ok"):
        return "inconclusive", f"could not generate proving test: {gen.get('error')}"
    sbx = Path(gen["sandbox"])
    forge = config.ANVIL_BIN.replace("anvil", "forge")
    subprocess.run([forge, "clean"], cwd=sbx, capture_output=True)
    r = subprocess.run([forge, "test", "--match-path", "test/Generated.t.sol"],
                       cwd=sbx, capture_output=True, text=True, timeout=180)
    passed = "[PASS]" in r.stdout
    logging_setup.save_raw(run_dir, f"sandbox_{finding['file'].replace('/','_')}_{finding['lines'][:1]}.txt", r.stdout + r.stderr)
    # test PASSES on vulnerable code => defect is real and exploitable
    return ("confirmed" if passed else "not_confirmed"), ("exploit test passed on current code" if passed else "exploit test did not pass — defect not demonstrated")

def audit(target=None, deep=False, do_sandbox=True):
    target = target or "src"
    run_dir = logging_setup.new_run_dir()
    log = logging_setup.get_logger(run_dir)
    froot = str(config.FOUNDRY_ROOT)
    log.info(f"=== CRUCIBLE AUDIT: {target} ===")

    # Layer 1
    bundle = ingest_runner.audit(target, deep=deep)
    blocking = [f for f in bundle["findings"] if f["severity"] in config.BADGE_BLOCKS_ON]
    log.info(f"Layer 1: {bundle['total']} findings, {len(blocking)} high/medium to adjudicate")

    verdicts = []
    for f in blocking:
        code = _code_context(f, froot)
        red = prosecute(f, code, run_dir=run_dir)
        if red.get("error"):
            verdicts.append({**_slim(f), "disposition": "error", "detail": "reasoning refused/failed"}); continue
        white = defend(f, code, red, run_dir=run_dir)
        judge = arbitrate(f, red, white, run_dir=run_dir)
        entry = {**_slim(f), "red_exploitable": red.get("exploitable"),
                 "white_agrees": white.get("agree_with_red"), "judge": judge.get("verdict"),
                 "needs_human": judge.get("needs_human")}

        # Layer 3: sandbox-prove when the debate says real (or is disputed) and sandbox is on
        if do_sandbox and (red.get("exploitable") or judge.get("needs_human")):
            status, detail = _sandbox_prove(f, code, red, run_dir, log)
            entry["sandbox"] = status; entry["sandbox_detail"] = detail
            red_expected_bug = red.get("exploitable")
            if status == "confirmed":
                entry["disposition"] = "CONFIRMED_DEFECT"          # proven real -> block
            elif status == "not_confirmed":
                # exploit ran but did NOT demonstrate the defect
                entry["disposition"] = "cleared_by_failed_exploit"  # tried, couldn't break it
            else:  # inconclusive: couldn't build a working exploit
                if red_expected_bug:
                    entry["disposition"] = "UNRESOLVED"             # Red suspected a bug, unproven -> block + human
                    entry["needs_human"] = True
                else:
                    entry["disposition"] = "cleared_consistent"     # Red=safe, White=safe, no exploit buildable -> clear
        elif judge.get("verdict") == "dismissed_cosmetic":
            entry["disposition"] = "dismissed_cosmetic"
        else:
            entry["disposition"] = "needs_sandbox" if do_sandbox else "debate_only"
        verdicts.append(entry)
        log.info(f"  {f['file']}:{f['lines'][:1]} [{f['severity']}] -> {entry['disposition']}")

    confirmed = [v for v in verdicts if v.get("disposition") == "CONFIRMED_DEFECT"]
    unresolved = [v for v in verdicts if v.get("disposition") in ("UNRESOLVED", "error", "needs_sandbox")]
    # cleared_consistent and cleared_by_failed_exploit and dismissed_cosmetic do NOT block
    disputed = [v for v in verdicts if v.get("needs_human")]
    badge = (len(confirmed) == 0 and len(unresolved) == 0 and len(disputed) == 0)

    report = {"target": target, "run_id": run_dir.name,
              "scanned": bundle["by_severity"], "adjudicated": len(blocking),
              "confirmed_defects": len(confirmed), "unresolved": len(unresolved),
              "disputed": len(disputed), "badge_eligible": badge, "verdicts": verdicts}
    (config.OUT_DIR / run_dir.name / "audit_report.json").write_text(json.dumps(report, indent=2))
    log.info(f"=== VERDICT: badge_eligible={badge} | confirmed={len(confirmed)} unresolved={len(unresolved)} disputed={len(disputed)} ===")
    return report

def _slim(f):
    return {"file": f["file"], "lines": f["lines"][:2], "severity": f["severity"], "detectors": f.get("check_ids", f.get("check_id"))}

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/home/dburnett11155/taprouter/.env.local")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="src/TapMarket.sol")
    ap.add_argument("--no-sandbox", action="store_true")
    a = ap.parse_args()
    import os; os.chdir(str(config.FOUNDRY_ROOT))
    rep = audit(a.target, do_sandbox=not a.no_sandbox)
    print(json.dumps({k: rep[k] for k in ("target","scanned","adjudicated","confirmed_defects","unresolved","disputed","badge_eligible")}, indent=2))
