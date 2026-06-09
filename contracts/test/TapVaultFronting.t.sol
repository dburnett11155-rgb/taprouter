// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/TapVault.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USD Coin", "USDC") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function decimals() public pure override returns (uint8) { return 6; }
}

contract TapVaultFrontingTest is Test {
    MockUSDC usdc;
    TapVault vault;
    address protocol = address(0xBEEF);
    address messenger = address(0xAAA1);
    address settler = address(0x5E77);
    address lp = address(0x11);
    address recipient = address(0x22);

    function setUp() public {
        usdc = new MockUSDC();
        vault = new TapVault(address(usdc), protocol, messenger);
        vault.setSettler(settler);

        // LP deposits 1000 USDC
        usdc.mint(lp, 1000e6);
        vm.startPrank(lp);
        usdc.approve(address(vault), 1000e6);
        vault.deposit(1000e6);
        vm.stopPrank();
    }

    // A swap with NO CCTP funds present should FRONT from LP liquidity.
    function testFrontsFromLiquidity() public {
        uint256 amountIn = 100e6;
        vm.prank(messenger);
        vault.executeSwap(keccak256("s1"), recipient, amountIn);

        // recipient got payout (amountIn - 1.5% fee)
        uint256 expectedPayout = amountIn - (amountIn * 150 / 10000);
        assertEq(usdc.balanceOf(recipient), expectedPayout, "recipient payout");
        // outstandingFronted == amountIn
        assertEq(vault.outstandingFronted(), amountIn, "fronted recorded");
    }

    // Trustless: reconcile with NO real funds arrived clears nothing.
    function testReconcileWithoutFundsClearsNothing() public {
        vm.prank(messenger);
        vault.executeSwap(keccak256("s1"), recipient, 100e6);
        uint256 before = vault.outstandingFronted();

        vm.prank(settler);
        vault.reconcile();

        assertEq(vault.outstandingFronted(), before, "fake reconcile cleared nothing");
    }

    // Real reconcile: after USDC actually arrives, fronted debt clears.
    function testReconcileWithFundsClears() public {
        uint256 amountIn = 100e6;
        vm.prank(messenger);
        vault.executeSwap(keccak256("s1"), recipient, amountIn);

        // Simulate CCTP mint arriving: real USDC lands in the vault.
        usdc.mint(address(vault), amountIn);

        vm.prank(settler);
        vault.reconcile();

        assertEq(vault.outstandingFronted(), 0, "fronted cleared after real funds");
    }

    // Cap: cannot front beyond 50% of liquidity; falls back to strict (reverts w/o CCTP).
    function testFrontCapEnforced() public {
        // 50% of 1000 = 500 frontable. A 600 swap exceeds cap -> strict path ->
        // needs CCTP present; none is, so it reverts InsufficientLiquidity.
        vm.prank(messenger);
        vm.expectRevert(TapVault.InsufficientLiquidity.selector);
        vault.executeSwap(keccak256("big"), recipient, 600e6);
    }
}
