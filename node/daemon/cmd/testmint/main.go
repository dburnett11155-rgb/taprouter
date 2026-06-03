package main

import (
	"context"
	"fmt"
	"log"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/blockchain"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/bridge"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

func main() {
	ctx := context.Background()

	cfg, err := config.Load("/home/dburnett11155/taprouter/.env.local")
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	clients, err := blockchain.Connect(ctx)
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer clients.Close()

	// Second swap's burn tx (nonce 0x2d974), not yet minted.
	txHash := "0xcfe6db67c524823e5af1c1247f73a2266b51029b5e419b3066931ccb65fe7578"

	fmt.Println("Fetching attestation...")
	att, err := bridge.FetchAttestation(ctx, config.ArbCCTPDomain, txHash)
	if err != nil {
		log.Fatalf("fetch attestation: %v", err)
	}
	fmt.Println("Attestation ready. Submitting mint to Base...")

	mintTx, err := bridge.SubmitMint(ctx, clients.Base, cfg.PrivateKey, att)
	if err != nil {
		log.Fatalf("submit mint: %v", err)
	}
	fmt.Printf("MINT SUCCESS — tx: %s\n", mintTx.Hex())
}
