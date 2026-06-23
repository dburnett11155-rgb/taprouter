// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.35;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title TapMarket — agent use-pack marketplace with builder-attested, batched settlement
/// @notice Buyers escrow USDC for packs of agent uses. The agent's signer attests a
///         cumulative use count (EIP-712); the contract releases the delta's value,
///         splitting protocol fee -> owner and builder share -> builder (same-chain,
///         or cross-chain via TapRouter when payoutChain differs).
contract TapMarket is ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ----- types -----
    struct Listing {
        address builder;        // receives builder share
        address agentSigner;    // key that signs use attestations
        uint256 pricePerUse;    // USDC (6dp) per use
        uint32  payoutChainEid; // 0 = same-chain (Base); else LZ EID for cross-chain payout
        bool    active;
    }

    struct Escrow {
        uint256 balance;        // USDC remaining in escrow
        uint256 usesPurchased;  // total uses bought
        uint256 settledUses;    // cumulative uses already settled (monotonic)
        uint64  capPerPeriod;   // buyer-set max uses settleable per period (burst limit)
        uint64  periodStart;    // unix ts of current period
        uint64  usedThisPeriod; // uses settled in current period
        uint64  purchaseTime;   // for refund dispute-window timing
    }

    // ----- constants -----
    uint256 public constant PERIOD = 1 days;
    uint256 public constant REFUND_DELAY = 1 days; // dispute window before unused refund
    uint16  public constant MAX_FEE_BPS = 2000;    // 20% ceiling on protocol fee

    // ----- storage -----
    IERC20 public immutable usdc;
    address public owner;
    uint16  public protocolFeeBps;              // protocol cut, e.g. 1000 = 10%
    uint256 public nextListingId;
    mapping(uint256 => Listing) public listings;
    mapping(uint256 => mapping(address => Escrow)) public escrows; // listingId => buyer => Escrow

    // EIP-712
    bytes32 public immutable DOMAIN_SEPARATOR;
    // Attestation(address buyer,uint256 listingId,uint256 cumulativeUses,uint256 expiry)
    bytes32 public constant ATTEST_TYPEHASH =
        keccak256("Attestation(address buyer,uint256 listingId,uint256 cumulativeUses,uint256 expiry)");

    // Builder share accrued for cross-chain payout, awaiting flush. listingId => USDC.
    mapping(uint256 => uint256) public pendingCrossChain;

    // ----- events -----
    event AgentListed(uint256 indexed listingId, address indexed builder, address agentSigner, uint256 pricePerUse, uint32 payoutChainEid);
    event ListingUpdated(uint256 indexed listingId, uint256 pricePerUse, bool active);
    event PackPurchased(uint256 indexed listingId, address indexed buyer, uint256 numUses, uint256 paid, uint64 capPerPeriod);
    event UsesSettled(uint256 indexed listingId, address indexed buyer, uint256 delta, uint256 builderShare, uint256 protocolFee, uint256 newSettledTotal);
    event Refunded(uint256 indexed listingId, address indexed buyer, uint256 amount);
    event ProtocolFeeSet(uint16 bps);
    event OwnerTransferred(address indexed newOwner);

    // ----- errors -----
    error NotOwner();
    error NotBuilder();
    error InactiveListing();
    error ZeroAddress();
    error BadAmount();
    error FeeTooHigh();
    error InsufficientEscrow();
    error CapExceeded();
    error StaleAttestation();
    error BadSignature();
    error RefundLocked();
    error NothingToRefund();

    // ----- modifiers -----
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address _usdc, uint16 _protocolFeeBps) {
        if (_usdc == address(0)) revert ZeroAddress();
        if (_protocolFeeBps > MAX_FEE_BPS) revert FeeTooHigh();
        usdc = IERC20(_usdc);
        owner = msg.sender;
        protocolFeeBps = _protocolFeeBps;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256(bytes("TapMarket")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    // ===== builder-side =====

    /// @notice List an agent for sale. Returns the new listingId.
    function listAgent(address agentSigner, uint256 pricePerUse, uint32 payoutChainEid)
        external
        returns (uint256 listingId)
    {
        if (agentSigner == address(0)) revert ZeroAddress();
        if (pricePerUse == 0) revert BadAmount();

        listingId = nextListingId++;
        listings[listingId] = Listing({
            builder: msg.sender,
            agentSigner: agentSigner,
            pricePerUse: pricePerUse,
            payoutChainEid: payoutChainEid,
            active: true
        });

        emit AgentListed(listingId, msg.sender, agentSigner, pricePerUse, payoutChainEid);
    }

    /// @notice Update price and/or active status of a listing. Builder only.
    function updateListing(uint256 listingId, uint256 pricePerUse, bool active) external {
        Listing storage l = listings[listingId];
        if (l.builder != msg.sender) revert NotBuilder();
        if (pricePerUse == 0) revert BadAmount();

        l.pricePerUse = pricePerUse;
        l.active = active;

        emit ListingUpdated(listingId, pricePerUse, active);
    }

    // ===== buyer-side =====

    /// @notice Buy a pack of `numUses` uses of a listing. Escrows USDC in the contract.
    /// @param capPerPeriod buyer-set max uses settleable per PERIOD (burst protection vs a rogue agent)
    function buyPack(uint256 listingId, uint256 numUses, uint64 capPerPeriod) external nonReentrant {
        Listing storage l = listings[listingId];
        if (!l.active) revert InactiveListing();
        if (numUses == 0 || capPerPeriod == 0) revert BadAmount();

        uint256 cost = numUses * l.pricePerUse;

        Escrow storage e = escrows[listingId][msg.sender];
        e.balance += cost;
        e.usesPurchased += numUses;
        e.capPerPeriod = capPerPeriod;
        e.purchaseTime = uint64(block.timestamp);
        if (e.periodStart == 0) {
            e.periodStart = uint64(block.timestamp);
        }

        usdc.safeTransferFrom(msg.sender, address(this), cost);

        emit PackPurchased(listingId, msg.sender, numUses, cost, capPerPeriod);
    }

    // ===== settlement =====

    /// @notice Settle consumed uses up to a builder-attested cumulative count.
    /// @param cumulativeUses total uses the agent attests this buyer has consumed (monotonic)
    /// @param expiry unix ts after which this attestation is invalid
    /// @param sig agentSigner's EIP-712 signature over (buyer, listingId, cumulativeUses, expiry)
    function settle(
        uint256 listingId,
        address buyer,
        uint256 cumulativeUses,
        uint256 expiry,
        bytes calldata sig
    ) external nonReentrant {
        if (block.timestamp > expiry) revert StaleAttestation();

        Listing storage l = listings[listingId];
        Escrow storage e = escrows[listingId][buyer];

        // Verify the agent signer attested this exact (buyer, listing, count, expiry).
        bytes32 structHash = keccak256(
            abi.encode(ATTEST_TYPEHASH, buyer, listingId, cumulativeUses, expiry)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
        if (_recover(digest, sig) != l.agentSigner) revert BadSignature();

        // Batched delta: cumulative count can only move up; replay -> delta 0 -> revert.
        if (cumulativeUses <= e.settledUses) revert StaleAttestation();
        uint256 delta = cumulativeUses - e.settledUses;

        // Period cap (burst protection). Reset window if PERIOD elapsed.
        if (block.timestamp >= e.periodStart + PERIOD) {
            e.periodStart = uint64(block.timestamp);
            e.usedThisPeriod = 0;
        }
        // delta is bounded by capPerPeriod (a uint64) here, so the uint64 cast below
        // cannot truncate. This check enforces that invariant explicitly.
        if (delta > type(uint64).max || e.usedThisPeriod + uint64(delta) > e.capPerPeriod) revert CapExceeded();

        uint256 cost = delta * l.pricePerUse;
        if (cost > e.balance) revert InsufficientEscrow();

        uint256 protocolFee = (cost * protocolFeeBps) / 10000;
        uint256 builderShare = cost - protocolFee;

        // Effects before interactions.
        e.balance -= cost;
        e.settledUses = cumulativeUses;
        // casting to 'uint64' is safe because delta is bounded by type(uint64).max
        // (checked in the cap guard above before any cast occurs)
        // forge-lint: disable-next-line(unsafe-typecast)
        e.usedThisPeriod += uint64(delta);

        if (protocolFee > 0) usdc.safeTransfer(owner, protocolFee);

        if (l.payoutChainEid == 0) {
            usdc.safeTransfer(l.builder, builderShare); // same-chain (Base)
        } else {
            pendingCrossChain[listingId] += builderShare; // accrue for flush
        }

        emit UsesSettled(listingId, buyer, delta, builderShare, protocolFee, cumulativeUses);
    }

    /// @dev Recover signer from a 65-byte ECDSA signature.
    function _recover(bytes32 digest, bytes calldata sig) internal pure returns (address) {
        if (sig.length != 65) revert BadSignature();
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 32))
            v := byte(0, calldataload(add(sig.offset, 64)))
        }
        return ecrecover(digest, v, r, s);
    }

    // ===== refund =====

    /// @notice Buyer reclaims unconsumed escrow for a listing after the dispute window.
    /// @dev Only the buyer's remaining balance is refundable; settled funds are already paid out.
    function refundUnused(uint256 listingId) external nonReentrant {
        Escrow storage e = escrows[listingId][msg.sender];
        if (e.balance == 0) revert NothingToRefund();
        if (block.timestamp < e.purchaseTime + REFUND_DELAY) revert RefundLocked();

        uint256 amount = e.balance;
        e.balance = 0;

        usdc.safeTransfer(msg.sender, amount);
        emit Refunded(listingId, msg.sender, amount);
    }

    // ===== admin =====

    function setProtocolFee(uint16 bps) external onlyOwner {
        if (bps > MAX_FEE_BPS) revert FeeTooHigh();
        protocolFeeBps = bps;
        emit ProtocolFeeSet(bps);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        owner = newOwner;
        emit OwnerTransferred(newOwner);
    }
}
