"""runner.py — Layer 1 orchestrator. Runs scanners concurrently against a target,
normalizes to one bundle, writes it to out/<run_id>/, logs everything.
This is the entry point: `python -m auditor.ingest.runner [target]`."""
import os, sys, json, time, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, logging_setup
from ingest import tool_slither, tool_aderyn, tool_mythril, normalize


def _top_level_commas(expr):
    """Count commas at paren-depth 0 within expr."""
    depth = 0; n = 0
    for ch in expr:
        if ch in "([{": depth += 1
        elif ch in ")]}": depth -= 1
        elif ch == "," and depth == 0: n += 1
    return n


def _extract_call_args(src, method):
    """Return the argument string inside the first .method(...) call, or None."""
    m = re.search(r'\.' + method + r'\s*\(', src)
    if not m:
        return None
    i = m.end() - 1  # at the '('
    depth = 0; out = []
    for ch in src[i:]:
        out.append(ch)
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                break
    inner = "".join(out)
    return inner[1:-1] if inner.startswith("(") and inner.endswith(")") else None


def _suppress_misclassified(findings, froot):
    """Drop unsafe-erc20-operation findings whose flagged line is a NATIVE-ETH transfer.

    ERC20 transfer/transferFrom is two-arg (to, amount) / three-arg; native
    payable(x).transfer(amount) / .send(amount) is ONE-arg. Argument count is the
    definitional discriminator and never confuses the two. This corrects a provable
    Aderyn misclassification (it pattern-matches `.transfer`/`.send` tokens without
    checking the receiver type). Real IERC20(x).transfer(to, amount) findings are kept.
    """
    kept = []
    dropped = 0
    for f in findings:
        ids = list(f.get("check_ids") or ([f["check_id"]] if f.get("check_id") else []))
        if "unsafe-erc20-operation" in ids:
            native = False
            try:
                lines = open(os.path.join(froot, f["file"])).read().splitlines()
            except Exception:
                lines = None
            if lines:
                for ln in (f.get("lines") or []):
                    if 1 <= ln <= len(lines):
                        src = lines[ln - 1]
                        for meth in ("transfer", "send"):
                            args = _extract_call_args(src, meth)
                            if args is not None and args.strip():
                                if _top_level_commas(args) == 0:
                                    native = True
            if native:
                # Remove ONLY the misclassified detector, preserving any real detectors
                # merged into the same finding (e.g. arbitrary-send-eth on the same line).
                remaining = [d for d in ids if d != "unsafe-erc20-operation"]
                dropped += 1
                if remaining:
                    f = dict(f)
                    f["check_ids"] = remaining
                    kept.append(f)
                # else: unsafe-erc20-operation was the sole detector -> drop the finding
                continue
        kept.append(f)
    return kept, dropped


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
    # Suppress provably-misclassified findings (native-ETH transfer flagged as ERC20).
    from collections import Counter as _Counter
    _kept, _dropped = _suppress_misclassified(bundle["findings"], str(config.FOUNDRY_ROOT))
    if _dropped:
        bundle["findings"] = _kept
        bundle["total"] = len(_kept)
        bundle["by_severity"] = dict(_Counter(f["severity"] for f in _kept))
        bundle["badge_blocking_count"] = len([f for f in _kept if f["severity"] in config.BADGE_BLOCKS_ON])
        bundle["suppressed_misclassified"] = _dropped
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
