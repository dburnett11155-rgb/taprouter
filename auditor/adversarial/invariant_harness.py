"""invariant_harness.py — Phase 3b: assembles generated invariants into a runnable Foundry
invariant campaign. MECHANICAL handler (option B), hand-written not LLM-generated.

v2: mock token carries a REENTRANCY HOOK and the harness drives a re-entrant Attacker.
Without it the fuzzer only explores the happy path and reentrancy invariants are vacuous
(v1: 128k calls, 0 reverts, found nothing on a knowingly-broken vault).

Placeholders are __TOKENS__, not str.format — Solidity braces break .format().
"""

TEMPLATE = r'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import "forge-std/Test.sol";
import "../src/__TARGET_FILE__";

contract HookToken {
    mapping(address => uint256) public balanceOf;
    address public hook;
    function setHook(address h) external { hook = h; }
    function mint(address to, uint256 amt) external { balanceOf[to] += amt; }
    function transfer(address to, uint256 amt) external returns (bool) {
        require(balanceOf[msg.sender] >= amt, "insufficient");
        balanceOf[msg.sender] -= amt;
        balanceOf[to] += amt;
        if (to == hook && hook != address(0)) { Attacker(hook).onTokens(); }
        return true;
    }
}

contract Attacker {
    __TARGET__ public vault;
    HookToken public token;
    uint256 public budget;
    bool public armed;
    constructor(__TARGET__ _v, HookToken _t) { vault = _v; token = _t; }
    function depositTo(uint256 amt) external { vault.deposit(amt); }
    function attack(uint256 b) external {
        budget = b; armed = true;
        vault.withdraw();
        armed = false;
    }
    function onTokens() external {
        if (armed && budget > 0 && vault.balances(address(this)) > 0) {
            budget -= 1;
            vault.withdraw();
        }
    }
}

contract Handler is Test {
    __TARGET__ public vault;
    HookToken public token;
    Attacker public attacker;
    address[] public users;
    mapping(address => bool) internal seen;
    uint256 public totalDeposited;
    uint256 public totalWithdrawn;

    constructor(__TARGET__ _vault, HookToken _token, Attacker _atk) {
        vault = _vault; token = _token; attacker = _atk;
        seen[address(_atk)] = true; users.push(address(_atk));
    }

    function getUserCount() external view returns (uint256) { return users.length; }
    function getUser(uint256 i) external view returns (address) { return users[i]; }

    function deposit(uint256 amt, uint256 who) external {
        amt = bound(amt, 1, 1e18);
        address user = address(uint160(uint256(keccak256(abi.encode(who))) % 100 + 1));
        if (!seen[user]) { seen[user] = true; users.push(user); }
        token.mint(address(vault), amt);
        vm.prank(user);
        vault.deposit(amt);
        totalDeposited += amt;
    }

    function withdraw(uint256 who) external {
        if (users.length == 0) return;
        address user = users[who % users.length];
        if (user == address(attacker)) return;
        uint256 pre = token.balanceOf(user);
        vm.prank(user);
        try vault.withdraw() {} catch { return; }
        totalWithdrawn += token.balanceOf(user) - pre;
    }

    function attackerDeposit(uint256 amt) external {
        amt = bound(amt, 1, 1e18);
        token.mint(address(vault), amt);
        attacker.depositTo(amt);
        totalDeposited += amt;
    }

    function attackerWithdraw(uint256 b) external {
        b = bound(b, 1, 5);
        uint256 pre = token.balanceOf(address(attacker));
        try attacker.attack(b) {} catch { return; }
        totalWithdrawn += token.balanceOf(address(attacker)) - pre;
    }
}

contract CrucibleInvariants is Test {
    __TARGET__ public vault;
    HookToken public token;
    Attacker public attacker;
    Handler public handler;

    function setUp() public {
        vault = new __TARGET__();
        token = new HookToken();
        vm.store(address(vault), bytes32(uint256(1)), bytes32(uint256(uint160(address(token)))));
        attacker = new Attacker(vault, token);
        token.setHook(address(attacker));
        handler = new Handler(vault, token, attacker);
        targetContract(address(handler));
    }

__INVARIANTS__
}
'''


def assemble(target_file, target_name, invariants):
    bodies = "\n".join("    " + inv.get("foundry_code", "").strip().replace("\n", "\n    ")
                       for inv in invariants)
    return (TEMPLATE
            .replace("__TARGET_FILE__", target_file)
            .replace("__TARGET__", target_name)
            .replace("__INVARIANTS__", bodies))
