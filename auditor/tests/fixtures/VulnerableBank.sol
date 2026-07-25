// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract VulnerableBank {
    address public owner;
    mapping(address => uint256) public balances;

    constructor() { owner = msg.sender; }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    // reentrancy: external call before zeroing balance
    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no funds");
        (bool ok, ) = msg.sender.call{value: bal}("");
        require(ok, "send failed");
        balances[msg.sender] = 0;
    }

    // tx.origin authorization
    function rescue(address to) external {
        require(tx.origin == owner, "not owner");
        payable(to).transfer(address(this).balance);
    }

    // unchecked low-level call return
    function payout(address to, uint256 amt) external {
        to.call{value: amt}("");
    }
}