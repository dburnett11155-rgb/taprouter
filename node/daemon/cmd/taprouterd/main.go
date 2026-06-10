package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ethereum/go-ethereum/common"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/blockchain"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/db"
	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/settler"
)

func main() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	cfg, err := config.Load("/home/dburnett11155/taprouter/.env.local")
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	clients, err := blockchain.Connect(ctx)
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer clients.Close()

	store, err := db.New(ctx, "localhost:6379")
	if err != nil {
		log.Fatalf("redis: %v", err)
	}
	defer store.Close()

	// Resume from persisted block if present, else start from current latest.
	startBlock, found, err := store.LoadLastBlock(ctx)
	if err != nil {
		log.Fatalf("load lastBlock: %v", err)
	}
	if !found {
		startBlock, err = clients.Arb.BlockNumber(ctx)
		if err != nil {
			log.Fatalf("latest: %v", err)
		}
		log.Printf("no saved position; starting from current block %d", startBlock)
	} else {
		log.Printf("resuming from saved block %d", startBlock)
	}

	router := common.HexToAddress(cfg.RouterAddress)
	vault := common.HexToAddress(cfg.VaultAddress)
	s := settler.New(clients.Arb, clients.Base, cfg.PrivateKey, router, vault, startBlock, 10*time.Second, store)

	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
		<-sig
		cancel()
	}()

	s.Run(ctx)
}
