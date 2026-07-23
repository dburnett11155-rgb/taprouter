// SPDX-License-Identifier: MIT
// PLANTED VULNERABILITY — regression test for Crucible. GENUINE reentrancy: withdraw sends
// the full balance via external call BEFORE zeroing it, so a re-entrant call sees the full
// balance again and drains the whole vault. No guard. Verified exploitable in-sandbox.
pragma solidity ^0.8.20;
interface IERC20 { function transfer(address,uint256) external returns (bool); }
contract VulnerableVault {
    mapping(address => uint256) public balances;
    IERC20 public token;
    function deposit(uint256 amount) external { balances[msg.sender] += amount; }
    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "nothing to withdraw");
        // BUG: sends full balance via external call BEFORE zeroing — re-entry sees full bal again.
        token.transfer(msg.sender, bal);
        balances[msg.sender] = 0;
    }
}
