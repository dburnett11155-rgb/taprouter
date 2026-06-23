// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.35;

import "forge-std/Test.sol";
import "../src/TapMarket.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USD Coin", "USDC") {}
    function decimals() public pure override returns (uint8) {
        return 6;
    }
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract TapMarketTest is Test {
    TapMarket market;
    MockUSDC usdc;

    address owner   = address(this);
    address builder = makeAddr("builder");
    address buyer   = makeAddr("buyer");

    // Agent signer needs a known private key so the test can sign attestations.
    uint256 agentPk = 0xA11CE;
    address agentSigner;

    uint16 constant FEE_BPS = 1000; // 10%
    uint256 constant PRICE  = 1e6;  // 1 USDC per use

    function setUp() public {
        agentSigner = vm.addr(agentPk);
        usdc = new MockUSDC();
        market = new TapMarket(address(usdc), FEE_BPS);

        usdc.mint(buyer, 1_000e6);
        vm.prank(buyer);
        usdc.approve(address(market), type(uint256).max);
    }

    // ---- EIP-712 attestation signing helper ----
    function _signAttestation(
        address buyer_,
        uint256 listingId,
        uint256 cumulativeUses,
        uint256 expiry
    ) internal view returns (bytes memory) {
        bytes32 structHash = keccak256(
            abi.encode(
                market.ATTEST_TYPEHASH(),
                buyer_,
                listingId,
                cumulativeUses,
                expiry
            )
        );
        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", market.DOMAIN_SEPARATOR(), structHash)
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(agentPk, digest);
        return abi.encodePacked(r, s, v);
    }

    // ---- helper: list an agent and return its id ----
    function _list(uint32 payoutEid) internal returns (uint256) {
        vm.prank(builder);
        return market.listAgent(agentSigner, PRICE, payoutEid);
    }

    function test_setup() public view {
        assertEq(address(market.usdc()), address(usdc));
        assertEq(market.protocolFeeBps(), FEE_BPS);
        assertEq(usdc.balanceOf(buyer), 1_000e6);
    }

    function test_listAndBuyPack() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        (uint256 bal, uint256 purchased,,,,,) = market.escrows(id, buyer);
        assertEq(bal, 100e6);          // 100 uses * 1 USDC
        assertEq(purchased, 100);
        assertEq(usdc.balanceOf(address(market)), 100e6);
    }

    function test_settleHappyPath() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        uint256 expiry = block.timestamp + 1 hours;
        bytes memory sig = _signAttestation(buyer, id, 10, expiry);

        uint256 builderBefore = usdc.balanceOf(builder);
        uint256 ownerBefore   = usdc.balanceOf(owner);

        market.settle(id, buyer, 10, expiry, sig);

        // 10 uses * 1 USDC = 10 USDC cost; 10% fee = 1 USDC owner, 9 USDC builder
        assertEq(usdc.balanceOf(builder) - builderBefore, 9e6);
        assertEq(usdc.balanceOf(owner) - ownerBefore, 1e6);

        (uint256 bal,, uint256 settled,,,,) = market.escrows(id, buyer);
        assertEq(bal, 90e6);   // 100 - 10
        assertEq(settled, 10);
    }

    function test_settleBatched() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 100);

        uint256 expiry = block.timestamp + 1 hours;

        // First settle: cumulative 10
        market.settle(id, buyer, 10, expiry, _signAttestation(buyer, id, 10, expiry));
        // Second settle: cumulative 25 -> only 15 new uses charged
        uint256 builderBefore = usdc.balanceOf(builder);
        market.settle(id, buyer, 25, expiry, _signAttestation(buyer, id, 25, expiry));

        assertEq(usdc.balanceOf(builder) - builderBefore, 15e6 * 9 / 10); // 15 uses, 90% to builder
        (uint256 bal,, uint256 settled,,,,) = market.escrows(id, buyer);
        assertEq(bal, 75e6);    // 100 - 25
        assertEq(settled, 25);
    }

    function test_crossChainAccrues() public {
        uint256 id = _list(40231); // non-zero payout EID = cross-chain
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        uint256 expiry = block.timestamp + 1 hours;
        uint256 builderBefore = usdc.balanceOf(builder);

        market.settle(id, buyer, 10, expiry, _signAttestation(buyer, id, 10, expiry));

        // Builder share should accrue, not transfer
        assertEq(usdc.balanceOf(builder), builderBefore); // unchanged
        assertEq(market.pendingCrossChain(id), 9e6);      // 9 USDC accrued
        assertEq(usdc.balanceOf(owner), 1e6);             // protocol fee still paid out
    }

    function test_rejectBadSignature() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        uint256 expiry = block.timestamp + 1 hours;
        // Sign with a different key (0xBAD) than the listing's agentSigner
        bytes32 structHash = keccak256(abi.encode(market.ATTEST_TYPEHASH(), buyer, id, uint256(10), expiry));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", market.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xBAD, digest);
        bytes memory badSig = abi.encodePacked(r, s, v);

        vm.expectRevert(TapMarket.BadSignature.selector);
        market.settle(id, buyer, 10, expiry, badSig);
    }

    function test_rejectExpiredAttestation() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        uint256 expiry = block.timestamp + 1 hours;
        bytes memory sig = _signAttestation(buyer, id, 10, expiry);

        vm.warp(block.timestamp + 2 hours); // past expiry
        vm.expectRevert(TapMarket.StaleAttestation.selector);
        market.settle(id, buyer, 10, expiry, sig);
    }

    function test_rejectReplay() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 50);

        uint256 expiry = block.timestamp + 1 hours;
        market.settle(id, buyer, 10, expiry, _signAttestation(buyer, id, 10, expiry));

        // Replaying the same cumulative count -> delta 0 -> StaleAttestation
        bytes memory replaySig = _signAttestation(buyer, id, 10, expiry);
        vm.expectRevert(TapMarket.StaleAttestation.selector);
        market.settle(id, buyer, 10, expiry, replaySig);
    }

    function test_rejectCapExceeded() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 20); // cap 20 per period

        uint256 expiry = block.timestamp + 1 hours;
        // Try to settle 25 in one go, exceeds cap of 20
        bytes memory capSig = _signAttestation(buyer, id, 25, expiry);
        vm.expectRevert(TapMarket.CapExceeded.selector);
        market.settle(id, buyer, 25, expiry, capSig);
    }

    function test_rejectInsufficientEscrow() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 10, 100); // only 10 uses bought

        uint256 expiry = block.timestamp + 1 hours;
        // Attest 20 uses but only 10 escrowed
        bytes memory escSig = _signAttestation(buyer, id, 20, expiry);
        vm.expectRevert(TapMarket.InsufficientEscrow.selector);
        market.settle(id, buyer, 20, expiry, escSig);
    }

    function test_capResetsNextPeriod() public {
        uint256 id = _list(0);
        vm.prank(buyer);
        market.buyPack(id, 100, 20);

        uint256 expiry = block.timestamp + 365 days;
        // Settle 20 (hits cap exactly)
        market.settle(id, buyer, 20, expiry, _signAttestation(buyer, id, 20, expiry));

        // Same period, settling more reverts
        bytes memory over = _signAttestation(buyer, id, 25, expiry);
        vm.expectRevert(TapMarket.CapExceeded.selector);
        market.settle(id, buyer, 25, expiry, over);

        // After PERIOD elapses, cap resets and it works
        vm.warp(block.timestamp + 1 days + 1);
        market.settle(id, buyer, 25, expiry, _signAttestation(buyer, id, 25, expiry));
        (,, uint256 settled,,,,) = market.escrows(id, buyer);
        assertEq(settled, 25);
    }
}
