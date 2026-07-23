"""invariant_pass.py — Phase 5b: the contract-level invariant phase of a Crucible audit.

The finding-level loop adjudicates what SCANNERS flagged. This pass reasons about the
CONTRACT AS A WHOLE and produces findings on the confidence ladder:

    INVARIANT_VIOLATED  — a mutation-validated invariant broke under fuzzing.
    INVARIANT_HELD      — a validated invariant survived. Evidence WITHIN BOUNDS, never
                          "safe". Does NOT earn a badge; only fails to block one.
    (discarded)         — invariants that don't discriminate claim nothing.

THREE CAPS, learned the hard way, all mandatory:
  1. MUTATION CAP — confidence == number of injected bugs provably caught. Never rounded up.
  2. COVERAGE CAP — an invariant that "held" while the functions it reads never executed is
                    NOT evidence (try/catch swallows target reverts; hollow campaigns look
                    identical to healthy ones without ghost counters).
  3. ARTIFACT SUSPICION — counterexamples using arriveTokens() may depend on a
                    protocol-impossible state; flagged, not reported as fact.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from adversarial import invariant_synth, harness_gen, mutation_engine

FORGE = str(config.ANVIL_BIN).replace("anvil", "forge")
WORK = Path("/tmp/crucible_inv_proj")


def _setup_project(project_root):
    """Copy the foundry project so mutants never touch real src/. lib/ is symlinked."""
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    root = Path(project_root)
    for f in ("foundry.toml", "remappings.txt"):
        if (root / f).exists():
            shutil.copy(root / f, WORK / f)
    shutil.copytree(root / "src", WORK / "src")
    (WORK / "test").mkdir(exist_ok=True)
    lib = root / "lib"
    if lib.exists() and not (WORK / "lib").exists():
        os.symlink(lib, WORK / "lib")


def _campaign(harness_sol, source, rel_src, runs, depth, verbose=False):
    (WORK / rel_src).write_text(source)
    (WORK / "test" / "CrucibleInv.t.sol").write_text(harness_sol)
    env = dict(os.environ,
               FOUNDRY_INVARIANT_RUNS=str(runs),
               FOUNDRY_INVARIANT_DEPTH=str(depth),
               FOUNDRY_INVARIANT_FAIL_ON_REVERT="false")
    cmd = [FORGE, "test", "--match-path", "test/CrucibleInv.t.sol"]
    if verbose:
        cmd.append("-vvv")
    r = subprocess.run(cmd, cwd=WORK, capture_output=True, text=True, timeout=1800, env=env)
    blob = r.stdout + "\n" + (r.stderr or "")
    if "Compiler run failed" in blob:
        return False, set(), blob
    failed = set()
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{") and '"event"' in line:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "failure" and ev.get("invariant"):
                failed.add(ev["invariant"])
    return True, failed, blob


def _counterexample_for(blob, inv_name):
    seq, grabbing = [], False
    for line in blob.splitlines():
        if "[Sequence]" in line:
            grabbing, seq = True, []
            continue
        if grabbing:
            if "calldata=" in line:
                m = re.search(r'calldata=(\w+)\(', line)
                if m:
                    seq.append(m.group(1))
            elif inv_name in line:
                return seq
            elif line.strip() == "":
                grabbing = False
    return seq


def run(target_files, project_root, run_dir, log=print, runs=32, depth=60):
    findings = []
    try:
        _setup_project(project_root)
    except Exception as e:
        log(f"  invariant pass: project setup failed ({e}) — skipping")
        return findings

    for rel in target_files:
        name = Path(rel).stem
        src_path = Path(project_root) / rel
        artifact = Path(project_root) / "out" / f"{name}.sol" / f"{name}.json"
        if not src_path.exists() or not artifact.exists():
            log(f"  {name}: no source/artifact — skipped (run forge build)")
            continue
        source = src_path.read_text()
        try:
            abi = json.loads(artifact.read_text())["abi"]
        except Exception:
            log(f"  {name}: unreadable artifact — skipped")
            continue

        try:
            cands = invariant_synth.synthesize(source, name, run_dir=run_dir)
        except Exception as e:
            log(f"  {name}: synthesis failed ({type(e).__name__}) — skipped")
            continue
        if not cands:
            log(f"  {name}: no candidate invariants")
            continue

        # Normalize model output into test-contract reference form before assembly.
        # CRITICAL: re-derive each name from the FINAL code. The gate matches forge failure
        # events by invariant name, and normalize() may supply a wrapper (renaming to
        # invariant_synthesized) — a stale name silently reads every result as "passed".
        import re as _re
        seen = {}
        for c in cands:
            c["foundry_code"] = invariant_synth.normalize(c.get("foundry_code", ""), abi)
            m = _re.search(r'function\s+(invariant_\w+)\s*\(', c["foundry_code"])
            if m:
                nm = m.group(1)
                # de-duplicate: two auto-wrapped candidates would both be invariant_synthesized
                if nm in seen:
                    seen[nm] += 1
                    new_nm = "%s_%d" % (nm, seen[nm])
                    c["foundry_code"] = c["foundry_code"].replace(
                        "function %s(" % nm, "function %s(" % new_nm, 1)
                    nm = new_nm
                else:
                    seen[nm] = 1
                c["name"] = nm
        harness, meta = harness_gen.generate(name, Path(rel).name, abi, source, cands)
        rel_src = str(Path("src") / Path(rel).name)

        ok, base_failed, _ = _campaign(harness, source, rel_src, runs, depth)
        if not ok:
            log(f"  {name}: harness did not compile — invariant pass skipped")
            continue

        caught = {c["name"]: [] for c in cands if c.get("name")}
        for op, mutant, _desc in mutation_engine.all_mutants(source):
            ok_m, failed_m, _ = _campaign(harness, mutant, rel_src, runs, depth)
            if not ok_m:
                continue
            for n in caught:
                if n in failed_m:
                    caught[n].append(op)

        survivors = [c for c in cands
                     if c.get("name") and c["name"] not in base_failed and caught.get(c["name"])]
        discarded = [c["name"] for c in cands if c.get("name") and c not in survivors]
        log(f"  {name}: {len(survivors)}/{len(cands)} invariants validated (discarded: {discarded or 'none'})")
        if not survivors:
            continue

        ok_r, failed_r, blob = _campaign(harness, source, rel_src, runs, depth, verbose=True)
        (Path(run_dir) / "sandbox").mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / "sandbox" / f"invariants_{name}.t.sol").write_text(harness)
        (Path(run_dir) / "sandbox" / f"invariants_{name}_output.txt").write_text(blob[:40000])

        for c in survivors:
            n = c["name"]
            cap = len(caught[n])
            base = {"file": rel, "invariant": n, "property": c.get("property", ""),
                    "mutants_caught": caught[n], "confidence_cap": cap}
            if n in failed_r:
                seq = _counterexample_for(blob, n)
                suspected = "arriveTokens" in seq
                base.update({
                    "disposition": "INVARIANT_VIOLATED",
                    "counterexample": seq,
                    "needs_human": True,
                    "harness_artifact_suspected": suspected,
                    "detail": ("counterexample uses arriveTokens (generic out-of-band minting) — "
                               "may depend on a protocol-impossible state; verify by hand"
                               if suspected else "fuzzer found a violating call sequence"),
                })
            else:
                base.update({
                    "disposition": "INVARIANT_HELD",
                    "needs_human": False,
                    "detail": (f"held over {runs} runs x {depth} depth; validated against {cap} "
                               f"injected bug(s). Evidence within bounds — NOT proof of safety."),
                })
            findings.append(base)
            log(f"    {n} -> {base['disposition']} (cap={cap})")

    return findings
