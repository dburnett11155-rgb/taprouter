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

	latest, err := clients.Arb.BlockNumber(ctx)
	if err != nil {
		log.Fatalf("latest: %v", err)
	}

	router := common.HexToAddress(cfg.RouterAddress)
	s := settler.New(clients.Arb, clients.Base, cfg.PrivateKey, router, latest, 10*time.Second)

	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
		<-sig
		cancel()
	}()

	s.Run(ctx)
}
