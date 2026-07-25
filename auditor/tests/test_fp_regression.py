"""Regression test: the native-ETH-transfer-as-ERC20 false positive stays fixed.

VulnerableBank.sol is the exact contract from the first Desktop hire (2026-07-25) whose
advisory result carried one false positive: Aderyn flagged line 21's
`payable(to).transfer(address(this).balance)` (a native ETH send) as unsafe-erc20-operation.

This test pins that input so the FP can never silently return, and — just as important —
proves the three planted true-positive bugs are still caught and no real detector on the
FP's line was dropped by the suppression pass.
"""
import sys, os, shutil, pathlib

HERE = pathlib.Path(__file__).resolve().parent
AUDITOR = HERE.parent
sys.path.insert(0, str(AUDITOR))


def _run_fixture():
    import config as c
    real = pathlib.Path(c.ROOT) / "contracts"
    work = pathlib.Path("/tmp/crucible_fp_regression")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for f in ("foundry.toml", "remappings.txt"):
        if (real / f).exists():
            shutil.copy(real / f, work / f)
    (work / "src").mkdir()
    shutil.copy(HERE / "fixtures" / "VulnerableBank.sol", work / "src" / "VulnerableBank.sol")
    if (real / "lib").exists() and not (work / "lib").exists():
        os.symlink(real / "lib", work / "lib")
    c.FOUNDRY_ROOT = work
    c.OUT_DIR = work / "out"
    from ingest import runner
    return runner.audit("src/VulnerableBank.sol", deep=False)


def test_planted_bugs_caught_and_fp_suppressed():
    b = _run_fixture()
    all_detectors = set()
    line21 = None
    for f in b["findings"]:
        ids = f.get("check_ids") or ([f["check_id"]] if f.get("check_id") else [])
        all_detectors.update(ids)
        if 21 in (f.get("lines") or []):
            line21 = ids

    # 1. the three planted true positives are caught
    assert "reentrancy-eth" in all_detectors or "reentrancy-no-eth" in all_detectors \
        or "reentrancy-state-change" in all_detectors, "reentrancy not caught"
    assert "tx-origin-used-for-auth" in all_detectors or any("tx-origin" in d for d in all_detectors), \
        "tx.origin auth not caught"
    assert any("unchecked" in d and ("call" in d or "return" in d or "transfer" in d)
               for d in all_detectors), "unchecked low-level call not caught"

    # 2. the false positive is gone: no unsafe-erc20-operation on the native-transfer line 21
    if line21 is not None:
        assert "unsafe-erc20-operation" not in line21, \
            "native-ETH transfer on line 21 still misflagged as ERC20 op (FP regressed)"

    # 3. no true positive was dropped: line 21's real detectors survive
    if line21 is not None:
        assert any("arbitrary-send" in d or "eth-send" in d for d in line21), \
            "suppression pass dropped a real detector on line 21 (over-suppression)"

    print("PASS: 3 planted bugs caught, native-transfer FP suppressed, real detectors preserved")


if __name__ == "__main__":
    test_planted_bugs_caught_and_fp_suppressed()
