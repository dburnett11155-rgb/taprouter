// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/TapMarket.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

// Live end-to-end test of TapMarket on Base Sepolia: list -> buyPack -> settle.
// One wallet plays builder+buyer; a throwaway agent key signs the attestation.
contract TestMarketFlow is Script {
    address constant MARKET = 0xBfd085f192d2246F1BFBe386DF399335dc894f2c;
    address constant USDC   = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address me          = vm.addr(deployerKey);

        // Throwaway, deterministic agent signer (testnet only).
        uint256 agentKey    = uint256(keccak256("tapmarket-test-agent-v1"));
        address agentSigner = vm.addr(agentKey);

        TapMarket market = TapMarket(MARKET);
        IERC20 usdc      = IERC20(USDC);

        vm.startBroadcast(deployerKey);

        // 1. List an agent: 1 USDC/use, same-chain payout (eid 0).
        uint256 id = market.listAgent(agentSigner, 1e6, 0);
        console.log("Listed agent id:", id);

        // 2. Buy a 3-use pack (3 USDC), cap 10/period.
        usdc.approve(MARKET, 3e6);
        market.buyPack(id, 3, 10);
        console.log("Bought 3-use pack");

        vm.stopBroadcast();

        // 3. Sign an attestation for 2 cumulative uses (outside broadcast — just signing).
        uint256 expiry = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(
            abi.encode(market.ATTEST_TYPEHASH(), me, id, uint256(2), expiry)
        );
        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", market.DOMAIN_SEPARATOR(), structHash)
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(agentKey, digest);
        bytes memory sig = abi.encodePacked(r, s, v);

        uint256 builderBefore = usdc.balanceOf(me);

        // 4. Settle 2 uses.
        vm.startBroadcast(deployerKey);
        market.settle(id, me, 2, expiry, sig);
        vm.stopBroadcast();

        console.log("Settled 2 uses");
        console.log("  builder+owner delta (self):", usdc.balanceOf(me) - builderBefore);
        (uint256 bal,, uint256 settled,,,,) = market.escrows(id, me);
        console.log("  escrow balance remaining:  ", bal);
        console.log("  settledUses:               ", settled);
    }
}
