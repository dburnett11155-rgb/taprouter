"""dep_codegen.py — Phase 5c component 2: turn a dependency resolution plan into Solidity.

Consumes dep_resolver.resolve() plans and emits:
  - stub CONTRACTS (one per external interface dependency), ABI-derived no-ops returning
    zero-ish values so the target's calls don't revert (a reverting stub is as useless as
    no stub — same vacuity trap as the v1 mock token).
  - a deployment BLOCK for setUp(): deploy token/stubs/real deps, then wire ctor args in order.

REAL deps recurse (depth cap 2); on cycle or over-depth, degrade to a dummy address and let
coverage-capping flag reduced fidelity.
"""
import json
import re
from pathlib import Path

SOL_ZERO = {"uint": "0", "int": "0", "bool": "false", "address": "address(0)",
            "bytes32": "bytes32(0)", "string": '""', "bytes": '""'}


def _zero_for(sol_type):
    if sol_type.endswith("[]"):
        return None
    for k, v in SOL_ZERO.items():
        if sol_type.startswith(k):
            return v
    return "0"


def _mem(sol_type):
    if sol_type in ("string", "bytes") or sol_type.endswith("[]"):
        return sol_type + " memory"
    return sol_type


def stub_for_interface(iface_name, abi):
    lines = ["contract Stub_%s {" % iface_name]
    for e in abi:
        if e.get("type") != "function":
            continue
        args = ", ".join("%s a%d" % (_mem(i["type"]), n)
                         for n, i in enumerate(e.get("inputs", [])))
        outs = e.get("outputs", [])
        ret_decl, body = "", ""
        if outs:
            ret_decl = " returns (%s)" % ", ".join(_mem(o["type"]) for o in outs)
            vals = []
            for o in outs:
                z = _zero_for(o["type"])
                if "nonce" in (o.get("name", "").lower()):
                    z = "1"
                vals.append(z if z is not None else "0")
            body = "return (%s);" % ", ".join(vals)
        mut = e.get("stateMutability", "nonpayable")
        mut_kw = " view" if mut == "view" else (" payable" if mut == "payable" else "")
        lines.append("    function %s(%s) external%s%s { %s }"
                     % (e["name"], args, mut_kw, ret_decl, body))
    lines.append("}")
    return "\n".join(lines)


def _iface_abi_from_source(iface_name, src_dir):
    for f in Path(src_dir).glob("*.sol"):
        text = f.read_text()
        m = re.search(r'interface\s+%s\s*\{(.*?)\n\}' % re.escape(iface_name), text, re.S)
        if not m:
            continue
        body = m.group(1)
        fns = []
        for fm in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)\s*external([^;]*);', body):
            name, args_s, tail = fm.group(1), fm.group(2), fm.group(3)
            inputs = []
            for a in [x.strip() for x in args_s.split(",") if x.strip()]:
                parts = a.split()
                inputs.append({"type": parts[0], "name": parts[-1] if len(parts) > 1 else ""})
            outputs = []
            rm = re.search(r'returns\s*\(([^)]*)\)', tail)
            if rm:
                for o in [x.strip() for x in rm.group(1).split(",") if x.strip()]:
                    parts = o.split()
                    outputs.append({"type": parts[0], "name": parts[-1] if len(parts) > 1 else ""})
            mut = "view" if (" view" in tail or " pure" in tail) else "nonpayable"
            fns.append({"type": "function", "name": name, "inputs": inputs,
                        "outputs": outputs, "stateMutability": mut})
        return fns
    return []


def build(target_name, plan, src_dir, out_dir, depth=0, _seen=None):
    if _seen is None:
        _seen = set()
    stubs, deploy, ctor_args = {}, [], []
    for i, e in enumerate(plan):
        kind = e["kind"]; arg = e["arg"]
        var = "dep_%s_%d" % (re.sub(r'\W', '', arg), i)
        if kind == "token":
            ctor_args.append("address(token)")
        elif kind == "value":
            t = e["type"]
            ctor_args.append("1000" if t.startswith("uint") else ("false" if t == "bool" else "0"))
        elif kind == "real" and depth < 2:
            impl = e["impl"]
            sub_art = Path(out_dir) / ("%s.sol" % impl) / ("%s.json" % impl)
            if impl in _seen or not sub_art.exists():
                deploy.append('address %s = address(uint160(uint256(keccak256("%s"))));' % (var, arg))
                ctor_args.append(var)
            else:
                from adversarial import dep_resolver
                sub_plan = dep_resolver.resolve(str(sub_art), src_dir) or []
                sub_stubs, sub_deploy, sub_args = build(impl, sub_plan, src_dir, out_dir,
                                                        depth + 1, _seen | {impl})
                stubs.update(sub_stubs)
                deploy.extend(sub_deploy)
                deploy.append("%s %s = new %s(%s);" % (impl, var, impl, ", ".join(sub_args)))
                ctor_args.append("address(%s)" % var)
        elif kind == "stub" and e.get("iface"):
            iface = e["iface"]
            abi = _iface_abi_from_source(iface, src_dir)
            if abi:
                stubs[iface] = stub_for_interface(iface, abi)
                deploy.append("Stub_%s %s = new Stub_%s();" % (iface, var, iface))
                ctor_args.append("address(%s)" % var)
            else:
                deploy.append('address %s = address(uint160(uint256(keccak256("%s"))));' % (var, arg))
                ctor_args.append(var)
        else:
            deploy.append('address %s = address(uint160(uint256(keccak256("%s"))));' % (var, arg))
            ctor_args.append(var)
    return stubs, deploy, ctor_args
