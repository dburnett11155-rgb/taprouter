"""harness_gen.py — Phase 5a: GENERALIZED invariant harness generator.

The vault-shaped template only fits deposit/withdraw toys. This builds a harness for an
ARBITRARY contract from its compiled ABI + source.

THREE-WAY CLASSIFICATION (the load-bearing decision):
  FUZZ       — permissionless user actions, driven from random actors.
  ROLE_PRANK — permissioned actions (onlyOwner/onlySettler/inline msg.sender checks), called
               AS the legitimate role holder so privileged paths ARE exercised.
  EXCLUDE    — ownership destruction; bricks the contract and makes later invariants
               fail meaninglessly.

Misclassification is the silent killer: fuzzing a config setter yields FALSE violations;
excluding a role function means interesting state never moves and invariants pass vacuously.
Actors are minted+approved before every call — safeTransferFrom contracts revert otherwise
and the campaign explores nothing (the v1-handler failure).
"""
import re

EXCLUDE_NAMES = {
    "renounceOwnership", "transferOwnership", "renounceRole",
    "selfdestruct", "kill", "upgradeTo", "upgradeToAndCall",
}

ROLE_MODIFIERS = {
    "onlyOwner": "owner", "onlySettler": "settler", "onlyMessenger": "messenger",
    "onlyAdmin": "admin", "onlyGovernance": "governance",
}


def _fn_signatures_from_source(source):
    out = {}
    for m in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)\s*([^{;]*)\{', source):
        name, _args, mods = m.group(1), m.group(2), m.group(3)
        # Brace-match the ACTUAL body. A fixed window bleeds into the next function and
        # steals its msg.sender guard -> permissionless fns misclassified as role-gated.
        depth, i, n = 1, m.end(), len(source)
        while i < n and depth > 0:
            c = source[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        out[name] = (mods, source[m.end():i - 1])
    return out


def classify(abi, source):
    sigs = _fn_signatures_from_source(source)
    result = {}
    for entry in abi:
        if entry.get("type") != "function" or entry.get("stateMutability") in ("view", "pure"):
            continue
        name = entry["name"]
        if name in EXCLUDE_NAMES:
            result[name] = ("exclude", "ownership/upgrade destruction")
            continue
        mods, body = sigs.get(name, ("", ""))
        role = None
        for mod_name, accessor in ROLE_MODIFIERS.items():
            if re.search(r'\b%s\b' % mod_name, mods):
                role = accessor
                break
        if role is None and body:
            guard = re.search(r'msg\.sender\s*!=\s*(\w+)', body)
            if guard:
                role = guard.group(1).replace("()", "")
        result[name] = (("role:%s" % role, "permissioned via %s" % role) if role
                        else ("fuzz", "permissionless"))
    return result


def _arg_exprs(inputs):
    decls, args = [], []
    for i, inp in enumerate(inputs):
        t = inp["type"]; p = "a%d" % i
        if t.startswith("uint"):
            decls.append("%s %s" % (t, p)); args.append("bound(%s, 1, 1e18)" % p)
        elif t.startswith("int"):
            decls.append("%s %s" % (t, p)); args.append(p)
        elif t == "address":
            decls.append("uint256 %s" % p); args.append("_actor(%s)" % p)
        elif t == "bool":
            decls.append("bool %s" % p); args.append(p)
        elif t.startswith("bytes") and t != "bytes":
            decls.append("%s %s" % (t, p)); args.append(p)
        elif t == "bytes":
            decls.append("bytes memory %s" % p); args.append(p)
        elif t == "string":
            decls.append("string memory %s" % p); args.append(p)
        else:
            return None, None
    return decls, args


MOCK_ERC20 = '''contract MockERC20 {
    string public name = "MockUSD";
    string public symbol = "mUSD";
    uint8 public decimals = 6;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 amt) external { balanceOf[to] += amt; totalSupply += amt; }
    function approve(address s, uint256 amt) external returns (bool) {
        allowance[msg.sender][s] = amt; return true;
    }
    function transfer(address to, uint256 amt) external returns (bool) {
        require(balanceOf[msg.sender] >= amt, "bal");
        balanceOf[msg.sender] -= amt; balanceOf[to] += amt; return true;
    }
    function transferFrom(address f, address to, uint256 amt) external returns (bool) {
        require(balanceOf[f] >= amt, "bal");
        uint256 a = allowance[f][msg.sender];
        require(a >= amt, "allow");
        if (a != type(uint256).max) allowance[f][msg.sender] = a - amt;
        balanceOf[f] -= amt; balanceOf[to] += amt; return true;
    }
}
'''


def _ctor_args(abi):
    ctor = next((e for e in abi if e.get("type") == "constructor"), None)
    if not ctor:
        return []
    args = []
    for inp in ctor.get("inputs", []):
        t = inp["type"]; n = inp.get("name", "").lower().lstrip("_")
        if t == "address" and any(k in n for k in ("usdc", "token", "asset", "currency")):
            args.append("address(token)")
        elif t == "address":
            args.append('address(uint160(uint256(keccak256(abi.encode("%s")))))' % n)
        elif t.startswith("uint"):
            args.append("1000")
        elif t == "bool":
            args.append("false")
        else:
            args.append("0")
    return args


TPL = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import "forge-std/Test.sol";
import "../src/__TARGET_FILE__";

__MOCK__
contract Handler is Test {
    __TARGET__ public target;
    MockERC20 public token;
    address[] public actors;

    constructor(__TARGET__ _t, MockERC20 _tok, address[] memory _actors) {
        target = _t; token = _tok;
        for (uint256 i = 0; i < _actors.length; i++) actors.push(_actors[i]);
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function _fund(address who) internal {
        token.mint(who, 1e24);
        vm.prank(who);
        token.approve(address(target), type(uint256).max);
    }

__WRAPPERS__}

contract CrucibleInvariants is Test {
    __TARGET__ public target;
    MockERC20 public token;
    Handler public handler;

    function setUp() public {
        token = new MockERC20();
        target = new __TARGET__(__CTOR_ARGS__);
        address[] memory a = new address[](__NACTORS__);
        for (uint256 i = 0; i < __NACTORS__; i++) {
            a[i] = address(uint160(uint256(keccak256(abi.encode("actor", i)))));
        }
        handler = new Handler(target, token, a);
        token.mint(address(handler), 1e30);
        targetContract(address(handler));
    }

__INVARIANTS__
}
'''


def generate(target_name, target_file, abi, source, invariants, actors=5):
    cls = classify(abi, source)
    wrappers, skipped = [], []
    for entry in abi:
        if entry.get("type") != "function" or entry.get("stateMutability") in ("view", "pure"):
            continue
        name = entry["name"]
        kind, _ = cls.get(name, ("fuzz", ""))
        if kind == "exclude":
            skipped.append("%s (excluded)" % name); continue
        decls, args = _arg_exprs(entry.get("inputs", []))
        if decls is None:
            skipped.append("%s (unsupported arg types)" % name); continue
        prank = ("vm.prank(target.%s());" % kind.split(":", 1)[1]) if kind.startswith("role:") \
                else "vm.prank(_actor(_who));"
        # Ghost counters: try/catch swallows TARGET reverts, so Foundry's "reverts: 0" can
        # mean "nothing ever executed". Without success counts a fully-reverting campaign
        # looks identical to a healthy one and every invariant passes vacuously.
        wrappers.append(
            "    uint256 public ok_%s;\n    uint256 public fail_%s;\n"
            "    function %s(%s) external {\n        _fund(_actor(_who));\n        %s\n"
            "        try target.%s(%s) { ok_%s++; } catch { fail_%s++; }\n    }\n"
            % (name, name, name, ", ".join(["uint256 _who"] + decls), prank,
               name, ", ".join(args), name, name))
    inv_bodies = "\n".join("    " + i.get("foundry_code", "").strip().replace("\n", "\n    ")
                           for i in invariants)
    out = (TPL.replace("__TARGET_FILE__", target_file)
              .replace("__MOCK__", MOCK_ERC20)
              .replace("__TARGET__", target_name)
              .replace("__CTOR_ARGS__", ", ".join(_ctor_args(abi)))
              .replace("__NACTORS__", str(actors))
              .replace("__WRAPPERS__", "".join(wrappers))
              .replace("__INVARIANTS__", inv_bodies))
    return out, {"classification": cls, "skipped": skipped}
