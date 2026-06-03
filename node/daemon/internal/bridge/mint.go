package bridge

import (
	"context"
	"encoding/hex"
	"fmt"
	"strings"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

// receiveMessage(bytes message, bytes attestation) on the CCTP MessageTransmitter.
const messageTransmitterABI = `[{"inputs":[{"internalType":"bytes","name":"message","type":"bytes"},{"internalType":"bytes","name":"attestation","type":"bytes"}],"name":"receiveMessage","outputs":[{"internalType":"bool","name":"success","type":"bool"}],"stateMutability":"nonpayable","type":"function"}]`

// SubmitMint sends receiveMessage to Base's MessageTransmitter to complete a
// CCTP mint, using the provided attestation. Returns the mint tx hash.
func SubmitMint(ctx context.Context, base *ethclient.Client, privKeyHex string, att *Attestation) (common.Hash, error) {
	key, err := crypto.HexToECDSA(strings.TrimPrefix(privKeyHex, "0x"))
	if err != nil {
		return common.Hash{}, fmt.Errorf("parse private key: %w", err)
	}

	chainID, err := base.ChainID(ctx)
	if err != nil {
		return common.Hash{}, fmt.Errorf("chainID: %w", err)
	}

	auth, err := bind.NewKeyedTransactorWithChainID(key, chainID)
	if err != nil {
		return common.Hash{}, fmt.Errorf("build transactor: %w", err)
	}
	auth.Context = ctx

	parsedABI, err := abi.JSON(strings.NewReader(messageTransmitterABI))
	if err != nil {
		return common.Hash{}, fmt.Errorf("parse ABI: %w", err)
	}

	msgBytes, err := hex.DecodeString(strings.TrimPrefix(att.Message, "0x"))
	if err != nil {
		return common.Hash{}, fmt.Errorf("decode message: %w", err)
	}
	attBytes, err := hex.DecodeString(strings.TrimPrefix(att.Attestation, "0x"))
	if err != nil {
		return common.Hash{}, fmt.Errorf("decode attestation: %w", err)
	}

	contract := bind.NewBoundContract(
		common.HexToAddress(config.BaseMessageTransmitter),
		parsedABI, base, base, base,
	)

	tx, err := contract.Transact(auth, "receiveMessage", msgBytes, attBytes)
	if err != nil {
		return common.Hash{}, fmt.Errorf("send receiveMessage: %w", err)
	}

	receipt, err := bind.WaitMined(ctx, base, tx)
	if err != nil {
		return tx.Hash(), fmt.Errorf("wait mined: %w", err)
	}
	if receipt.Status != types.ReceiptStatusSuccessful {
		return tx.Hash(), fmt.Errorf("mint tx reverted: %s", tx.Hash().Hex())
	}
	return tx.Hash(), nil
}
