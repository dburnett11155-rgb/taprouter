// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

interface ITapVault {
    function executeSwap(bytes32 swapId, address recipient, uint256 amountIn) external;
}

interface ILayerZeroEndpointV2 {
    function setDelegate(address delegate) external;
}

struct Origin {
    uint32 srcEid;
    bytes32 sender;
    uint64 nonce;
}

contract TapMessenger is Ownable {
    ILayerZeroEndpointV2 public immutable endpoint;
    ITapVault public immutable vault;

    uint32 public constant ARBITRUM_EID = 30110;
    bytes32 public trustedRouter;
    mapping(bytes32 => bool) public received;

    event MessageReceived(bytes32 indexed swapId, address indexed recipient, uint256 amount);

    error Unauthorized();
    error AlreadyReceived();
    error InvalidSource();

    constructor(address _endpoint, address _vault, bytes32 _trustedRouter) Ownable(msg.sender) {
        endpoint = ILayerZeroEndpointV2(_endpoint);
        vault = ITapVault(_vault);
        trustedRouter = _trustedRouter;
        endpoint.setDelegate(msg.sender);
    }

    function lzReceive(Origin calldata origin, bytes32 guid, bytes calldata payload, address, bytes calldata) external {
        if (msg.sender != address(endpoint)) revert Unauthorized();
        if (origin.srcEid != ARBITRUM_EID) revert InvalidSource();
        if (origin.sender != trustedRouter) revert Unauthorized();
        if (received[guid]) revert AlreadyReceived();

        received[guid] = true;

        (bytes32 swapId, address recipient, uint256 amount) = abi.decode(payload, (bytes32, address, uint256));
        vault.executeSwap(swapId, recipient, amount);

        emit MessageReceived(swapId, recipient, amount);
    }

    function setTrustedRouter(bytes32 _trustedRouter) external onlyOwner { trustedRouter = _trustedRouter; }
    function allowInitializePath(Origin calldata origin) external view returns (bool) { return origin.srcEid == ARBITRUM_EID && origin.sender == trustedRouter; }
    function nextNonce(uint32, bytes32) external pure returns (uint64) { return 0; }
}
