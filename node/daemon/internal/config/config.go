package config

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Network endpoints (testnet). Not secret; kept here to keep .env focused on secrets/addresses.
const (
	ArbRPC  = "https://sepolia-rollup.arbitrum.io/rpc"
	BaseRPC = "https://sepolia.base.org"

	ArbChainID  = 421614
	BaseChainID = 84532

	// LayerZero EIDs (testnet)
	ArbEID  = 40231
	BaseEID = 40245

	// CCTP domains
	ArbCCTPDomain  = 3
	BaseCCTPDomain = 6

	// Circle attestation API (testnet/sandbox)
	CircleIrisAPI = "https://iris-api-sandbox.circle.com"

	// CCTP MessageTransmitter on Base Sepolia (where mints are submitted)
	BaseMessageTransmitter = "0x7865fAfC2db2093669d92c0F33AeEF291086BEFD"
)

// Config holds all secrets and deployed addresses loaded from .env.local.
type Config struct {
	PrivateKey       string
	VaultAddress     string
	RouterAddress    string
	MessengerAddress string
	DstEid           uint32
}

// Load reads key=value pairs from the given .env file and returns a validated Config.
func Load(path string) (*Config, error) {
	vars, err := parseEnvFile(path)
	if err != nil {
		return nil, err
	}

	c := &Config{
		PrivateKey:       vars["PRIVATE_KEY"],
		VaultAddress:     vars["TAP_VAULT_ADDRESS"],
		RouterAddress:    vars["TAP_ROUTER_ADDRESS"],
		MessengerAddress: vars["TAP_MESSENGER_ADDRESS"],
	}

	if err := c.validate(vars); err != nil {
		return nil, err
	}
	return c, nil
}

func (c *Config) validate(vars map[string]string) error {
	if !strings.HasPrefix(c.PrivateKey, "0x") || len(c.PrivateKey) != 66 {
		return fmt.Errorf("PRIVATE_KEY missing or malformed (need 0x + 64 hex)")
	}
	for name, val := range map[string]string{
		"TAP_VAULT_ADDRESS":     c.VaultAddress,
		"TAP_ROUTER_ADDRESS":    c.RouterAddress,
		"TAP_MESSENGER_ADDRESS": c.MessengerAddress,
	} {
		if !strings.HasPrefix(val, "0x") || len(val) != 42 {
			return fmt.Errorf("%s missing or malformed (need 0x + 40 hex)", name)
		}
	}
	dstRaw, ok := vars["DST_EID"]
	if !ok || dstRaw == "" {
		return fmt.Errorf("DST_EID missing")
	}
	d, err := strconv.ParseUint(dstRaw, 10, 32)
	if err != nil {
		return fmt.Errorf("DST_EID not a uint32: %w", err)
	}
	c.DstEid = uint32(d)
	return nil
}

// parseEnvFile reads a simple KEY=VALUE file, ignoring blanks and # comments.
func parseEnvFile(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open env file: %w", err)
	}
	defer f.Close()

	out := make(map[string]string)
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		eq := strings.IndexByte(line, '=')
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		val := strings.TrimSpace(line[eq+1:])
		out[key] = val
	}
	if err := sc.Err(); err != nil {
		return nil, fmt.Errorf("read env file: %w", err)
	}
	return out, nil
}
