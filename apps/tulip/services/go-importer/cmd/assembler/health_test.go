package main

import (
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestHealthReturnsLastProcessedTimestamp(t *testing.T) {
	start := time.Date(2026, 7, 2, 12, 0, 0, 0, time.UTC)
	processed := start.Add(30 * time.Second)
	health := NewAssemblerHealth(start)

	health.markProcessedAt(processed)

	if got := health.LastProcessed(); !got.Equal(processed) {
		t.Fatalf("expected last processed timestamp %s, got %s", processed, got)
	}
}

func TestHealthzReturnsUnixTimestamp(t *testing.T) {
	processed := time.Unix(1782993630, 0)
	health := NewAssemblerHealth(processed)
	response := httptest.NewRecorder()

	health.HandleHealthz(response, httptest.NewRequest("GET", "/healthz", nil))

	if got := strings.TrimSpace(response.Body.String()); got != "1782993630" {
		t.Fatalf("expected unix timestamp response, got %q", got)
	}
}
