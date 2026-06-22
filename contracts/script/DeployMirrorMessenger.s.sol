// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Script.sol";
import "../src/TapMessenger.sol";

// Mirror messenger lives on ARBITRUM (receives LZ from the Base router).
contract DeployMirrorMessenger is Script {
    address constant LZ_ENDPOINT = 0x6EDCE65403992e310A62460808c4b910D972f10f;
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address mirrorVault = vm.envAddress("MIRROR_VAULT_ADDRESS");
        vm.startBroadcast(deployerKey);
        TapMessenger messenger = new TapMessenger(LZ_ENDPOINT, mirrorVault);
        vm.stopBroadcast();
        console.log("Mirror TapMessenger deployed at:", address(messenger));
    }
}
