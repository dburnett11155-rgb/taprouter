package main

import (
	"context"
	"fmt"
	"log"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/bridge"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

func main() {
	// Second swap's burn tx on Arbitrum (source domain 3).
	txHash := "0xcfe6db67c524823e5af1c1247f73a2266b51029b5e419b3066931ccb65fe7578"

	att, err := bridge.FetchAttestation(context.Background(), config.ArbCCTPDomain, txHash)
	if err != nil {
		log.Fatalf("fetch failed: %v", err)
	}
	fmt.Println("Attestation fetched OK")
	fmt.Printf("  message    (len %d): %s...\n", len(att.Message), att.Message[:42])
	fmt.Printf("  attestation(len %d): %s...\n", len(att.Attestation), att.Attestation[:42])
}
