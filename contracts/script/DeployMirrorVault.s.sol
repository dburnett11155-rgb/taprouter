// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Script.sol";
import "../src/TapVault.sol";

// Mirror vault lives on ARBITRUM (receives Base->Arb swaps). Uses Arbitrum USDC.
contract DeployMirrorVault is Script {
    address constant USDC = 0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d; // Arbitrum Sepolia USDC
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer    = vm.addr(deployerKey);
        vm.startBroadcast(deployerKey);
        TapVault vault = new TapVault(
            USDC,
            deployer, // protocolWallet
            deployer  // placeholder messenger, fixed via setMessenger
        );
        vm.stopBroadcast();
        console.log("Mirror TapVault deployed at:", address(vault));
    }
}
