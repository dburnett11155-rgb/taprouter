// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Script.sol";
import "../src/TapMessenger.sol";
contract DeployTapMessenger is Script {
    address constant LZ_ENDPOINT = 0x6EDCE65403992e310A62460808c4b910D972f10f;
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address tapVault    = vm.envAddress("TAP_VAULT_ADDRESS");
        vm.startBroadcast(deployerKey);
        TapMessenger messenger = new TapMessenger(
            LZ_ENDPOINT,
            tapVault
        );
        vm.stopBroadcast();
        console.log("TapMessenger deployed at:", address(messenger));
        console.log("REMINDER: TapVault.setMessenger(messenger)");
        console.log("REMINDER: setPeer on both router and messenger");
    }
}
