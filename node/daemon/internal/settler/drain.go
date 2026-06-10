package settler

import (
	"context"
	"log"
	"strings"

	"github.com/ethereum/go-ethereum/common"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/bridge"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

// drain attempts to settle each pending swap: fetch its CCTP attestation and,
// once ready, submit the mint on Base. Swaps whose attestation isn't ready yet
// are left pending and retried next tick. Successfully minted (or already-minted)
// swaps are removed from pending.
func (s *Settler) drain(ctx context.Context) {
	// Snapshot pending under lock so we don't hold it during network calls.
	s.mu.Lock()
	snapshot := make([]SwapEvent, 0, len(s.pending))
	for _, e := range s.pending {
		snapshot = append(snapshot, e)
	}
	s.mu.Unlock()

	for _, e := range snapshot {
		att, err := bridge.FetchAttestation(ctx, config.ArbCCTPDomain, e.TxHash.Hex())
		if err != nil {
			// Attestation not ready yet is the normal case — retry next tick.
			continue
		}

		mintTx, err := bridge.SubmitMint(ctx, s.base, s.privKey, att)
		if err != nil {
			// "Nonce already used" means the mint already happened (executor path
			// or prior run). Drop it from pending rather than retry forever.
			if isAlreadyMinted(err) {
				log.Printf("settler: swap %s already minted, removing from pending", e.SwapID.Hex())
				s.remove(e.SwapID)
				continue
			}
			log.Printf("settler: mint failed for swap %s: %v (will retry)", e.SwapID.Hex(), err)
			continue
		}

		if rtx, rerr := bridge.Reconcile(ctx, s.base, s.privKey, s.vault); rerr != nil {
			log.Printf("settler: reconcile after mint failed for %s: %v (mint OK, vault will reconcile on next arrival)", e.SwapID.Hex(), rerr)
		} else {
			log.Printf("settler: reconciled swap %s — tx %s", e.SwapID.Hex(), rtx.Hex())
		}
		log.Printf("settler: SETTLED swap %s — mint tx %s", e.SwapID.Hex(), mintTx.Hex())
		s.remove(e.SwapID)
	}
}

func (s *Settler) remove(swapID common.Hash) {
	s.mu.Lock()
	delete(s.pending, swapID)
	s.mu.Unlock()
}

// isAlreadyMinted detects the CCTP "nonce already used" revert.
func isAlreadyMinted(err error) bool {
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "nonce already used") ||
		strings.Contains(msg, "message already") ||
		strings.Contains(msg, "already used")
}
