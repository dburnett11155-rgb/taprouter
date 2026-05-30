// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract TapVault is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    uint256 public constant TOTAL_FEE_BPS     = 150;
    uint256 public constant LP_FEE_BPS        = 80;
    uint256 public constant PROTOCOL_FEE_BPS  = 50;
    uint256 public constant FLASH_RESERVE_BPS = 20;
    uint256 public constant BPS_DENOMINATOR   = 10_000;

    IERC20  public immutable usdc;
    address public immutable protocolWallet;
    address public messenger;

    uint256 public totalLiquidity;
    uint256 public flashReserve;
    uint256 public accFeePerShare;
    uint256 public cctpReceived;

    mapping(address => uint256) public shares;
    mapping(address => uint256) public feeDebt;
    mapping(bytes32  => bool)   public processed;

    event Deposited(address indexed lp, uint256 amount, uint256 shares);
    event Withdrawn(address indexed lp, uint256 amount, uint256 shares);
    event SwapExecuted(bytes32 indexed swapId, address indexed recipient, uint256 amountIn, uint256 amountOut);
    event FeesDistributed(uint256 lpFee, uint256 protocolFee, uint256 flashFee);
    event CCTPReceived(bytes32 indexed swapId, uint256 amount);

    error InsufficientLiquidity();
    error AlreadyProcessed();
    error Unauthorized();
    error ZeroAmount();

    constructor(address _usdc, address _protocolWallet, address _messenger) Ownable(msg.sender) {
        usdc           = IERC20(_usdc);
        protocolWallet = _protocolWallet;
        messenger      = _messenger;
    }

    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert ZeroAmount();
        _claimFees(msg.sender);
        usdc.safeTransferFrom(msg.sender, address(this), amount);
        shares[msg.sender] += amount;
        totalLiquidity     += amount;
        feeDebt[msg.sender] = (shares[msg.sender] * accFeePerShare) / 1e18;
        emit Deposited(msg.sender, amount, shares[msg.sender]);
    }

    function withdraw(uint256 shareAmount) external nonReentrant {
        if (shareAmount == 0) revert ZeroAmount();
        if (shares[msg.sender] < shareAmount) revert InsufficientLiquidity();
        _claimFees(msg.sender);
        shares[msg.sender] -= shareAmount;
        totalLiquidity     -= shareAmount;
        feeDebt[msg.sender] = (shares[msg.sender] * accFeePerShare) / 1e18;
        usdc.safeTransfer(msg.sender, shareAmount);
        emit Withdrawn(msg.sender, shareAmount, shares[msg.sender]);
    }

    function claimFees() external nonReentrant {
        _claimFees(msg.sender);
    }

    function pendingFees(address lp) external view returns (uint256) {
        if (shares[lp] == 0) return 0;
        return (shares[lp] * accFeePerShare) / 1e18 - feeDebt[lp];
    }

    function executeSwap(
        bytes32 swapId,
        address recipient,
        uint256 amountIn
    ) external nonReentrant {
        if (msg.sender != messenger) revert Unauthorized();
        if (processed[swapId])       revert AlreadyProcessed();
        if (amountIn == 0)           revert ZeroAmount();

        processed[swapId] = true;

        uint256 totalFee    = (amountIn * TOTAL_FEE_BPS)     / BPS_DENOMINATOR;
        uint256 lpFee       = (amountIn * LP_FEE_BPS)        / BPS_DENOMINATOR;
        uint256 protocolFee = (amountIn * PROTOCOL_FEE_BPS)  / BPS_DENOMINATOR;
        uint256 flashFee    = (amountIn * FLASH_RESERVE_BPS) / BPS_DENOMINATOR;
        uint256 amountOut   = amountIn - totalFee;

        if (usdc.balanceOf(address(this)) < totalLiquidity + flashReserve + amountIn) revert InsufficientLiquidity();

        cctpReceived += amountIn;

        if (totalLiquidity > 0) {
            accFeePerShare += (lpFee * 1e18) / totalLiquidity;
        }
        flashReserve += flashFee;
        usdc.safeTransfer(protocolWallet, protocolFee);
        usdc.safeTransfer(recipient, amountOut);

        emit SwapExecuted(swapId, recipient, amountIn, amountOut);
        emit FeesDistributed(lpFee, protocolFee, flashFee);
        emit CCTPReceived(swapId, amountIn);
    }

    function setMessenger(address _messenger) external onlyOwner {
        messenger = _messenger;
    }

    function withdrawFlashReserve() external onlyOwner {
        uint256 amount = flashReserve;
        flashReserve = 0;
        usdc.safeTransfer(protocolWallet, amount);
    }

    function _claimFees(address lp) internal {
        if (shares[lp] == 0) return;
        uint256 pending = (shares[lp] * accFeePerShare) / 1e18 - feeDebt[lp];
        if (pending > 0) {
            feeDebt[lp] = (shares[lp] * accFeePerShare) / 1e18;
            usdc.safeTransfer(lp, pending);
        }
    }
}
