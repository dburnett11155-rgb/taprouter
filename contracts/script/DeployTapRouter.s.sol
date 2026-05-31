// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/TapRouter.sol";

contract DeployTapRouter is Script {
    address constant USDC           = 0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d;
    address constant LZ_ENDPOINT    = 0x6EDCE65403992e310A62460808c4b910D972f10f;
    address constant CCTP_MESSENGER = 0x9f3B8679c73C2Fef8b59B4f3444d4e156fb70AA5;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer    = vm.addr(deployerKey);
        address tapVault    = vm.envAddress("TAP_VAULT_ADDRESS");
        uint32  dstEid      = uint32(vm.envUint("DST_EID"));

        vm.startBroadcast(deployerKey);

        TapRouter router = new TapRouter(
            USDC,
            LZ_ENDPOINT,
            CCTP_MESSENGER,
            tapVault,
            deployer,
            dstEid
        );

        vm.stopBroadcast();

        console.log("TapRouter deployed at:", address(router));
    }
}
