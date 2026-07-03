package main

import (
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"
)

type AssemblerHealth struct {
	mutex         sync.RWMutex
	lastProcessed time.Time
}

func NewAssemblerHealth(now time.Time) *AssemblerHealth {
	return &AssemblerHealth{
		lastProcessed: now,
	}
}

func (health *AssemblerHealth) StartServer(addr string) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", health.HandleHealthz)

	server := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Println("Health server stopped:", err)
		}
	}()
}

func (health *AssemblerHealth) MarkProcessed() {
	health.markProcessedAt(time.Now())
}

func (health *AssemblerHealth) markProcessedAt(now time.Time) {
	health.mutex.Lock()
	defer health.mutex.Unlock()
	health.lastProcessed = now
}

func (health *AssemblerHealth) LastProcessed() time.Time {
	health.mutex.RLock()
	defer health.mutex.RUnlock()
	return health.lastProcessed
}

func (health *AssemblerHealth) HandleHealthz(response http.ResponseWriter, request *http.Request) {
	response.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = fmt.Fprintf(response, "%d\n", health.LastProcessed().Unix())
}
