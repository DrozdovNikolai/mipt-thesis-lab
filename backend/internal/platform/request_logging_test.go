package platform

import (
	"bytes"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func captureApplicationLogs(t *testing.T) *bytes.Buffer {
	t.Helper()
	var output bytes.Buffer
	logger, err := NewApplicationLogger(&output, "INFO", false)
	if err != nil {
		t.Fatal(err)
	}
	previous := slog.Default()
	slog.SetDefault(logger)
	t.Cleanup(func() { slog.SetDefault(previous) })
	return &output
}

func TestRequestLoggingCapturesOutcomeAndAuthenticatedUser(t *testing.T) {
	for _, tc := range []struct {
		name       string
		status     int
		unhandled  bool
		panicValue bool
	}{
		{"anonymous", 200, false, false},
		{"denied", 403, false, false},
		{"handled-500", 500, false, false},
		{"unexpected-error", 500, true, false},
		{"panic", 500, true, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output := captureApplicationLogs(t)
			handler := Middleware(Config{}, Wrap(func(w http.ResponseWriter, r *http.Request) error {
				if tc.name != "anonymous" {
					SetRequestUser(r, "public-user-id")
				}
				if tc.panicValue {
					panic("synthetic panic")
				}
				if tc.unhandled {
					return errors.New("synthetic failure")
				}
				if tc.status != 200 {
					return Error(tc.status, "handled response")
				}
				WriteJSON(w, 200, map[string]bool{"ok": true})
				return nil
			}))
			request := httptest.NewRequest("GET", "/api/users/me", nil)
			request.Header.Set("X-Request-ID", "upstream-id")
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != tc.status {
				t.Fatal("status changed", response.Code)
			}
			lines := strings.Split(strings.TrimSpace(output.String()), "\n")
			if len(lines) != 1 {
				t.Fatalf("expected one request record, got %s", output.String())
			}
			var log map[string]any
			if err := json.Unmarshal([]byte(lines[0]), &log); err != nil {
				t.Fatal(err)
			}
			if log["request_id"] != "upstream-id" || log["method"] != "GET" || log["path"] != "/api/users/me" {
				t.Fatal("missing request identity", log)
			}
			if duration, ok := log["duration_ms"].(float64); !ok || duration < 0 {
				t.Fatal("invalid duration", log)
			}
			if tc.name == "anonymous" {
				if log["user_id"] != nil {
					t.Fatal("anonymous user", log)
				}
			} else if log["user_id"] != "public-user-id" {
				t.Fatal("authenticated user lost", log)
			}
			if tc.unhandled {
				if log["level"] != "ERROR" || log["message"] != "Request failed" || log["exception"] == nil || log["status_code"] != nil {
					t.Fatal("unexpected error not distinguished", log)
				}
				if response.Header().Get("X-Request-ID") != "" {
					t.Fatal("unhandled response headers changed")
				}
			} else if log["level"] != "INFO" || log["message"] != "Request completed" || log["status_code"] != float64(tc.status) {
				t.Fatal("handled outcome", log)
			}
		})
	}
}

func TestRequestLoggingExclusionsAndGeneratedID(t *testing.T) {
	for _, tc := range []struct {
		path string
		log  bool
	}{
		{"/api/health", false}, {"/api/health/ready", false},
		{"/api/health/detailed", false}, {"/metrics", false},
		{"/", true}, {"/api/health/backups", true}, {"/v2/health", true},
	} {
		t.Run(tc.path, func(t *testing.T) {
			output := captureApplicationLogs(t)
			handler := Middleware(Config{}, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest("GET", tc.path, nil))
			if (output.Len() > 0) != tc.log {
				t.Fatal("wrong exclusion", output.String())
			}
			if tc.log {
				var record map[string]any
				if err := json.Unmarshal(output.Bytes(), &record); err != nil {
					t.Fatal(err)
				}
				if record["request_id"] != response.Header().Get("X-Request-ID") || record["request_id"] == "" || record["status_code"] != float64(204) {
					t.Fatal("generated identity", record)
				}
			}
		})
	}
}

func TestRequestLoggingStartsAfterCORSAndRateLimit(t *testing.T) {
	output := captureApplicationLogs(t)
	handler := Middleware(Config{EnableCORS: true, AllowedOrigins: []string{"https://app.example"}, EnableRateLimit: true, RateLimitPerMinute: 1, RateLimitPerSecond: 1}, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
	preflight := httptest.NewRequest("OPTIONS", "/api/users/me", nil)
	preflight.Header.Set("Origin", "https://app.example")
	preflight.Header.Set("Access-Control-Request-Method", "GET")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, preflight)
	if response.Code != 200 || output.Len() != 0 {
		t.Fatal("preflight logged or changed", response.Code, output.String())
	}
	for i, status := range []int{204, 429} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", "/api/users/me", nil))
		if response.Code != status {
			t.Fatal("rate status", i, response.Code)
		}
	}
	if bytes.Count(output.Bytes(), []byte("\n")) != 1 {
		t.Fatal("rejected request logged", output.String())
	}
}

func TestExcludedProbeStillReportsUnexpectedFailure(t *testing.T) {
	output := captureApplicationLogs(t)
	handler := Middleware(Config{}, Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return errors.New("synthetic probe failure")
	}))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest("GET", "/api/health", nil))
	var record map[string]any
	if err := json.Unmarshal(output.Bytes(), &record); err != nil {
		t.Fatal(err)
	}
	if response.Code != 500 || record["level"] != "ERROR" || record["logger"] != "app.main" || !strings.Contains(record["exception"].(string), "synthetic probe failure") {
		t.Fatal("probe failure lost", record)
	}
}
