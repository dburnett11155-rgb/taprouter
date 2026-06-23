// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/TapMarket.sol";

// TapMarket lives on BASE (where buyer escrow + same-chain payouts settle). Uses Base USDC.
contract DeployTapMarket is Script {
    address constant USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e; // Base Sepolia USDC
    uint16  constant PROTOCOL_FEE_BPS = 1000; // 10% — changeable later via setProtocolFee

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer    = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);
        TapMarket market = new TapMarket(USDC, PROTOCOL_FEE_BPS);
        vm.stopBroadcast();

        console.log("TapMarket deployed at:", address(market));
        console.log("  owner (deployer):   ", deployer);
        console.log("  usdc:               ", USDC);
        console.log("  protocolFeeBps:     ", PROTOCOL_FEE_BPS);
    }
}
