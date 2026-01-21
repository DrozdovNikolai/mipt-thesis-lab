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
