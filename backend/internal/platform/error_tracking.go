package platform

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/getsentry/sentry-go"
)

// ErrorTracker uses an isolated hub per HTTP request. No client or transport is
// created for an empty DSN; the environment cannot enable a disabled instance.
type ErrorTracker struct {
	client *sentry.Client
	base   *sentry.Hub
}
type trackingKey struct{}
type trackingState struct {
	hub     *sentry.Hub
	mu      sync.Mutex
	failure error
}

func NewErrorTracker(dsn, environment string) (*ErrorTracker, error) {
	return newErrorTracker(dsn, environment, nil, .2)
}
func newErrorTracker(dsn, environment string, transport sentry.Transport, traceRate float64) (*ErrorTracker, error) {
	if dsn == "" {
		return nil, nil
	}
	// The SDK 0.49 telemetry scheduler can drain into a concurrent sender after
	// FlushWithContext has observed an empty transport. Its established async
	// transport preserves bounded shutdown flush for these error/trace events.
	client, err := sentry.NewClient(sentry.ClientOptions{Dsn: dsn, Environment: environment, EnableTracing: true, TracesSampleRate: traceRate, Transport: transport, DisableTelemetryBuffer: true})
	if err != nil {
		return nil, err
	}
	return &ErrorTracker{client: client, base: sentry.NewHub(client, sentry.NewScope())}, nil
}
func (t *ErrorTracker) Flush(ctx context.Context) bool {
	if t == nil {
		return true
	}
	return t.client.FlushWithContext(ctx)
}
func (t *ErrorTracker) Close() {
	if t != nil {
		t.client.Close()
	}
}

func traceState(ctx context.Context) *trackingState {
	state, _ := ctx.Value(trackingKey{}).(*trackingState)
	return state
}
func reportTrackedFailure(ctx context.Context, err error) {
	if state := traceState(ctx); state != nil {
		state.mu.Lock()
		state.failure = err
		state.mu.Unlock()
	}
}
func (t *ErrorTracker) hub(ctx context.Context) *sentry.Hub {
	if state := traceState(ctx); state != nil {
		return state.hub
	}
	return t.base
}
func (t *ErrorTracker) captureException(hub *sentry.Hub, ctx context.Context, err error, mechanism string, handled bool) {
	event := t.client.EventFromException(err, sentry.LevelError)
	if span := sentry.SpanFromContext(ctx); span != nil {
		event.Transaction = span.Name
	}
	for i := range event.Exception {
		event.Exception[i].Mechanism = &sentry.Mechanism{Type: mechanism, Handled: &handled}
	}
	hub.CaptureEventWithHint(event, &sentry.EventHint{Context: ctx, OriginalException: err})
}

// CaptureLog preserves source LoggingIntegration ordering: the error event
// precedes its breadcrumb. SDK 0.49 represents application data in contexts.
func (t *ErrorTracker) CaptureLog(ctx context.Context, logger string, level sentry.Level, message string, fields map[string]any, err error) {
	if t == nil {
		return
	}
	hub := t.hub(ctx)
	if level == sentry.LevelError || level == sentry.LevelFatal {
		event := sentry.NewEvent()
		if err != nil {
			event = t.client.EventFromException(err, level)
			for i := range event.Exception {
				handled := true
				event.Exception[i].Mechanism = &sentry.Mechanism{Type: "logging", Handled: &handled}
			}
		}
		if span := sentry.SpanFromContext(ctx); span != nil {
			event.Transaction = span.Name
		}
		event.Logger = logger
		event.Level = level
		event.Message = message
		event.Contexts["log"] = sentry.Context(fields)
		hub.CaptureEventWithHint(event, &sentry.EventHint{Context: ctx, OriginalException: err})
	}
	if level != sentry.LevelDebug {
		hub.AddBreadcrumb(&sentry.Breadcrumb{Timestamp: time.Now(), Type: "log", Category: logger, Level: level, Message: message, Data: fields}, nil)
	}
}

type trackedResponse struct {
	http.ResponseWriter
	status int
}

func (w *trackedResponse) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *trackedResponse) WriteHeader(status int) {
	if w.status == 0 && status >= 200 {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}
func (w *trackedResponse) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(200)
	}
	return w.ResponseWriter.Write(b)
}

func (t *ErrorTracker) Middleware(router *Router, next http.Handler) http.Handler {
	if t == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hub := t.base.Clone()
		state := &trackingState{hub: hub}
		ctx := sentry.SetHubOnContext(context.WithValue(r.Context(), trackingKey{}, state), hub)
		name := router.metricHandler(r.URL.Path)
		if name == "none" {
			name = "generic ASGI request"
		}
		span := sentry.StartTransaction(ctx, name, sentry.ContinueTrace(hub, r.Header.Get(sentry.SentryTraceHeader), r.Header.Get(sentry.SentryBaggageHeader)), sentry.WithOpName("http.server"), sentry.WithTransactionSource(sentry.SourceRoute))
		r = r.WithContext(span.Context())
		hub.Scope().SetRequest(r)
		span.SetData("http.request.method", r.Method)
		writer := &trackedResponse{ResponseWriter: w}
		defer func() {
			state.mu.Lock()
			failure := state.failure
			state.mu.Unlock()
			if failure != nil {
				t.captureException(hub, r.Context(), failure, "go.http", false)
			}
			status := writer.status
			if status == 0 {
				status = 200
			}
			span.Status = sentry.HTTPtoSpanStatus(status)
			span.SetData("http.response.status_code", status)
			span.Finish()
		}()
		next.ServeHTTP(writer, r)
	})
}
