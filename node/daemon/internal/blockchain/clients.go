package blockchain

import (
	"context"
	"fmt"
	"math/big"
	"time"

	"github.com/ethereum/go-ethereum/ethclient"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

// Clients holds connected RPC clients for both chains.
type Clients struct {
	Arb  *ethclient.Client
	Base *ethclient.Client
}

// Connect dials both chain RPCs and verifies each by fetching its chain ID.
func Connect(ctx context.Context) (*Clients, error) {
	arb, err := dialAndVerify(ctx, config.ArbRPC, config.ArbChainID, "Arbitrum Sepolia")
	if err != nil {
		return nil, err
	}
	base, err := dialAndVerify(ctx, config.BaseRPC, config.BaseChainID, "Base Sepolia")
	if err != nil {
		arb.Close()
		return nil, err
	}
	return &Clients{Arb: arb, Base: base}, nil
}

func dialAndVerify(ctx context.Context, rpc string, wantChainID int64, name string) (*ethclient.Client, error) {
	dialCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	cl, err := ethclient.DialContext(dialCtx, rpc)
	if err != nil {
		return nil, fmt.Errorf("%s: dial failed: %w", name, err)
	}

	idCtx, cancel2 := context.WithTimeout(ctx, 10*time.Second)
	defer cancel2()

	got, err := cl.ChainID(idCtx)
	if err != nil {
		cl.Close()
		return nil, fmt.Errorf("%s: chainID query failed: %w", name, err)
	}
	if got.Cmp(big.NewInt(wantChainID)) != 0 {
		cl.Close()
		return nil, fmt.Errorf("%s: chainID mismatch, want %d got %s", name, wantChainID, got.String())
	}
	return cl, nil
}

// Close shuts down both clients.
func (c *Clients) Close() {
	if c.Arb != nil {
		c.Arb.Close()
	}
	if c.Base != nil {
		c.Base.Close()
	}
}
