// SPDX-License-Identifier: MIT
// PLANTED VULNERABILITY — regression test for Crucible. This contract has a REAL
// reentrancy bug: state update AFTER the external call, NO guard. Red must catch it.
pragma solidity ^0.8.20;
interface IERC20 { function transfer(address,uint256) external returns (bool); }
contract VulnerableVault {
    mapping(address => uint256) public balances;
    IERC20 public token;
    function deposit(uint256 amount) external { balances[msg.sender] += amount; }
    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient");
        // BUG: external call BEFORE state update, no nonReentrant guard.
        // Attacker re-enters withdraw() during transfer, draining the vault.
        token.transfer(msg.sender, amount);
        balances[msg.sender] -= amount;
    }
}
