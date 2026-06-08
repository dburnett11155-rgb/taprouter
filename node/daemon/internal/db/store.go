package db

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	"github.com/redis/go-redis/v9"
)

const lastBlockKey = "taprouter:settler:lastBlock"

// Store is a Redis-backed persistence layer for daemon state.
type Store struct {
	rdb *redis.Client
}

// New connects to Redis at addr (e.g. "localhost:6379") and verifies it.
func New(ctx context.Context, addr string) (*Store, error) {
	rdb := redis.NewClient(&redis.Options{Addr: addr})
	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}
	return &Store{rdb: rdb}, nil
}

// Close shuts down the Redis client.
func (s *Store) Close() error {
	return s.rdb.Close()
}

// SaveLastBlock persists the settler's last-scanned block.
func (s *Store) SaveLastBlock(ctx context.Context, block uint64) error {
	return s.rdb.Set(ctx, lastBlockKey, block, 0).Err()
}

// LoadLastBlock returns the persisted last-scanned block. Returns (0, false, nil)
// if no value is stored yet (first run).
func (s *Store) LoadLastBlock(ctx context.Context) (block uint64, found bool, err error) {
	val, err := s.rdb.Get(ctx, lastBlockKey).Result()
	if errors.Is(err, redis.Nil) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("redis get lastBlock: %w", err)
	}
	block, err = strconv.ParseUint(val, 10, 64)
	if err != nil {
		return 0, false, fmt.Errorf("parse lastBlock %q: %w", val, err)
	}
	return block, true, nil
}
