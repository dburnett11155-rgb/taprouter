// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import { SafeERC20 } from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import { ReentrancyGuard } from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import { Ownable } from "@openzeppelin/contracts/access/Ownable.sol";
import { OApp, MessagingFee, Origin } from "@layerzerolabs/oapp/OApp.sol";
import { OptionsBuilder } from "@layerzerolabs/oapp/libs/OptionsBuilder.sol";

interface ICCTPTokenMessenger {
    function depositForBurn(uint256 amount, uint32 destinationDomain, bytes32 mintRecipient, address burnToken) external returns (uint64 nonce);
}

contract TapRouter is OApp, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using OptionsBuilder for bytes;

    uint32 public destCctpDomain; // set per-direction at deploy (Base=6, Arbitrum=3)
    uint256 public constant MIN_SWAP_AMOUNT = 1e6;
    uint256 public constant MAX_SWAP_AMOUNT = 10_000e6;

    IERC20 public immutable usdc;
    ICCTPTokenMessenger public immutable cctpMessenger;
    address public tapVault;
    address public protocolWallet;
    uint32 public dstEid;
    uint128 public lzReceiveGas;
    bool public paused;

    uint256 public swapNonce;
    mapping(bytes32 => bool) public swapInitiated;

    event SwapInitiated(bytes32 indexed swapId, address indexed sender, address indexed recipient, uint256 amount);
    event VaultUpdated(address newVault);
    event DstEidUpdated(uint32 newDstEid);
    event LzReceiveGasUpdated(uint128 newGas);

    error InvalidAmount();
    error Paused();
    error ZeroAddress();
    error SwapAlreadyInitiated();
    error InsufficientFee();

    constructor(
        address _usdc,
        address _endpoint,
        address _cctpMessenger,
        address _tapVault,
        address _protocolWallet,
        uint32 _dstEid,
        uint32 _destCctpDomain
    ) OApp(_endpoint, msg.sender) Ownable(msg.sender) {
        if (_usdc == address(0) || _endpoint == address(0) || _cctpMessenger == address(0)) revert ZeroAddress();
        usdc = IERC20(_usdc);
        cctpMessenger = ICCTPTokenMessenger(_cctpMessenger);
        tapVault = _tapVault;
        protocolWallet = _protocolWallet;
        destCctpDomain = _destCctpDomain;
        dstEid = _dstEid;
        lzReceiveGas = 200_000;
    }

    function initiateSwap(uint256 amount, address recipient) external payable nonReentrant {
        if (paused) revert Paused();
        if (amount < MIN_SWAP_AMOUNT || amount > MAX_SWAP_AMOUNT) revert InvalidAmount();
        if (recipient == address(0)) revert ZeroAddress();

        bytes32 swapId = keccak256(abi.encodePacked(msg.sender, recipient, amount, block.timestamp, block.number, swapNonce++));
        if (swapInitiated[swapId]) revert SwapAlreadyInitiated();
        swapInitiated[swapId] = true;

        usdc.safeTransferFrom(msg.sender, address(this), amount);

        bytes memory message = abi.encode(swapId, recipient, amount);
        bytes memory options = OptionsBuilder.newOptions().addExecutorLzReceiveOption(lzReceiveGas, 0);

        MessagingFee memory fee = _quote(dstEid, message, options, false);
        if (msg.value < fee.nativeFee) revert InsufficientFee();

        usdc.forceApprove(address(cctpMessenger), amount);
        bytes32 mintRecipient = bytes32(uint256(uint160(tapVault)));
        cctpMessenger.depositForBurn(amount, destCctpDomain, mintRecipient, address(usdc));

        _lzSend(dstEid, message, options, MessagingFee(fee.nativeFee, 0), payable(msg.sender));


        emit SwapInitiated(swapId, msg.sender, recipient, amount);
    }

    function quoteSwapFee(uint256 amount, address recipient) external view returns (uint256 nativeFee) {
        bytes memory message = abi.encode(bytes32(0), recipient, amount);
        bytes memory options = OptionsBuilder.newOptions().addExecutorLzReceiveOption(lzReceiveGas, 0);
        MessagingFee memory fee = _quote(dstEid, message, options, false);
        nativeFee = fee.nativeFee;
    }

    // Send-only OApp: inbound messages are not expected.
    // Forward full msg.value; LZ endpoint refunds any excess above the fee to the refundAddress.
    function _payNative(uint256 _nativeFee) internal view override returns (uint256) {
        if (msg.value < _nativeFee) revert InsufficientFee();
        return msg.value;
    }

    function _lzReceive(Origin calldata, bytes32, bytes calldata, address, bytes calldata) internal override {
        revert("TapRouter: receive disabled");
    }

    function setTapVault(address _tapVault) external onlyOwner { tapVault = _tapVault; emit VaultUpdated(_tapVault); }
    function setDstEid(uint32 _dstEid) external onlyOwner { dstEid = _dstEid; emit DstEidUpdated(_dstEid); }
    function setLzReceiveGas(uint128 _gas) external onlyOwner { lzReceiveGas = _gas; emit LzReceiveGasUpdated(_gas); }
    function setPaused(bool _paused) external onlyOwner { paused = _paused; }
    function rescueEth() external onlyOwner { payable(protocolWallet).transfer(address(this).balance); }
    function rescueUsdc() external onlyOwner { usdc.safeTransfer(protocolWallet, usdc.balanceOf(address(this))); }
}
