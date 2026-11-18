package platform

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/getsentry/sentry-go"
	"github.com/jackc/pgx/v5/pgxpool"
)

type capturedTrackingEnvelope struct {
	Path        string           `json:"path"`
	ContentType string           `json:"content_type"`
	Auth        string           `json:"auth"`
	Events      []map[string]any `json:"events"`
}

// This uses the real asynchronous SDK HTTP transport and an actual HTTP
// application server. No outbound request leaves the local capture server.
func TestErrorTrackingHTTPTransportContract(t *testing.T) {
	if os.Getenv("NORTH55_SENTRY_DEBUG_TEST") != "" {
		originalWriter := sentry.DebugLogger.Writer()
		sentry.DebugLogger.SetOutput(os.Stderr)
		t.Cleanup(func() { sentry.DebugLogger.SetOutput(originalWriter) })
	}
	var mu sync.Mutex
	var envelopes []capturedTrackingEnvelope
	capture := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		envelope := capturedTrackingEnvelope{Path: r.URL.Path, ContentType: r.Header.Get("Content-Type"), Auth: r.Header.Get("X-Sentry-Auth")}
		reader := bufio.NewReader(r.Body)
		if _, err := reader.ReadString('\n'); err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		for {
			line, err := reader.ReadString('\n')
			if err == io.EOF && strings.TrimSpace(line) == "" {
				break
			}
			if strings.TrimSpace(line) == "" {
				continue
			}
			var header struct {
				Type   string `json:"type"`
				Length int    `json:"length"`
			}
			if err := json.Unmarshal([]byte(line), &header); err != nil {
				t.Error(err)
				break
			}
			payload := make([]byte, header.Length)
			if _, err := io.ReadFull(reader, payload); err != nil {
				t.Error(err)
				break
			}
			if header.Type == "event" || header.Type == "transaction" {
				var event map[string]any
				if err := json.Unmarshal(payload, &event); err != nil {
					t.Error(err)
					break
				}
				envelope.Events = append(envelope.Events, event)
			}
		}
		mu.Lock()
		envelopes = append(envelopes, envelope)
		mu.Unlock()
		w.WriteHeader(200)
	}))
	defer capture.Close()
	tracker, err := newErrorTracker(strings.Replace(capture.URL, "http://", "http://public@", 1)+"/1", "test", nil, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer tracker.Close()
	original := slog.Default()
	defer slog.SetDefault(original)
	logger, err := NewApplicationLogger(io.Discard, "INFO", false, tracker)
	if err != nil {
		t.Fatal(err)
	}
	slog.SetDefault(logger)
	var db *pgxpool.Pool
	if dsn := os.Getenv("NORTH55_SENTRY_TEST_DB"); dsn != "" {
		cfg, err := pgxpool.ParseConfig(dsn)
		if err != nil {
			t.Fatal(err)
		}
		cfg.ConnConfig.Tracer = tracker.QueryTracer()
		db, err = pgxpool.NewWithConfig(context.Background(), cfg)
		if err != nil {
			t.Fatal(err)
		}
		defer db.Close()
	}
	router := NewRouter()
	router.HandleFunc("GET /sentry-source-probe/{item_id}", Wrap(func(w http.ResponseWriter, r *http.Request) error {
		LogModule("app.audit", r.Context()).Info("Probe breadcrumb", "action", "probe.info", "writer_instance_id", "synthetic-writer")
		switch r.PathValue("item_id") {
		case "error-log":
			LogModule("app.audit", r.Context()).Error("Probe error log", "action", "probe.error", "writer_instance_id", "synthetic-writer")
		case "handled":
			return Error(409, "Synthetic handled source failure")
		case "unhandled":
			return errors.New("Synthetic unhandled source failure")
		case "sql":
			var value string
			if err := db.QueryRow(r.Context(), "SELECT CAST($1 AS VARCHAR) AS sentry_probe", "synthetic-private-bind").Scan(&value); err != nil {
				return err
			}
		case "sql-error":
			if _, err := db.Exec(r.Context(), "SELECT 1 / 0 AS sentry_probe"); err == nil {
				return errors.New("expected division error")
			}
			return Error(409, "Synthetic handled SQL failure")
		}
		WriteJSON(w, 200, map[string]bool{"ok": true})
		return nil
	}))
	handler := Middleware(Config{ErrorTracker: tracker}, router)
	requestFinished := make(chan struct{}, 1)
	application := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handler.ServeHTTP(w, r)
		requestFinished <- struct{}{}
	}))
	defer application.Close()
	items := []string{"ok", "error-log", "handled", "unhandled", "parent-sampled", "parent-unsampled"}
	if db != nil {
		items = append(items, "sql", "sql-error")
	}
	var statuses []map[string]any
	for _, item := range items {
		mu.Lock()
		prior := len(envelopes)
		mu.Unlock()
		request, _ := http.NewRequest("GET", application.URL+"/sentry-source-probe/"+item, nil)
		request.Header.Set("X-Request-ID", "sentry-source-"+item)
		request.Header.Set("Authorization", "Bearer synthetic-sensitive-token")
		request.Header.Set("Cookie", "synthetic=private")
		if strings.HasPrefix(item, "parent-") {
			decision := "1"
			if item == "parent-unsampled" {
				decision = "0"
			}
			request.Header.Set("sentry-trace", "0123456789abcdef0123456789abcdef-0123456789abcdef-"+decision)
		}
		response, err := application.Client().Do(request)
		if err != nil {
			t.Fatal(err)
		}
		io.Copy(io.Discard, response.Body)
		response.Body.Close()
		select {
		case <-requestFinished:
		case <-time.After(5 * time.Second):
			t.Fatal("request middleware did not finish")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		flushed := tracker.Flush(ctx)
		cancel()
		if !flushed {
			t.Fatal("flush timeout")
		}
		mu.Lock()
		var errorsCount, transactions int
		for _, envelope := range envelopes[prior:] {
			if envelope.Path != "/api/1/envelope/" || envelope.ContentType != "application/x-sentry-envelope" || !strings.Contains(envelope.Auth, "sentry_key=public") {
				t.Error("invalid SDK request", envelope.Path, envelope.ContentType, envelope.Auth)
			}
			for _, event := range envelope.Events {
				if event["type"] == "transaction" {
					transactions++
				} else {
					errorsCount++
				}
				raw, _ := json.Marshal(event)
				for _, secret := range []string{"synthetic-sensitive-token", "synthetic=private", "synthetic-private-bind"} {
					if strings.Contains(string(raw), secret) {
						t.Error("unexpected private data", item, secret)
					}
				}
			}
		}
		mu.Unlock()
		wantErrors := map[string]int{"error-log": 1, "unhandled": 2}[item]
		wantTransactions := 1
		if item == "parent-unsampled" {
			wantTransactions = 0
		}
		if errorsCount != wantErrors || transactions != wantTransactions {
			t.Fatal(item, errorsCount, transactions)
		}
		statuses = append(statuses, map[string]any{"item": item, "status": response.StatusCode, "new_error_events": errorsCount, "transactions": transactions})
	}
	if path := os.Getenv("NORTH55_SENTRY_CAPTURE_REPORT"); path != "" {
		mu.Lock()
		report, err := json.MarshalIndent(map[string]any{"statuses": statuses, "envelopes": envelopes, "database_queries": db != nil}, "", "  ")
		mu.Unlock()
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, append(report, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
	t.Log(fmt.Sprintf("real HTTP transport: %d scenarios; SQL enabled: %v", len(items), db != nil))
}
