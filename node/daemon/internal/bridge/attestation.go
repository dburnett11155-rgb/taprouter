package bridge

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/dburnett11155-rgb/taprouter/node/daemon/internal/config"
)

// Attestation holds a Circle CCTP message + its attestation signature.
type Attestation struct {
	Message     string // hex message bytes
	Attestation string // hex attestation signature
}

type irisResponse struct {
	Messages []struct {
		Attestation string `json:"attestation"`
		Message     string `json:"message"`
		Status      string `json:"status"`
	} `json:"messages"`
}

// FetchAttestation queries Circle's iris API for the attestation of a burn,
// identified by source domain and source tx hash. Returns once attestation
// is available, or error on timeout/failure.
func FetchAttestation(ctx context.Context, srcDomain uint32, srcTxHash string) (*Attestation, error) {
	url := fmt.Sprintf("%s/v1/messages/%d/%s", config.CircleIrisAPI, srcDomain, srcTxHash)
	client := &http.Client{Timeout: 15 * time.Second}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("iris request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read iris body: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("iris status %d: %s", resp.StatusCode, string(body))
	}

	var parsed irisResponse
	if err := json.Unmarshal(body, &parsed); err != nil {
		return nil, fmt.Errorf("parse iris json: %w", err)
	}
	if len(parsed.Messages) == 0 {
		return nil, fmt.Errorf("no messages for tx %s (domain %d)", srcTxHash, srcDomain)
	}

	m := parsed.Messages[0]
	if m.Attestation == "" || m.Attestation == "PENDING" {
		return nil, fmt.Errorf("attestation not ready (status=%q)", m.Status)
	}
	return &Attestation{Message: m.Message, Attestation: m.Attestation}, nil
}
