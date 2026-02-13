package platform

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/getsentry/sentry-go"
)

type trackingTransport struct {
	mu     sync.Mutex
	events []*sentry.Event
}

func (t *trackingTransport) Configure(sentry.ClientOptions) {}
func (t *trackingTransport) SendEvent(e *sentry.Event) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.events = append(t.events, e)
}
func (t *trackingTransport) Flush(time.Duration) bool              { return true }
func (t *trackingTransport) FlushWithContext(context.Context) bool { return true }
func (t *trackingTransport) Close()                                {}
func (t *trackingTransport) snapshot() []*sentry.Event {
	t.mu.Lock()
	defer t.mu.Unlock()
	return append([]*sentry.Event(nil), t.events...)
}

func TestErrorTrackingDisabledAndOptions(t *testing.T) {
	t.Setenv("SENTRY_DSN", "http://public@unused.invalid/1")
	tracker, err := NewErrorTracker("", "test")
	if err != nil || tracker != nil {
		t.Fatal(tracker, err)
	}
	if !tracker.Flush(context.Background()) {
		t.Fatal("disabled flush")
	}
	tracker, err = NewErrorTracker("invalid", "test")
	if err == nil {
		t.Fatal("invalid DSN accepted")
	}
	transport := &trackingTransport{}
	tracker, err = newErrorTracker("http://public@unused.invalid/1", "test", transport, .2)
	if err != nil {
		t.Fatal(err)
	}
	defer tracker.client.Close()
	options := tracker.client.Options()
	if options.Environment != "test" || !options.EnableTracing || options.TracesSampleRate != .2 || options.SendDefaultPII || !options.DisableTelemetryBuffer {
		t.Fatal(options)
	}
}

func TestErrorTrackingSourceEventAndTransactionSemantics(t *testing.T) {
	transport := &trackingTransport{}
	tracker, err := newErrorTracker("http://public@unused.invalid/1", "test", transport, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer tracker.client.Close()
	router := NewRouter()
	router.HandleFunc("GET /probe/{item}", func(w http.ResponseWriter, r *http.Request) {
		tracker.CaptureLog(r.Context(), "app.audit", sentry.LevelInfo, "Probe breadcrumb", map[string]any{"action": "probe.info"}, nil)
		switch r.PathValue("item") {
		case "error-log":
			tracker.CaptureLog(r.Context(), "app.audit", sentry.LevelError, "Probe error log", map[string]any{"action": "probe.error"}, nil)
		case "handled":
			WriteJSON(w, 409, map[string]string{"error": "handled"})
			return
		case "unhandled":
			failure := errors.New("Synthetic unhandled source failure")
			reportTrackedFailure(r.Context(), failure)
			tracker.CaptureLog(r.Context(), "app.core.middleware", sentry.LevelError, "Request failed", map[string]any{"request_id": r.Header.Get("X-Request-ID")}, failure)
			http.Error(w, "Internal Server Error", 500)
			return
		}
		WriteJSON(w, 200, map[string]bool{"ok": true})
	})
	handler := tracker.Middleware(router, router)
	for i, item := range []string{"ok", "error-log", "handled", "unhandled"} {
		prior := len(transport.snapshot())
		request := httptest.NewRequest("GET", "/probe/"+item, nil)
		request.Header.Set("X-Request-ID", item)
		request.Header.Set("Authorization", "Bearer synthetic-private-token")
		request.Header.Set("Cookie", "private=synthetic")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		events := transport.snapshot()[prior:]
		errorsCount := 0
		transactionsCount := 0
		for _, e := range events {
			if e.Type == "transaction" {
				transactionsCount++
				if e.Transaction != "/probe/{item}" {
					t.Fatal(e.Transaction)
				}
				continue
			}
			errorsCount++
			if e.Environment != "test" || len(e.Breadcrumbs) == 0 || e.Request == nil || e.Request.Headers["X-Request-Id"] != item {
				t.Fatal("missing scoped event", e)
			}
			raw, _ := json.Marshal(e)
			if strings.Contains(string(raw), "synthetic-private-token") || strings.Contains(string(raw), "private=synthetic") {
				t.Fatal("sensitive request headers", string(raw))
			}
		}
		if errorsCount != []int{0, 1, 0, 2}[i] || transactionsCount != 1 {
			t.Fatal(item, errorsCount, transactionsCount)
		}
	}
}

func TestErrorTrackingThroughApplicationMiddleware(t *testing.T) {
	transport := &trackingTransport{}
	tracker, err := newErrorTracker("http://public@unused.invalid/1", "test", transport, 1)
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
	router := NewRouter()
	router.HandleFunc("GET /full/{item}", Wrap(func(w http.ResponseWriter, r *http.Request) error {
		LogModule("app.audit", r.Context()).Info("Probe breadcrumb", "action", "probe.info", "writer_instance_id", "source-extra")
		switch r.PathValue("item") {
		case "error-log":
			LogModule("app.audit", r.Context()).Error("Probe error log", "action", "probe.error", "writer_instance_id", "source-extra")
		case "handled":
			return Error(409, "Synthetic handled source failure")
		case "unhandled":
			return errors.New("Synthetic unhandled source failure")
		}
		WriteJSON(w, 200, map[string]bool{"ok": true})
		return nil
	}))
	handler := Middleware(Config{ErrorTracker: tracker}, router)
	for i, item := range []string{"ok", "error-log", "handled", "unhandled"} {
		prior := len(transport.snapshot())
		request := httptest.NewRequest("GET", "/full/"+item, nil)
		request.Header.Set("X-Request-ID", item)
		handler.ServeHTTP(httptest.NewRecorder(), request)
		errorsCount := 0
		for _, e := range transport.snapshot()[prior:] {
			if e.Type == "transaction" {
				continue
			}
			errorsCount++
			if e.Request == nil || e.Request.Headers["X-Request-Id"] != item || e.Transaction != "/full/{item}" {
				t.Fatal("request scope missing", e)
			}
			if len(e.Breadcrumbs) == 0 || e.Breadcrumbs[0].Data["writer_instance_id"] != "source-extra" {
				t.Fatal("lost source logging extra", e)
			}
			if item == "error-log" && e.Contexts["log"]["writer_instance_id"] != "source-extra" {
				t.Fatal("lost error log extra", e)
			}
		}
		if errorsCount != []int{0, 1, 0, 2}[i] {
			t.Fatal(item, errorsCount)
		}
	}
}
