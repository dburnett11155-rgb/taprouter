package bridge

import (
	"context"
	"fmt"
	"strings"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
)

const tapVaultReconcileABI = `[{"inputs":[],"name":"reconcile","outputs":[],"stateMutability":"nonpayable","type":"function"}]`

// Reconcile calls reconcile() on the TapVault to clear fronted debt against
// USDC that has actually arrived. Trustless: a call with no real funds clears
// nothing (enforced by the contract). Returns the tx hash.
func Reconcile(ctx context.Context, base *ethclient.Client, privKeyHex string, vault common.Address) (common.Hash, error) {
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

	parsedABI, err := abi.JSON(strings.NewReader(tapVaultReconcileABI))
	if err != nil {
		return common.Hash{}, fmt.Errorf("parse ABI: %w", err)
	}

	contract := bind.NewBoundContract(vault, parsedABI, base, base, base)

	tx, err := contract.Transact(auth, "reconcile")
	if err != nil {
		return common.Hash{}, fmt.Errorf("send reconcile: %w", err)
	}

	receipt, err := bind.WaitMined(ctx, base, tx)
	if err != nil {
		return tx.Hash(), fmt.Errorf("wait mined: %w", err)
	}
	if receipt.Status != types.ReceiptStatusSuccessful {
		return tx.Hash(), fmt.Errorf("reconcile reverted: %s", tx.Hash().Hex())
	}
	return tx.Hash(), nil
}
