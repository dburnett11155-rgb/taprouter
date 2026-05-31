// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { OApp, Origin, MessagingFee } from "@layerzerolabs/oapp/OApp.sol";
import { Ownable } from "@openzeppelin/contracts/access/Ownable.sol";

interface ITapVault {
    function executeSwap(bytes32 swapId, address recipient, uint256 amountIn) external;
}

contract TapMessenger is OApp {
    ITapVault public immutable vault;

    mapping(bytes32 => bool) public received;

    event MessageReceived(bytes32 indexed swapId, address indexed recipient, uint256 amount);

    error AlreadyReceived();

    constructor(address _endpoint, address _vault) OApp(_endpoint, msg.sender) Ownable(msg.sender) {
        vault = ITapVault(_vault);
    }

    function _lzReceive(
        Origin calldata,
        bytes32 guid,
        bytes calldata payload,
        address,
        bytes calldata
    ) internal override {
        if (received[guid]) revert AlreadyReceived();
        received[guid] = true;

        (bytes32 swapId, address recipient, uint256 amount) = abi.decode(payload, (bytes32, address, uint256));
        vault.executeSwap(swapId, recipient, amount);
        emit MessageReceived(swapId, recipient, amount);
    }
}
