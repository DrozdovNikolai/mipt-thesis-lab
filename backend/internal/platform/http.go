package platform

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"north55/backend/internal/telemetry"
)

type APIError struct {
	Status             int
	Code, Message      string
	Extra              map[string]any
	Headers            http.Header
	SupportCorrelation bool
}

func (e *APIError) Error() string { return e.Message }
func Error(status int, message string) *APIError {
	return &APIError{Status: status, Code: fmt.Sprintf("HTTP_%d", status), Message: message}
}
func WriteJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if status != 204 {
		_ = json.NewEncoder(w).Encode(value)
	}
}
func WriteError(w http.ResponseWriter, err error) {
	var e *APIError
	if !errors.As(err, &e) {
		if reporter, ok := w.(interface{ requestFailure(error) }); ok {
			reporter.requestFailure(err)
		} else {
			LogModule("app.core.middleware").Error("Request failed", "exception", err)
		}
		// Starlette's outer ServerErrorMiddleware emits this response outside the
		// application's JSON and security middleware for an unhandled exception.
		for key := range w.Header() {
			w.Header().Del(key)
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(500)
		_, _ = w.Write([]byte("Internal Server Error"))
		return
	}
	if reporter, ok := w.(interface{ domainError(*APIError) }); ok {
		reporter.domainError(e)
	}
	for k, values := range e.Headers {
		for _, v := range values {
			w.Header().Add(k, v)
		}
	}
	body := map[string]any{"status": e.Status, "code": e.Code, "message": e.Message}
	for k, v := range e.Extra {
		body[k] = v
	}
	if e.SupportCorrelation {
		if _, ok := body["retryable"]; !ok {
			body["retryable"] = false
		}
		body["supportCorrelationId"] = w.Header().Get("X-Request-ID")
	}
	WriteJSON(w, e.Status, map[string]any{"error": errorWire(body)})
}

var errorCamelKey = regexp.MustCompile(`_([a-zA-Z0-9])`)

// The error response also transforms keys inside validation input/ctx.
// String values (including loc components) are kept verbatim.
func errorWire(value any) any {
	switch v := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(v))
		for key, item := range v {
			key = errorCamelKey.ReplaceAllStringFunc(key, func(s string) string { return strings.ToUpper(s[1:]) })
			out[key] = errorWire(item)
		}
		return out
	case []any:
		out := make([]any, len(v))
		for i, item := range v {
			out[i] = errorWire(item)
		}
		return out
	}
	return value
}

type Handler func(http.ResponseWriter, *http.Request) error

func Wrap(h Handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := h(w, r); err != nil {
			WriteError(w, err)
		}
	}
}

func Middleware(cfg Config, next http.Handler, limiters ...RateLimiter) http.Handler {
	original := next
	next = requestMiddleware(next, cfg.Metrics)
	if cfg.EnableRateLimit {
		var limiter RateLimiter = newMemoryRateLimiter(cfg.RateLimitPerMinute, cfg.RateLimitPerSecond)
		if len(limiters) > 0 && limiters[0] != nil {
			limiter = limiters[0]
		}
		next = rateLimitMiddleware(limiter, next)
	}
	next = corsMiddleware(cfg, next)
	if cfg.EnableMetrics {
		if router, ok := original.(*Router); ok {
			next = metricsMiddleware(cfg.Metrics, router, next)
		}
	}
	if router, ok := original.(*Router); ok {
		next = cfg.ErrorTracker.Middleware(router, next)
	}
	return next
}

func requestMiddleware(next http.Handler, metrics ...*telemetry.Metrics) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		state := &requestLogState{path: r.URL.Path, tracking: traceState(r.Context())}
		if len(metrics) > 0 {
			state.metrics = metrics[0]
		}
		r = requestLogContext(r, state)
		writer := &requestLogWriter{ResponseWriter: w, state: state}
		requestID := r.Header.Get("X-Request-ID")
		if requestID == "" {
			requestID = uuid.NewString()
		}
		w.Header().Set("X-Request-ID", requestID)
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-XSS-Protection", "1; mode=block")
		w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
		w.Header().Set("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
		defer func() {
			if recoverValue := recover(); recoverValue != nil {
				WriteError(writer, fmt.Errorf("request panic: %v", recoverValue))
			}
			recordRequestCompletion(r, writer, requestID, started)
		}()
		next.ServeHTTP(writer, r)
	})
}

func corsMiddleware(cfg Config, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		hasOrigin := len(r.Header.Values("Origin")) > 0
		allowed := false
		wildcard := false
		if cfg.EnableCORS && hasOrigin {
			w.Header().Set("Access-Control-Allow-Credentials", "true")
			for _, v := range cfg.AllowedOrigins {
				v = strings.TrimSpace(v)
				if v == "*" {
					wildcard = true
					allowed = true
				}
				if v == origin {
					allowed = true
				}
			}
			if allowed {
				if wildcard && len(r.Header.Values("Cookie")) == 0 {
					w.Header().Set("Access-Control-Allow-Origin", "*")
				} else {
					w.Header().Set("Access-Control-Allow-Origin", origin)
					w.Header().Add("Vary", "Origin")
				}
			}
		}
		if cfg.EnableCORS && r.Method == http.MethodOptions && len(r.Header.Values("Access-Control-Request-Method")) > 0 && hasOrigin {
			w.Header().Del("Access-Control-Allow-Origin")
			if allowed {
				w.Header().Set("Access-Control-Allow-Origin", origin)
			}
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT")
			if len(r.Header.Values("Access-Control-Request-Headers")) > 0 {
				w.Header().Set("Access-Control-Allow-Headers", r.Header.Get("Access-Control-Request-Headers"))
			}
			w.Header().Set("Access-Control-Max-Age", "600")
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			failures := []string{}
			if !allowed {
				failures = append(failures, "origin")
			}
			switch r.Header.Get("Access-Control-Request-Method") {
			case "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT":
			default:
				failures = append(failures, "method")
			}
			if len(failures) > 0 {
				w.WriteHeader(400)
				_, _ = w.Write([]byte("Disallowed CORS " + strings.Join(failures, ", ")))
				return
			}
			_, _ = w.Write([]byte("OK"))
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Object retains presence and null independently for partial update semantics.
type Object map[string]any
type Field struct {
	Name, Alias, Kind, Pattern string
	Required, Nullable         bool
	Min, Max                   int
	Default                    any
	NonNegative                bool
	GreaterThanZero            bool
	AllowBigInteger            bool
	Decimal                    *DecimalConstraints
	Choices                    []string
	Schema                     *Schema
	Item                       *Field
	Before                     func(any, []any) (any, []any)
	Check                      func(any) string
}

type Schema struct {
	Fields      []Field
	Check       func(Object) string
	ForbidExtra bool
}

func (o Object) Has(name string) bool      { _, ok := o[name]; return ok }
func (o Object) String(name string) string { v, _ := o[name].(string); return v }
func (o Object) StringPtr(name string) *string {
	v, ok := o[name].(string)
	if !ok {
		return nil
	}
	return &v
}
func (o Object) Int(name string) int64 { v, _ := o[name].(int64); return v }

// CompareInteger compares an unbounded client watermark without narrowing it.
func (o Object) CompareInteger(name string, other int64) int {
	if value, ok := o[name].(*big.Int); ok {
		return value.Cmp(big.NewInt(other))
	}
	value := o.Int(name)
	if value < other {
		return -1
	}
	if value > other {
		return 1
	}
	return 0
}
func (o Object) Bool(name string) bool { v, _ := o[name].(bool); return v }

func validationError(details []any) *APIError {
	return &APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": details}}
}
func Detail(kind, message string, loc []any, input any, ctx map[string]any) map[string]any {
	d := map[string]any{"type": kind, "loc": loc, "msg": message, "input": input, "url": "https://errors.pydantic.dev/2.6/v/" + kind}
	if ctx != nil {
		d["ctx"] = ctx
	}
	return d
}
