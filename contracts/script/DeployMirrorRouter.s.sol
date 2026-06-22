// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "forge-std/Script.sol";
import "../src/TapRouter.sol";

// Mirror router lives on BASE (burns Base->Arb). Uses Base addresses,
// dstEid = Arbitrum (40231), dest CCTP domain = Arbitrum (3).
contract DeployMirrorRouter is Script {
    address constant USDC           = 0x036CbD53842c5426634e7929541eC2318f3dCF7e; // Base Sepolia USDC
    address constant LZ_ENDPOINT    = 0x6EDCE65403992e310A62460808c4b910D972f10f;
    address constant CCTP_MESSENGER = 0x9f3B8679c73C2Fef8b59B4f3444d4e156fb70AA5; // Base TokenMessenger
    uint32  constant ARB_EID        = 40231;
    uint32  constant ARB_CCTP_DOMAIN = 3;
    function run() external {
        uint256 deployerKey  = vm.envUint("PRIVATE_KEY");
        address deployer     = vm.addr(deployerKey);
        address mirrorVault  = vm.envAddress("MIRROR_VAULT_ADDRESS");
        vm.startBroadcast(deployerKey);
        TapRouter router = new TapRouter(
            USDC,
            LZ_ENDPOINT,
            CCTP_MESSENGER,
            mirrorVault,
            deployer,
            ARB_EID,
            ARB_CCTP_DOMAIN
        );
        vm.stopBroadcast();
        console.log("Mirror TapRouter deployed at:", address(router));
    }
}
