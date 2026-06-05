package settler

import (
	"context"
	"log"
	"math/big"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/ethclient"
)

// Settler watches the router for swaps and tracks ones pending settlement.
type Settler struct {
	arb       *ethclient.Client
	base      *ethclient.Client
	privKey   string
	router    common.Address
	interval  time.Duration
	lastBlock uint64

	mu      sync.Mutex
	pending map[common.Hash]SwapEvent // keyed by swapId
}

// New creates a Settler starting from the given block, polling every interval.
func New(arb, base *ethclient.Client, privKey string, router common.Address, startBlock uint64, interval time.Duration) *Settler {
	return &Settler{
		arb:       arb,
		base:      base,
		privKey:   privKey,
		router:    router,
		interval:  interval,
		lastBlock: startBlock,
		pending:   make(map[common.Hash]SwapEvent),
	}
}

// PendingCount returns how many swaps are awaiting settlement.
func (s *Settler) PendingCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.pending)
}

// Run polls until ctx is cancelled. Each tick: discover new swaps into pending.
// (Step two will add draining pending -> mint.)
func (s *Settler) Run(ctx context.Context) {
	ticker := time.NewTicker(s.interval)
	defer ticker.Stop()

	log.Printf("settler: started, watching %s from block %d", s.router.Hex(), s.lastBlock)

	for {
		select {
		case <-ctx.Done():
			log.Printf("settler: stopping (pending=%d)", s.PendingCount())
			return
		case <-ticker.C:
			s.discover(ctx)
			s.drain(ctx)
		}
	}
}

// discover scans new blocks and adds any swaps to the pending set.
func (s *Settler) discover(ctx context.Context) {
	latest, err := s.arb.BlockNumber(ctx)
	if err != nil {
		log.Printf("settler: latest block error: %v", err)
		return
	}
	if latest <= s.lastBlock {
		return // no new blocks
	}

	from := new(big.Int).SetUint64(s.lastBlock + 1)
	to := new(big.Int).SetUint64(latest)

	events, err := ScanSwaps(ctx, s.arb, s.router, from, to)
	if err != nil {
		log.Printf("settler: scan error (blocks %d..%d): %v", from, to, err)
		return // don't advance lastBlock; retry same range next tick
	}

	s.mu.Lock()
	for _, e := range events {
		if _, exists := s.pending[e.SwapID]; !exists {
			s.pending[e.SwapID] = e
			log.Printf("settler: discovered swap %s (tx %s, amount %s) -> pending",
				e.SwapID.Hex(), e.TxHash.Hex(), e.Amount.String())
		}
	}
	s.mu.Unlock()

	s.lastBlock = latest
}
