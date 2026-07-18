"""runner.py — Layer 1 orchestrator. Runs scanners concurrently against a target,
normalizes to one bundle, writes it to out/<run_id>/, logs everything.
This is the entry point: `python -m auditor.ingest.runner [target]`."""
import sys, json, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, logging_setup
from ingest import tool_slither, tool_aderyn, tool_mythril, normalize

def audit(target: str = None, deep: bool = False) -> dict:
    """Run Layer 1 ingestion on a target. Returns the normalized bundle."""
    target = target or "src"
    run_dir = logging_setup.new_run_dir()
    log = logging_setup.get_logger(run_dir)
    t0 = time.time()
    log.info(f"Crucible ingestion — target: {target} | deep: {deep}")

    # Slither + Aderyn run concurrently (both fast). Mythril is opt-in and serial (slow).
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_sl = ex.submit(tool_slither.run, target)
        f_ad = ex.submit(tool_aderyn.run)
        for name, fut in (("slither", f_sl), ("aderyn", f_ad)):
            r = fut.result()
            results.append(r)
            status = f"{len(r['findings'])} findings" if r["ok"] else f"FAILED: {r['error']}"
            log.info(f"  {name}: {status}")
            if r.get("raw_path"):
                try: logging_setup.save_raw(run_dir, f"{name}_raw.json", Path(r["raw_path"]).read_text())
                except Exception: pass

    if deep and config.MYTHRIL_ENABLED:
        log.info("  mythril: running (slow symbolic pass)...")
        r = tool_mythril.run(target)
        results.append(r)
        log.info(f"  mythril: {'ok' if r['ok'] else r['error']}")

    bundle = normalize.normalize(*results)
    bundle["target"] = target
    bundle["run_id"] = run_dir.name
    bundle["elapsed_s"] = round(time.time() - t0, 1)

    out_dir = config.OUT_DIR / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bundle.json").write_text(json.dumps(bundle, indent=2))
    logging_setup.save_raw(run_dir, "bundle.json", json.dumps(bundle, indent=2))

    log.info(f"Ingestion complete in {bundle['elapsed_s']}s — "
             f"{bundle['total']} findings, {bundle['badge_blocking_count']} badge-blocking")
    log.info(f"Bundle: {out_dir / 'bundle.json'}")
    return bundle

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="src")
    ap.add_argument("--deep", action="store_true", help="include Mythril symbolic pass")
    a = ap.parse_args()
    import os
    os.chdir(str(config.FOUNDRY_ROOT))
    b = audit(a.target, deep=a.deep)
    print(f"\n=== {b['by_severity']} | blocking: {b['badge_blocking_count']} | {b['elapsed_s']}s ===")
