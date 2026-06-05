package settler

import (
	"context"
	"fmt"
	"math/big"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
)

// SwapInitiated event signature: SwapInitiated(bytes32,address,address,uint256)
var swapInitiatedTopic = crypto.Keccak256Hash(
	[]byte("SwapInitiated(bytes32,address,address,uint256)"),
)

// SwapEvent is a decoded SwapInitiated log.
type SwapEvent struct {
	SwapID    common.Hash
	Sender    common.Address
	Recipient common.Address
	Amount    *big.Int
	TxHash    common.Hash
	Block     uint64
}

// ScanSwaps returns all SwapInitiated events emitted by the router between
// fromBlock and toBlock (inclusive). toBlock = nil means "latest".
func ScanSwaps(ctx context.Context, arb *ethclient.Client, router common.Address, fromBlock, toBlock *big.Int) ([]SwapEvent, error) {
	q := ethereum.FilterQuery{
		FromBlock: fromBlock,
		ToBlock:   toBlock,
		Addresses: []common.Address{router},
		Topics:    [][]common.Hash{{swapInitiatedTopic}},
	}

	logs, err := arb.FilterLogs(ctx, q)
	if err != nil {
		return nil, fmt.Errorf("filter logs: %w", err)
	}

	out := make([]SwapEvent, 0, len(logs))
	for _, lg := range logs {
		ev, err := decodeSwap(lg)
		if err != nil {
			return nil, fmt.Errorf("decode log (tx %s): %w", lg.TxHash.Hex(), err)
		}
		out = append(out, ev)
	}
	return out, nil
}

func decodeSwap(lg types.Log) (SwapEvent, error) {
	// topics[0] = event sig; [1] = swapId; [2] = sender; [3] = recipient
	if len(lg.Topics) != 4 {
		return SwapEvent{}, fmt.Errorf("expected 4 topics, got %d", len(lg.Topics))
	}
	if len(lg.Data) != 32 {
		return SwapEvent{}, fmt.Errorf("expected 32 data bytes, got %d", len(lg.Data))
	}
	return SwapEvent{
		SwapID:    lg.Topics[1],
		Sender:    common.HexToAddress(lg.Topics[2].Hex()),
		Recipient: common.HexToAddress(lg.Topics[3].Hex()),
		Amount:    new(big.Int).SetBytes(lg.Data),
		TxHash:    lg.TxHash,
		Block:     lg.BlockNumber,
	}, nil
}
