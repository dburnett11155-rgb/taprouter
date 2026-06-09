// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @notice TapVault with trustless LP-fronting.
/// INVARIANT: accountedBalance == USDC the vault holds that is already assigned
/// (LP principal + flashReserve + accrued-unclaimed LP fees). Any real balance
/// ABOVE accountedBalance is unaccounted = funds that physically arrived (a CCTP
/// mint) and may clear fronted debt. reconcile() can only clear up to that gap,
/// so a reconcile call with no real mint behind it clears nothing. This makes
/// fronting trustless: a compromised settler key cannot fabricate liquidity.
contract TapVault is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    uint256 public constant LP_FEE_BPS        = 80;
    uint256 public constant PROTOCOL_FEE_BPS  = 50;
    uint256 public constant FLASH_RESERVE_BPS = 20;
    uint256 public constant BPS_DENOMINATOR   = 10_000;
    uint256 public constant MAX_FRONT_BPS_CAP = 8_000; // hard ceiling: cap can never exceed 80%

    IERC20  public immutable usdc;
    address public immutable protocolWallet;
    address public messenger;
    address public settler;

    uint256 public totalLiquidity;      // LP principal
    uint256 public flashReserve;        // accrued flash buffer
    uint256 public accruedLpFees;       // LP fees sitting in the vault, not yet claimed
    uint256 public accFeePerShare;
    uint256 public outstandingFronted;  // USDC fronted ahead of CCTP, awaiting reconcile
    uint256 public cctpReceived;        // lifetime reconciled/strict CCTP funds (stat)

    uint256 public frontCapBps = 5_000; // settable, default 50%
    bool    public paused;

    mapping(address => uint256) public shares;
    mapping(address => uint256) public feeDebt;
    mapping(bytes32  => bool)   public processed;

    event Deposited(address indexed lp, uint256 amount, uint256 shares);
    event Withdrawn(address indexed lp, uint256 amount, uint256 shares);
    event SwapExecuted(bytes32 indexed swapId, address indexed recipient, uint256 amountIn, uint256 payout, bool fronted);
    event FeesDistributed(uint256 lpFee, uint256 protocolFee, uint256 flashFee);
    event Reconciled(uint256 cleared, uint256 outstandingRemaining);
    event Paused(bool paused);
    event FrontCapUpdated(uint256 bps);

    error InsufficientLiquidity();
    error AlreadyProcessed();
    error Unauthorized();
    error ZeroAmount();
    error FrontCapExceeded();
    error IsPaused();
    error BadParam();

    constructor(address _usdc, address _protocolWallet, address _messenger) Ownable(msg.sender) {
        usdc           = IERC20(_usdc);
        protocolWallet = _protocolWallet;
        messenger      = _messenger;
    }

    // accountedBalance = everything the vault holds that's already assigned.
    function accountedBalance() public view returns (uint256) {
        return totalLiquidity + flashReserve + accruedLpFees;
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
        // Can't withdraw funds reserved or currently fronted out.
        if (usdc.balanceOf(address(this)) < shareAmount + flashReserve + accruedLpFees + outstandingFronted) {
            revert InsufficientLiquidity();
        }
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

    function executeSwap(bytes32 swapId, address recipient, uint256 amountIn) external nonReentrant {
        if (paused)                  revert IsPaused();
        if (msg.sender != messenger) revert Unauthorized();
        if (processed[swapId])       revert AlreadyProcessed();
        if (amountIn == 0)           revert ZeroAmount();

        processed[swapId] = true;

        uint256 lpFee       = (amountIn * LP_FEE_BPS)        / BPS_DENOMINATOR;
        uint256 protocolFee = (amountIn * PROTOCOL_FEE_BPS)  / BPS_DENOMINATOR;
        uint256 flashFee    = (amountIn * FLASH_RESERVE_BPS) / BPS_DENOMINATOR;
        uint256 payout      = amountIn - lpFee - protocolFee - flashFee;

        uint256 bal     = usdc.balanceOf(address(this));
        uint256 maxFront = (totalLiquidity * frontCapBps) / BPS_DENOMINATOR;

        // FRONT if: cap not exceeded AND vault holds enough real balance to cover
        // this payout + protocol fee on top of everything already assigned and
        // already fronted, WITHOUT counting the incoming CCTP amountIn.
        bool canFront =
            (outstandingFronted + amountIn <= maxFront) &&
            (bal >= flashReserve + accruedLpFees + outstandingFronted + payout + protocolFee);

        bool fronted;
        if (canFront) {
            outstandingFronted += amountIn;
            fronted = true;
        } else {
            // STRICT: the CCTP-minted amountIn must already be present (unaccounted).
            if (bal < accountedBalance() + outstandingFronted + amountIn) revert InsufficientLiquidity();
            cctpReceived += amountIn;
        }

        // Distribute fees. LP fee and flash fee stay in the vault (now assigned);
        // protocol fee leaves immediately.
        if (totalLiquidity > 0) {
            accFeePerShare += (lpFee * 1e18) / totalLiquidity;
            accruedLpFees  += lpFee;
        }
        flashReserve += flashFee;

        usdc.safeTransfer(protocolWallet, protocolFee);
        usdc.safeTransfer(recipient, payout);

        emit SwapExecuted(swapId, recipient, amountIn, payout, fronted);
        emit FeesDistributed(lpFee, protocolFee, flashFee);
    }

    /// @notice Trustless reconcile: clears fronted debt only up to USDC that has
    /// ACTUALLY arrived (real balance above accountedBalance + outstandingFronted's
    /// expected coverage). No trust in caller; a fake call clears nothing.
    function reconcile() external nonReentrant {
        if (msg.sender != settler && msg.sender != owner()) revert Unauthorized();

        uint256 bal      = usdc.balanceOf(address(this));
        uint256 assigned = accountedBalance();
        uint256 floor    = assigned > outstandingFronted ? assigned - outstandingFronted : 0;
        if (bal <= floor) {
            emit Reconciled(0, outstandingFronted);
            return;
        }
        uint256 unaccounted = bal - floor;
        uint256 clear = unaccounted < outstandingFronted ? unaccounted : outstandingFronted;
        if (clear == 0) {
            emit Reconciled(0, outstandingFronted);
            return;
        }

        // The arrived USDC replenishes LP principal that was fronted out.
        outstandingFronted -= clear;
        totalLiquidity     += clear;
        cctpReceived       += clear;
        emit Reconciled(clear, outstandingFronted);
    }

    // --- admin ---
    function setMessenger(address _messenger) external onlyOwner { messenger = _messenger; }
    function setSettler(address _settler) external onlyOwner { settler = _settler; }
    function setPaused(bool _paused) external onlyOwner { paused = _paused; emit Paused(_paused); }

    function setFrontCapBps(uint256 _bps) external onlyOwner {
        if (_bps > MAX_FRONT_BPS_CAP) revert BadParam();
        frontCapBps = _bps;
        emit FrontCapUpdated(_bps);
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
            feeDebt[lp]    = (shares[lp] * accFeePerShare) / 1e18;
            accruedLpFees -= pending;
            usdc.safeTransfer(lp, pending);
        }
    }
}
