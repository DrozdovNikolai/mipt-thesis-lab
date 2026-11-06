package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

func check() error {
	mode := "ready"
	if len(os.Args) == 2 {
		mode = os.Args[1]
	} else if len(os.Args) > 2 {
		return fmt.Errorf("usage: 55north-healthcheck [ready|live]")
	}
	if mode != "ready" && mode != "live" {
		return fmt.Errorf("unknown probe mode")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}
	prefix, exists := os.LookupEnv("API_PREFIX")
	if !exists {
		prefix = "/api"
	}
	path := strings.TrimRight(prefix, "/") + "/health"
	expected := "ok"
	if mode == "ready" {
		path += "/ready"
		expected = "ready"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1:"+port+path, nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return fmt.Errorf("probe request failed")
	}
	defer response.Body.Close()
	var payload struct {
		Status string `json:"status"`
	}
	if response.StatusCode != http.StatusOK || json.NewDecoder(io.LimitReader(response.Body, 16384)).Decode(&payload) != nil || payload.Status != expected {
		return fmt.Errorf("%s probe failed", mode)
	}
	return nil
}

func main() {
	if err := check(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
