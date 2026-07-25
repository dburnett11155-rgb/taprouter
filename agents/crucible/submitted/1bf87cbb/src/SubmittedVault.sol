// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
interface IERC20 { function transfer(address,uint256) external returns (bool); }
contract SubmittedVault {
    mapping(address => uint256) public balances;
    IERC20 public token;
    function deposit(uint256 a) external { balances[msg.sender] += a; }
    function withdraw() external { uint256 b = balances[msg.sender]; require(b > 0); token.transfer(msg.sender, b); balances[msg.sender] = 0; }
}