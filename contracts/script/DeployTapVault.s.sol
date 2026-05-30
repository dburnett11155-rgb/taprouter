// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/TapVault.sol";

contract DeployTapVault is Script {
    address constant USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer    = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);

        TapVault vault = new TapVault(
            USDC,
            deployer,
            deployer
        );

        vm.stopBroadcast();

        console.log("TapVault deployed at:", address(vault));
    }
}
