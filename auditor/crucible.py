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

def _persist_sandbox(sbx, finding, run_dir, forge_output, phase="exploit"):
    """Copy a sandbox's proof artifacts into the run dir so evidence survives the next
    finding wiping /tmp. Layout: run_dir/sandbox/<phase>_<file>_<line>/{Generated.t.sol,
    target.sol, forge_output.txt}. Best-effort — never let persistence failure break a run."""
    import shutil as _sh
    try:
        from pathlib import Path as _P
        sbx = _P(sbx)
        tag = f"{phase}_{finding['file'].replace('/','_')}_{(finding.get('lines') or ['x'])[0]}"
        dest = _P(run_dir) / "sandbox" / tag
        dest.mkdir(parents=True, exist_ok=True)
        gen_t = sbx / "test" / "Generated.t.sol"
        if gen_t.exists():
            _sh.copy(gen_t, dest / "Generated.t.sol")
        src_dir = sbx / "src"
        if src_dir.exists():
            tgt = src_dir / _P(finding["file"]).name
            if tgt.exists():
                _sh.copy(tgt, dest / _P(finding["file"]).name)
        (dest / "forge_output.txt").write_text(forge_output[:20000])
        return str(dest)
    except Exception as e:
        return f"persist_failed: {type(e).__name__}: {e}"

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
    passed_vuln = "[PASS]" in r.stdout
    logging_setup.save_raw(run_dir, f"sandbox_{finding['file'].replace('/','_')}_{finding['lines'][:1]}.txt", r.stdout + r.stderr)
    # PERSIST the proving artifact before the next finding clobbers /tmp. A certification
    # tool must retain the proof of what it certified — the .t.sol, the target, forge output.
    _persist_sandbox(sbx, finding, run_dir, r.stdout + r.stderr, phase="exploit")
    if not passed_vuln:
        return "not_confirmed", "exploit test did not pass on current code — defect not demonstrated"
    # DIFFERENTIAL POLARITY CHECK: a test that passes on vulnerable code is only a valid
    # proof if it FAILS on patched code. Otherwise it may be passing vacuously / wrong-polarity.
    flipped, detail = _differential_flip(sbx, finding, code, forge, run_dir)
    if flipped is True:
        return "confirmed", "exploit passed on vulnerable code AND failed on patched copy (polarity verified)"
    if flipped is False:
        return "inconclusive", f"exploit passed on BOTH vulnerable and patched code — not a valid proof ({detail})"
    return "inconclusive", f"polarity unverifiable ({detail}) — routing to human"

def _differential_flip(sbx, finding, code, forge, run_dir):
    """Apply a mechanical fix to a copy of the target and rerun the SAME test.
    Returns (True flipped / False no-flip / None unverifiable, detail).
    Currently handles the CEI-reorder reentrancy class; other classes return None (-> human)."""
    import re
    patched = _mechanical_patch(code)
    if patched is None:
        return None, "no mechanical patch for this defect class"
    if patched == code:
        return None, "mechanical patch made no change"
    tgt = sbx / "src" / Path(finding["file"]).name
    original = tgt.read_text()
    try:
        tgt.write_text(patched)
        subprocess.run([forge, "clean"], cwd=sbx, capture_output=True)
        pr = subprocess.run([forge, "test", "--match-path", "test/Generated.t.sol"],
                            cwd=sbx, capture_output=True, text=True, timeout=180)
        logging_setup.save_raw(run_dir, f"patched_{finding['file'].replace('/','_')}_{finding['lines'][:1]}.txt", pr.stdout + pr.stderr)
        passed_on_patched = "[PASS]" in pr.stdout
        compiled = "Compiler run failed" not in pr.stdout and "Error" not in pr.stderr[:200]
        if not compiled:
            return None, "patched copy failed to compile"
        return (not passed_on_patched), ("test failed on patched (good)" if not passed_on_patched else "test still passed on patched (bad)")
    finally:
        tgt.write_text(original)

def _mechanical_patch(code):
    """Deterministic fix for the CEI-violation reentrancy class: move a
    `balances[...] = 0;` (state zeroing) to BEFORE the external `.transfer(` call.
    Returns patched code, or None if the pattern isn't recognized (other bug class)."""
    import re
    zero = re.search(r'\n(\s*)(balances\[[^\]]+\]\s*=\s*0\s*;)', code)
    xfer = re.search(r'\n\s*[\w.]+\.transfer\([^;]*\);', code)
    if not zero or not xfer:
        return None
    if zero.start() < xfer.start():
        return None  # already CEI-safe, nothing to flip
    zline = zero.group(2)
    indent = zero.group(1)
    code_no_zero = code[:zero.start()] + code[zero.end():]
    xfer2 = re.search(r'\n(\s*)([\w.]+\.transfer\([^;]*\);)', code_no_zero)
    if not xfer2:
        return None
    injected = "\n" + xfer2.group(1) + zline + code_no_zero[xfer2.start():]
    return code_no_zero[:xfer2.start()] + injected

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
        try:
            red = prosecute(f, code, run_dir=run_dir)
            if red.get("error"):
                verdicts.append({**_slim(f), "disposition": "error", "needs_human": True, "detail": "reasoning refused/failed"}); continue
            white = defend(f, code, red, run_dir=run_dir)
            judge = arbitrate(f, red, white, run_dir=run_dir)
        except Exception as e:
            # One finding's model failure must never kill the whole audit.
            # "error" blocks the badge and routes to human; the run completes.
            verdicts.append({**_slim(f), "disposition": "error", "needs_human": True,
                             "detail": f"adjudication failed: {type(e).__name__}: {str(e)[:160]}"})
            continue
        entry = {**_slim(f), "red_exploitable": red.get("exploitable"),
                 "white_agrees": white.get("agree_with_red"), "judge": judge.get("verdict"),
                 "needs_human": judge.get("needs_human")}

        # Disposition. The sandbox CONFIRMS Red's exploitable claims and breaks ties —
        # it is NOT needed to re-clear a finding Red+White already judged safe.
        red_says_bug = red.get("exploitable")
        # Use White's EXPLICIT agree_with_red signal, not an inferred field comparison.
        # A real dispute is only when White explicitly says it does NOT agree with Red.
        red_white_disagree = (white.get("agree_with_red") is False)
        if judge.get("verdict") == "dismissed_cosmetic":
            entry["disposition"] = "dismissed_cosmetic"
        elif red_white_disagree or judge.get("needs_human"):
            # genuine dispute -> try sandbox to break the tie, else human
            if do_sandbox:
                status, detail = _sandbox_prove(f, code, red, run_dir, log)
                entry["sandbox"] = status; entry["sandbox_detail"] = detail
                if status == "confirmed":
                    entry["disposition"] = "CONFIRMED_DEFECT"
                else:
                    entry["disposition"] = "disputed_needs_human"; entry["needs_human"] = True
            else:
                entry["disposition"] = "disputed_needs_human"; entry["needs_human"] = True
        elif red_says_bug:
            # Red says exploitable and White agrees -> PROVE it in the sandbox
            if do_sandbox:
                status, detail = _sandbox_prove(f, code, red, run_dir, log)
                entry["sandbox"] = status; entry["sandbox_detail"] = detail
                if status == "confirmed":
                    entry["disposition"] = "CONFIRMED_DEFECT"
                elif status == "not_confirmed":
                    entry["disposition"] = "cleared_by_failed_exploit"
                else:
                    entry["disposition"] = "UNRESOLVED"; entry["needs_human"] = True  # claimed bug, unproven
            else:
                entry["disposition"] = "needs_sandbox"
        else:
            # Red says NOT exploitable and White agrees -> cleared by debate (two safe signals)
            entry["disposition"] = "cleared_by_debate"
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
