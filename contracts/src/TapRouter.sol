// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

interface ILayerZeroEndpoint {
    function send(uint32 dstEid, bytes calldata message, bytes calldata options) external payable returns (bytes32 guid, uint64 nonce);
    function quote(uint32 dstEid, bytes calldata message, bytes calldata options, bool payInLzToken) external view returns (uint256 nativeFee, uint256 lzTokenFee);
}

interface ICCTPTokenMessenger {
    function depositForBurn(uint256 amount, uint32 destinationDomain, bytes32 mintRecipient, address burnToken) external returns (uint64 nonce);
}

contract TapRouter is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    uint32 public constant BASE_EID = 30184;
    uint32 public constant BASE_CCTP_DOMAIN = 6;
    uint256 public constant MIN_SWAP_AMOUNT = 1e6;
    uint256 public constant MAX_SWAP_AMOUNT = 10_000e6;

    IERC20 public immutable usdc;
    ILayerZeroEndpoint public immutable lzEndpoint;
    ICCTPTokenMessenger public immutable cctpMessenger;
    address public tapVault;
    address public protocolWallet;
    bool public paused;

    mapping(bytes32 => bool) public swapInitiated;

    event SwapInitiated(bytes32 indexed swapId, address indexed sender, address indexed recipient, uint256 amount);
    event VaultUpdated(address newVault);

    error InvalidAmount();
    error Paused();
    error ZeroAddress();
    error SwapAlreadyInitiated();
    error InsufficientFee();

    constructor(address _usdc, address _lzEndpoint, address _cctpMessenger, address _tapVault, address _protocolWallet) Ownable(msg.sender) {
        if (_usdc == address(0) || _lzEndpoint == address(0) || _cctpMessenger == address(0)) revert ZeroAddress();
        usdc = IERC20(_usdc);
        lzEndpoint = ILayerZeroEndpoint(_lzEndpoint);
        cctpMessenger = ICCTPTokenMessenger(_cctpMessenger);
        tapVault = _tapVault;
        protocolWallet = _protocolWallet;
    }

    function initiateSwap(uint256 amount, address recipient) external payable nonReentrant {
        if (paused) revert Paused();
        if (amount < MIN_SWAP_AMOUNT) revert InvalidAmount();
        if (amount > MAX_SWAP_AMOUNT) revert InvalidAmount();
        if (recipient == address(0)) revert ZeroAddress();

        bytes32 swapId = keccak256(abi.encodePacked(msg.sender, recipient, amount, block.timestamp, block.number));
        if (swapInitiated[swapId]) revert SwapAlreadyInitiated();
        swapInitiated[swapId] = true;

        usdc.safeTransferFrom(msg.sender, address(this), amount);

        bytes memory message = abi.encode(swapId, recipient, amount);
        bytes memory options = hex"0003010011010000000000000000000000000000ea60";
        (uint256 nativeFee,) = lzEndpoint.quote(BASE_EID, message, options, false);
        if (msg.value < nativeFee) revert InsufficientFee();

        usdc.approve(address(cctpMessenger), amount);
        bytes32 mintRecipient = bytes32(uint256(uint160(tapVault)));
        cctpMessenger.depositForBurn(amount, BASE_CCTP_DOMAIN, mintRecipient, address(usdc));

        lzEndpoint.send{value: nativeFee}(BASE_EID, message, options);

        uint256 excess = msg.value - nativeFee;
        if (excess > 0) {
            (bool success,) = msg.sender.call{value: excess}("");
            require(success, "Refund failed");
        }

        emit SwapInitiated(swapId, msg.sender, recipient, amount);
    }

    function quoteSwapFee(uint256 amount, address recipient) external view returns (uint256 nativeFee) {
        bytes memory message = abi.encode(bytes32(0), recipient, amount);
        bytes memory options = hex"0003010011010000000000000000000000000000ea60";
        (nativeFee,) = lzEndpoint.quote(BASE_EID, message, options, false);
    }

    function setTapVault(address _tapVault) external onlyOwner { tapVault = _tapVault; emit VaultUpdated(_tapVault); }
    function setPaused(bool _paused) external onlyOwner { paused = _paused; }
    function rescueEth() external onlyOwner { payable(protocolWallet).transfer(address(this).balance); }
    function rescueUsdc() external onlyOwner { usdc.safeTransfer(protocolWallet, usdc.balanceOf(address(this))); }
}
