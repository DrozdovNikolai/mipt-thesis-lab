package platform

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

func TestRateLimitFrozenPythonVectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/rate_limits_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Minute, Second int64
		Checks         []struct {
			At               float64
			Client           string
			Allowed          bool
			Remaining, Reset int64
		}
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, scenario := range cases {
		limiter := newMemoryRateLimiter(scenario.Minute, scenario.Second)
		for _, check := range scenario.Checks {
			got := limiter.allow(check.Client, check.At)
			if got.Allowed != check.Allowed || got.Limit != scenario.Minute || got.Remaining != check.Remaining || got.Reset != check.Reset {
				t.Fatalf("quota %d/%d at %v: got %+v want %+v", scenario.Minute, scenario.Second, check.At, got, check)
			}
		}
	}
}

func TestRateLimitMemoryConcurrentAdmission(t *testing.T) {
	limiter := newMemoryRateLimiter(17, 17)
	var accepted atomic.Int64
	var group sync.WaitGroup
	for range 200 {
		group.Go(func() {
			if limiter.allow("one-client", 1000).Allowed {
				accepted.Add(1)
			}
		})
	}
	group.Wait()
	if accepted.Load() != 17 {
		t.Fatalf("accepted %d requests, want 17", accepted.Load())
	}
	if !limiter.allow("another-client", 1000).Allowed || !limiter.allow("one-client", 1060).Allowed {
		t.Fatal("independent client or expired window was rejected")
	}
}

type fakeRateRedis struct {
	redis.Scripter
	loads, evals     int
	loadErr, evalErr error
}

func (f *fakeRateRedis) ScriptLoad(ctx context.Context, script string) *redis.StringCmd {
	f.loads++
	cmd := redis.NewStringCmd(ctx)
	cmd.SetVal("script-sha")
	cmd.SetErr(f.loadErr)
	return cmd
}
func (f *fakeRateRedis) EvalSha(ctx context.Context, sha string, keys []string, args ...any) *redis.Cmd {
	f.evals++
	cmd := redis.NewCmd(ctx)
	cmd.SetVal([]any{int64(1), int64(1), int64(1)})
	cmd.SetErr(f.evalErr)
	return cmd
}

func TestRateLimitFallbackRetryAndHeaderDifference(t *testing.T) {
	client := &fakeRateRedis{loadErr: errors.New("connection refused")}
	limiter := NewRedisRateLimiter(client, 5, 1)
	now := time.Unix(1000, 0)
	limiter.now = func() time.Time { return now }
	if got := limiter.Allow(context.Background(), "a"); !got.Allowed || got.Remaining != 4 {
		t.Fatal(got)
	}
	if got := limiter.Allow(context.Background(), "a"); got.Allowed || got.Remaining != 3 {
		t.Fatal(got)
	}
	if client.loads != 1 || client.evals != 0 {
		t.Fatal("Redis retried before cooldown")
	}
	now = now.Add(30 * time.Second)
	client.loadErr = nil
	if got := limiter.Allow(context.Background(), "a"); !got.Allowed || got.Remaining != 4 {
		t.Fatal(got)
	}
	if client.loads != 2 || client.evals != 1 {
		t.Fatal("missing Redis retry")
	}
	client.evalErr = errors.New("NOSCRIPT")
	if got := limiter.Allow(context.Background(), "a"); !got.Allowed || got.Remaining != 3 {
		t.Fatal(got)
	}
	client.evalErr = nil
	if got := limiter.Allow(context.Background(), "a"); got.Allowed || got.Remaining != 2 {
		t.Fatal(got)
	}
	if client.evals != 2 {
		t.Fatal("failed EVAL bypassed cooldown")
	}
	now = now.Add(30 * time.Second)
	if got := limiter.Allow(context.Background(), "a"); !got.Allowed {
		t.Fatal(got)
	}
	if client.loads != 2 || client.evals != 3 {
		t.Fatal("source retry must reuse loaded SHA")
	}
	if got := limiter.Allow(context.Background(), "a"); !got.Allowed || client.evals != 3 {
		t.Fatal("source stays in fallback until the next probe after a recovered EVAL", got)
	}
}

type recordingRateLimiter struct {
	decision RateLimitDecision
	calls    int
	client   string
}

func (l *recordingRateLimiter) Allow(_ context.Context, client string) RateLimitDecision {
	l.calls++
	l.client = client
	return l.decision
}

func TestRateLimitMiddlewareOrderAndExemptions(t *testing.T) {
	for _, test := range []struct {
		name, path, method, origin, preflight string
		allowed                               bool
		status                                int
		limited, security, requestID          bool
	}{
		{"allowed", "/api/thing", "GET", "", "", true, 200, true, true, true},
		{"rejected", "/api/thing", "GET", "", "", false, 429, true, false, false},
		{"rejected-cors", "/api/thing", "GET", "https://allowed.example", "", false, 429, true, false, false},
		{"preflight", "/api/thing", "OPTIONS", "https://allowed.example", "POST", false, 200, false, false, false},
		{"denied-origin", "/api/thing", "OPTIONS", "https://other.example", "POST", false, 400, false, false, false},
		{"denied-method", "/api/thing", "OPTIONS", "https://allowed.example", "TRACE", false, 400, false, false, false},
		{"denied-both", "/api/thing", "OPTIONS", "https://other.example", "TRACE", false, 400, false, false, false},
		{"normal-options", "/api/thing", "OPTIONS", "", "", false, 429, true, false, false},
		{"root", "/", "GET", "", "", false, 200, false, true, true},
		{"health", "/api/health", "GET", "", "", false, 200, false, true, true},
		{"readiness", "/api/health/ready", "GET", "", "", false, 200, false, true, true},
		{"detailed", "/api/health/detailed", "GET", "", "", false, 200, false, true, true},
		{"metrics", "/metrics", "GET", "", "", false, 200, false, true, true},
		{"backups-counted", "/api/health/backups", "GET", "", "", false, 429, true, false, false},
		{"slash-counted", "/api/health/", "GET", "", "", false, 429, true, false, false},
		{"custom-prefix-counted", "/v2/health", "GET", "", "", false, 429, true, false, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			limiter := &recordingRateLimiter{decision: RateLimitDecision{Allowed: test.allowed, Limit: 5, Remaining: 2, Reset: 1060}}
			handler := Middleware(Config{EnableRateLimit: true, EnableCORS: true, AllowedOrigins: []string{"https://allowed.example"}},
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { WriteJSON(w, 200, map[string]bool{"ok": true}) }), limiter)
			request := httptest.NewRequest(test.method, "http://example.com"+test.path, nil)
			request.Header.Set("X-Request-ID", "upstream-id")
			request.Header.Set("X-Forwarded-For", " 192.0.2.1 , 192.0.2.2")
			if test.origin != "" {
				request.Header.Set("Origin", test.origin)
			}
			if test.preflight != "" {
				request.Header.Set("Access-Control-Request-Method", test.preflight)
			}
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != test.status || (limiter.calls == 1) != test.limited || (response.Header().Get("X-Frame-Options") == "DENY") != test.security || (response.Header().Get("X-Request-ID") == "upstream-id") != test.requestID {
				t.Fatalf("status=%d calls=%d headers=%v", response.Code, limiter.calls, response.Header())
			}
			if test.limited && limiter.client != "192.0.2.1" {
				t.Fatal(limiter.client)
			}
			if test.status == 429 && (response.Header().Get("Retry-After") != "60" || response.Body.String() != `{"detail": "Rate limit exceeded. Please slow down."}`) {
				t.Fatal(response.Body.String())
			}
			if test.origin == "https://allowed.example" && response.Header().Get("Access-Control-Allow-Origin") != test.origin {
				t.Fatal(response.Header())
			}
			if test.preflight != "" && response.Header().Get("Vary") != "Origin" {
				t.Fatal(response.Header())
			}
			if test.name == "denied-both" && response.Body.String() != "Disallowed CORS origin, method" {
				t.Fatal(response.Body.String())
			}
		})
	}
}

func TestRateLimitConfiguration(t *testing.T) {
	t.Setenv("ENABLE_RATE_LIMIT", "on")
	t.Setenv("RATE_LIMIT_PER_MINUTE", "5.0")
	t.Setenv("RATE_LIMIT_PER_SECOND", "0")
	config, err := LoadConfig()
	if err != nil || !config.EnableRateLimit || config.RateLimitPerMinute != 5 || config.RateLimitPerSecond != 0 {
		t.Fatal("rate-limit configuration", err)
	}
	for _, key := range []string{"ENABLE_RATE_LIMIT", "RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_PER_SECOND"} {
		t.Run(key, func(t *testing.T) {
			t.Setenv(key, "invalid")
			if _, err := LoadConfig(); err == nil || !strings.Contains(err.Error(), key) {
				t.Fatal(err)
			}
		})
	}
}

func TestRateLimitDisabledAndWildcardCORS(t *testing.T) {
	for _, test := range []struct {
		name, origin, cookie, wantOrigin, wantVary string
		withCookie                                 bool
	}{
		{"no-cookie", "https://example.com", "", "*", "", false},
		{"cookie", "https://example.com", "session=abc", "https://example.com", "Origin", true},
		{"empty-cookie", "https://example.com", "", "https://example.com", "Origin", true},
		{"empty-origin", "", "", "*", "", false},
	} {
		t.Run(test.name, func(t *testing.T) {
			limiter := &recordingRateLimiter{}
			handler := Middleware(Config{EnableCORS: true, AllowedOrigins: []string{"*"}},
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { WriteJSON(w, 200, map[string]bool{"ok": true}) }), limiter)
			request := httptest.NewRequest("GET", "/api/thing", nil)
			request.Header.Set("Origin", test.origin)
			if test.withCookie {
				request.Header.Set("Cookie", test.cookie)
			}
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != 200 || limiter.calls != 0 || response.Header().Get("X-RateLimit-Limit") != "" {
				t.Fatal("disabled limiter ran", response.Code, response.Header())
			}
			if response.Header().Get("Access-Control-Allow-Origin") != test.wantOrigin || response.Header().Get("Vary") != test.wantVary {
				t.Fatal(response.Header())
			}
		})
	}
}
