package platform

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// The two sorted sets are updated by one Redis operation, including under
// concurrent requests handled by different API processes.
const rateLimitScript = `
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 1)
local minute_count = redis.call('ZCARD', KEYS[1])
local second_count = redis.call('ZCARD', KEYS[2])
if minute_count >= tonumber(ARGV[2]) or second_count >= tonumber(ARGV[3]) then
    return {minute_count, second_count, 0}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('ZADD', KEYS[2], now, ARGV[4])
redis.call('EXPIRE', KEYS[1], 61)
redis.call('EXPIRE', KEYS[2], 2)
return {minute_count + 1, second_count + 1, 1}
`

type RateLimitDecision struct {
	Allowed                 bool
	Limit, Remaining, Reset int64
}

type RateLimiter interface {
	Allow(context.Context, string) RateLimitDecision
}

type memoryRateLimiter struct {
	mu             sync.Mutex
	minute, second int64
	requests       map[string]rateLimitWindows
}

type rateLimitWindows struct {
	minute, second []float64
}

func newMemoryRateLimiter(minute, second int64) *memoryRateLimiter {
	return &memoryRateLimiter{minute: minute, second: second, requests: map[string]rateLimitWindows{}}
}

func (l *memoryRateLimiter) Allow(_ context.Context, client string) RateLimitDecision {
	return l.allow(client, float64(time.Now().UnixNano())/1e9)
}

func rateRemaining(limit, count int64) int64 {
	if limit <= count {
		return 0
	}
	return limit - count
}

func (l *memoryRateLimiter) allow(client string, now float64) RateLimitDecision {
	l.mu.Lock()
	defer l.mu.Unlock()
	windows := l.requests[client]
	// Keep the source's independent windows: an entry removed from the second
	// window must not reappear there if the system clock moves backwards.
	windows.minute = cleanRateWindow(windows.minute, now, 60)
	windows.second = cleanRateWindow(windows.second, now, 1)
	l.requests[client] = windows
	minute, second := int64(len(windows.minute)), int64(len(windows.second))
	// The local fallback subtracts the attempted request even on rejection;
	// the Redis response subtracts only recorded requests.
	result := RateLimitDecision{Limit: l.minute, Remaining: rateRemaining(l.minute, minute+1), Reset: int64(now) + 60}
	if minute >= l.minute || second >= l.second {
		return result
	}
	windows.minute = append(windows.minute, now)
	windows.second = append(windows.second, now)
	l.requests[client] = windows
	result.Allowed = true
	return result
}

func cleanRateWindow(stamps []float64, now, window float64) []float64 {
	kept := stamps[:0]
	for _, stamp := range stamps {
		if now-stamp < window {
			kept = append(kept, stamp)
		}
	}
	return kept
}

type RedisRateLimiter struct {
	client         redis.Scripter
	minute, second int64
	now            func() time.Time
	fallback       *memoryRateLimiter
	mu             sync.Mutex
	sha            string
	unavailable    bool
	nextProbe      time.Time
}

func NewRedisRateLimiter(client redis.Scripter, minute, second int64) *RedisRateLimiter {
	return &RedisRateLimiter{client: client, minute: minute, second: second,
		now: time.Now, fallback: newMemoryRateLimiter(minute, second)}
}

func (l *RedisRateLimiter) script(ctx context.Context) (string, bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	if l.unavailable {
		if now.Before(l.nextProbe) {
			return "", false
		}
		l.nextProbe = now.Add(30 * time.Second)
	}
	if l.sha != "" {
		return l.sha, true
	}
	sha, err := l.client.ScriptLoad(ctx, rateLimitScript).Result()
	if err != nil {
		l.unavailable, l.nextProbe = true, now.Add(30*time.Second)
		slog.Warn("rate limiter Redis connection failed; using memory", "error", err)
		return "", false
	}
	l.sha, l.unavailable = sha, false
	return sha, true
}

func (l *RedisRateLimiter) Allow(ctx context.Context, client string) RateLimitDecision {
	// Limit Redis work independently of the HTTP server's read timeout.
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	sha, ready := l.script(ctx)
	now := float64(l.now().UnixNano()) / 1e9
	if !ready {
		return l.fallback.allow(client, now)
	}
	keys := []string{"rate_limit:min:" + client, "rate_limit:sec:" + client}
	counts, err := l.client.EvalSha(ctx, sha, keys, strconv.FormatFloat(now, 'f', -1, 64),
		l.minute, l.second, uuid.NewString()).Int64Slice()
	if err == nil && len(counts) == 3 {
		return RateLimitDecision{Allowed: counts[2] != 0, Limit: l.minute,
			Remaining: rateRemaining(l.minute, counts[0]), Reset: int64(now) + 60}
	}
	if err == nil {
		err = fmt.Errorf("unexpected rate limit script response")
	}
	l.mu.Lock()
	l.unavailable, l.nextProbe = true, l.now().Add(30*time.Second)
	l.mu.Unlock()
	slog.Warn("rate limiter Redis check failed; using memory", "error", err)
	return l.fallback.allow(client, float64(l.now().UnixNano())/1e9)
}

func rateLimitClient(r *http.Request) string {
	if forwarded := r.Header.Get("X-Forwarded-For"); forwarded != "" {
		first, _, _ := strings.Cut(forwarded, ",")
		return strings.TrimSpace(first)
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	if r.RemoteAddr != "" {
		return r.RemoteAddr
	}
	return "unknown"
}

func rateLimitMiddleware(limiter RateLimiter, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/", "/api/health", "/api/health/ready", "/api/health/detailed", "/metrics":
			next.ServeHTTP(w, r)
			return
		}
		result := limiter.Allow(r.Context(), rateLimitClient(r))
		w.Header().Set("X-RateLimit-Limit", strconv.FormatInt(result.Limit, 10))
		w.Header().Set("X-RateLimit-Remaining", strconv.FormatInt(result.Remaining, 10))
		w.Header().Set("X-RateLimit-Reset", strconv.FormatInt(result.Reset, 10))
		if !result.Allowed {
			w.Header().Set("Retry-After", "60")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"detail": "Rate limit exceeded. Please slow down."}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}
