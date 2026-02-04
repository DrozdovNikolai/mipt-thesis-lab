package platform

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"north55/backend/internal/telemetry"
	"runtime/debug"
	"sync"
	"time"
)

type requestLogKey struct{}

type requestLogState struct {
	metrics   *telemetry.Metrics
	tracking  *trackingState
	path      string
	mu        sync.Mutex
	user      any
	failure   error
	exception string
}

// SetRequestUser records the authenticated public user ID, before checks that
// may subsequently reject an inactive user or a missing privilege.
func SetRequestUser(r *http.Request, userID string) {
	if state, ok := r.Context().Value(requestLogKey{}).(*requestLogState); ok {
		state.mu.Lock()
		state.user = userID
		state.mu.Unlock()
	}
}

type requestLogWriter struct {
	http.ResponseWriter
	state  *requestLogState
	status int
}

func (w *requestLogWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (w *requestLogWriter) WriteHeader(status int) {
	if status >= 200 && w.status == 0 {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *requestLogWriter) Write(body []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(body)
}

func (w *requestLogWriter) requestFailure(err error) {
	if w.state.tracking != nil {
		w.state.tracking.mu.Lock()
		w.state.tracking.failure = err
		w.state.tracking.mu.Unlock()
	}
	if metrics, ok := w.ResponseWriter.(interface{ metricFailure() }); ok {
		metrics.metricFailure()
	}
	w.state.mu.Lock()
	w.state.failure = err
	w.state.exception = fmt.Sprint(err) + "\n" + string(debug.Stack())
	w.state.mu.Unlock()
}

func recordRequestCompletion(r *http.Request, writer *requestLogWriter, requestID string, started time.Time) {
	writer.state.mu.Lock()
	user, failure, exception := writer.state.user, writer.state.failure, writer.state.exception
	writer.state.mu.Unlock()
	switch r.URL.Path {
	case "/api/health", "/api/health/ready", "/api/health/detailed", "/metrics":
		if failure != nil {
			LogModule("app.main", r.Context()).Error("Request failed", "exception", exception)
		}
		return
	}
	attrs := []slog.Attr{
		slog.String("request_id", requestID), slog.Any("user_id", user),
		slog.String("method", r.Method), slog.String("path", r.URL.Path),
		slog.Float64("duration_ms", math.RoundToEven(float64(time.Since(started))/float64(time.Millisecond)*100)/100),
	}
	logger := LogModule("app.core.middleware")
	if failure != nil {
		attrs = append(attrs, slog.String("exception", exception))
		logger.LogAttrs(r.Context(), slog.LevelError, "Request failed", attrs...)
		return
	}
	status := writer.status
	if status == 0 {
		status = http.StatusOK
	}
	attrs = append(attrs, slog.Int("status_code", status))
	logger.LogAttrs(r.Context(), slog.LevelInfo, "Request completed", attrs...)
}

func requestLogContext(r *http.Request, state *requestLogState) *http.Request {
	return r.WithContext(context.WithValue(r.Context(), requestLogKey{}, state))
}

func (w *requestLogWriter) domainError(e *APIError) {
	recordDomainError(w.state.metrics, w.state.path, e)
}
