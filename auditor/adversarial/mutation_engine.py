"""mutation_engine.py — deterministic bug-injection operators for Crucible's invariant meta-oracle.

WHY: a machine-generated invariant is only trustworthy if it PROVABLY catches bugs. We inject
known bugs into a copy of the target and confirm the invariant fires. This is the bug-injector.
Each operator produces a SPECIFIC known defect. A non-compiling mutant is skipped downstream —
harmless — so regex fragility costs YIELD, never CORRECTNESS.
Each operator returns (mutated_source | None, description). None = pattern not present.
"""
import re


def op_flip_comparison(code):
    """Boundary bug: flip first strict inequality to non-strict (> -> >=, < -> <=)."""
    m = re.search(r'(?<![<>=])([<>])(?![=<>])', code)
    if not m:
        return None, "no strict inequality found"
    i = m.start()
    return code[:i] + m.group(1) + "=" + code[i+1:], f"flipped '{m.group(1)}' -> '{m.group(1)}=' (boundary bug)"


def op_remove_require(code):
    """Missing-validation bug: delete the first require(...) statement."""
    m = re.search(r'\n[ \t]*require\s*\([^;]*\);', code)
    if not m:
        return None, "no require statement found"
    return code[:m.start()] + code[m.end():], "removed require statement (missing validation)"


def op_remove_zeroing(code):
    """Reentrancy-class bug: delete a state-reset assignment (x = 0;)."""
    m = re.search(r'\n[ \t]*[\w\[\].]+\s*=\s*0\s*;', code)
    if not m:
        return None, "no zeroing assignment found"
    return code[:m.start()] + code[m.end():], f"removed zeroing '{m.group(0).strip()}' (reentrancy)"


def op_reorder_cei(code):
    """CEI-violation bug: move a state-zeroing to AFTER the next external .transfer(...)."""
    zero = re.search(r'\n([ \t]*)([\w\[\].]+\s*=\s*0\s*;)', code)
    xfer = re.search(r'\n[ \t]*[\w.]+\.transfer\([^;]*\);', code)
    if not zero or not xfer:
        return None, "need both a zeroing and a .transfer() call"
    if zero.start() > xfer.start():
        return None, "already CEI-unsafe (zero after transfer)"
    zline = zero.group(2); indent = zero.group(1)
    code_nz = code[:zero.start()] + code[zero.end():]
    xfer2 = re.search(r'\n[ \t]*[\w.]+\.transfer\([^;]*\);', code_nz)
    if not xfer2:
        return None, "transfer vanished after removing zeroing"
    at = xfer2.end()
    return code_nz[:at] + "\n" + indent + zline + code_nz[at:], "moved zeroing AFTER transfer (CEI violation)"


def op_weaken_access(code):
    """Broken-access-control bug: strip first access modifier (onlyOwner/onlyRole/...)."""
    m = re.search(r'\b(onlyOwner|onlyRole\s*\([^)]*\)|onlyAdmin|onlyGovernance)\b', code)
    if not m:
        return None, "no access modifier found"
    mutated = code[:m.start()] + code[m.end():]
    return re.sub(r'[ \t]{2,}', ' ', mutated), f"stripped '{m.group(1)}' (broken access control)"


OPERATORS = {
    "flip_comparison": op_flip_comparison,
    "remove_require": op_remove_require,
    "remove_zeroing": op_remove_zeroing,
    "reorder_cei": op_reorder_cei,
    "weaken_access": op_weaken_access,
}


def mutate(code, operator):
    if operator not in OPERATORS:
        return None, f"unknown operator: {operator}"
    return OPERATORS[operator](code)


def all_mutants(code):
    for name, fn in OPERATORS.items():
        mutated, desc = fn(code)
        if mutated is not None and mutated != code:
            yield name, mutated, desc
