"""dep_resolver.py — Phase 5c component 1: constructor dependency resolution.

The generalized harness could only deploy contracts whose constructor took a token-ish address
(mock ERC20) or bare values. Contracts with real dependencies — TapMessenger needs an ITapVault,
TapRouter a CCTP messenger — failed to deploy, so BOTH the exploit sandbox and the invariant
pass got nothing (why TapMessenger:11 is UNRESOLVED: no LayerZero environment could be built).

STRATEGY: both-with-fallback.
  REAL: constructor arg wrapped into a state var of interface type whose concrete impl exists
        in the repo (ITapVault -> TapVault) -> deploy the REAL contract. Catches integration bugs.
  STUB: no repo impl (LayerZero endpoint, external CCTP) -> minimal stub so calls don't revert.

All read from the compiled AST: arg name, its binding to a state var, that var's declared type
(the arg is a bare `address`; the interface type lives on the state variable it's assigned to).
"""
import json
import re
from pathlib import Path


def _find(node, pred):
    if isinstance(node, dict):
        if pred(node):
            return node
        for v in node.values():
            r = _find(v, pred)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find(v, pred)
            if r is not None:
                return r
    return None


def _find_all(node, pred, acc=None):
    if acc is None:
        acc = []
    if isinstance(node, dict):
        if pred(node):
            acc.append(node)
        for v in node.values():
            _find_all(v, pred, acc)
    elif isinstance(node, list):
        for v in node:
            _find_all(v, pred, acc)
    return acc


def _constructor(ast):
    return _find(ast, lambda n: n.get("nodeType") == "FunctionDefinition"
                 and n.get("kind") == "constructor")


def _ctor_params(ctor):
    if not ctor:
        return []
    out = []
    for p in ctor.get("parameters", {}).get("parameters", []):
        t = p.get("typeName", {})
        tn = (t.get("pathNode") or {}).get("name") or t.get("name")
        out.append((p.get("name"), tn))
    return out


def _arg_bindings(ctor):
    bindings = {}
    for asn in _find_all(ctor, lambda n: n.get("nodeType") == "Assignment"):
        rhs = asn.get("rightHandSide", {})
        if rhs.get("nodeType") == "FunctionCall":
            typ = (rhs.get("expression") or {}).get("name")
            args = rhs.get("arguments") or []
            if args and args[0].get("nodeType") == "Identifier":
                bindings[args[0].get("name")] = typ
        elif rhs.get("nodeType") == "Identifier":
            bindings[rhs.get("name")] = None
    return bindings


def _repo_contracts(src_dir):
    out = {}
    for f in sorted(Path(src_dir).glob("*.sol")):
        text = f.read_text()
        for m in re.finditer(r'\bcontract\s+(\w+)', text):
            out[m.group(1)] = f.name
    return out


def _resolve_impl(iface_type, repo):
    if not iface_type:
        return None, None
    candidates = []
    if iface_type.startswith("I") and len(iface_type) > 1:
        candidates.append(iface_type[1:])
    candidates.append(iface_type)
    for c in candidates:
        if c in repo:
            return c, repo[c]
    return None, None


def resolve(artifact_path, src_dir):
    """Return [{arg, kind: 'value'|'token'|'real'|'stub', type, ...}] or None."""
    art = json.loads(Path(artifact_path).read_text())
    ast = art.get("ast")
    if not ast:
        # A plain `forge build` strips the AST (only emitted with --ast). The invariant pass
        # runs its own builds, so this happens routinely. Rebuild with --ast rather than
        # silently returning None (which drops dependency resolution to dummy args).
        import subprocess as _sp, config as _cfg
        forge = str(_cfg.ANVIL_BIN).replace("anvil", "forge")
        proj = Path(src_dir).parent
        _sp.run([forge, "build", "--ast"], cwd=str(proj), capture_output=True, timeout=600)
        try:
            art = json.loads(Path(artifact_path).read_text())
            ast = art.get("ast")
        except Exception:
            ast = None
        if not ast:
            return None
    ctor = _constructor(ast)
    params = _ctor_params(ctor)
    bindings = _arg_bindings(ctor)
    repo = _repo_contracts(src_dir)

    plan = []
    for name, etype in params:
        entry = {"arg": name, "type": etype}
        if etype != "address":
            entry["kind"] = "value"
            plan.append(entry)
            continue
        iface = bindings.get(name)
        low = (name or "").lower().lstrip("_")
        if any(k in low for k in ("usdc", "token", "asset", "currency")):
            entry["kind"] = "token"
        else:
            impl_name, impl_file = _resolve_impl(iface, repo)
            if impl_name:
                entry.update({"kind": "real", "impl": impl_name, "file": impl_file})
            else:
                entry.update({"kind": "stub", "iface": iface})
        plan.append(entry)
    return plan
