package main

import (
	"context"
	"fmt"
	"log"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/blockchain"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

func main() {
	cfg, err := config.Load("/home/dburnett11155/taprouter/.env.local")
	if err != nil {
		log.Fatalf("config load failed: %v", err)
	}
	fmt.Println("TapRouter daemon — config loaded OK")
	fmt.Printf("  Router (Arb):     %s\n", cfg.RouterAddress)
	fmt.Printf("  Messenger (Base): %s\n", cfg.MessengerAddress)
	fmt.Printf("  Vault (Base):     %s\n", cfg.VaultAddress)
	fmt.Printf("  DstEid:           %d\n", cfg.DstEid)

	ctx := context.Background()
	clients, err := blockchain.Connect(ctx)
	if err != nil {
		log.Fatalf("chain connect failed: %v", err)
	}
	defer clients.Close()
	fmt.Println("Connected and verified both chains:")
	fmt.Println("  Arbitrum Sepolia (chain 421614) OK")
	fmt.Println("  Base Sepolia (chain 84532) OK")
}
