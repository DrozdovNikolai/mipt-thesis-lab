package platform

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/getsentry/sentry-go"
	"io"
	"log/slog"
	"strings"
	"sync"
)

type logOutput struct {
	mu      sync.Mutex
	w       io.Writer
	level   slog.Level
	local   bool
	tracker *ErrorTracker
}

type appLogHandler struct {
	output *logOutput
	attrs  []slog.Attr
	group  string
}

// NewApplicationLogger preserves the frozen logging level names and formats.
// A logger attribute chooses the module name. Extra fields use the source
// formatter's non-AI allowlist; local output includes only the message.
func NewApplicationLogger(w io.Writer, level string, local bool, trackers ...*ErrorTracker) (*slog.Logger, error) {
	thresholds := map[string]slog.Level{
		"NOTSET": -8, "DEBUG": slog.LevelDebug, "INFO": slog.LevelInfo,
		"WARN": slog.LevelWarn, "WARNING": slog.LevelWarn,
		"ERROR": slog.LevelError, "FATAL": 12, "CRITICAL": 12,
	}
	threshold, ok := thresholds[level]
	if !ok {
		return nil, fmt.Errorf("unknown LOG_LEVEL %q", level)
	}
	var tracker *ErrorTracker
	if len(trackers) > 0 {
		tracker = trackers[0]
	}
	return slog.New(&appLogHandler{output: &logOutput{w: w, level: threshold, local: local, tracker: tracker}}), nil
}

func (h *appLogHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= h.output.level
}

func (h *appLogHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := *h
	next.attrs = append([]slog.Attr(nil), h.attrs...)
	for _, attr := range attrs {
		attr.Key = h.group + attr.Key
		next.attrs = append(next.attrs, attr)
	}
	return &next
}

func (h *appLogHandler) WithGroup(name string) slog.Handler {
	next := *h
	if name != "" {
		next.group += name + "."
	}
	return &next
}

func logLevelName(level slog.Level) string {
	switch {
	case level >= 12:
		return "CRITICAL"
	case level >= slog.LevelError:
		return "ERROR"
	case level >= slog.LevelWarn:
		return "WARNING"
	case level >= slog.LevelInfo:
		return "INFO"
	default:
		return "DEBUG"
	}
}

var applicationLogFields = map[string]bool{
	"request_id": true, "user_id": true, "status": true, "method": true, "path": true,
	"status_code": true, "duration_ms": true, "action": true, "airline_id": true,
	"aircraft_id": true, "scenario_id": true, "pdf_id": true, "content_version": true,
	"target_user_id": true, "training_id": true, "assessment_id": true,
}

func (h *appLogHandler) Handle(ctx context.Context, record slog.Record) error {
	name := "app.main"
	fields := map[string]any{}
	sentryFields := map[string]any{}
	var exceptionErr error
	add := func(attr slog.Attr, group string) {
		attr.Value = attr.Value.Resolve()
		key := group + attr.Key
		if key != "logger" && key != "exception" {
			sentryFields[key] = attr.Value.Any()
		}
		if key == "exception" {
			exceptionErr, _ = attr.Value.Any().(error)
		}
		if key == "logger" {
			name = attr.Value.String()
		} else if key == "exception" {
			fields[key] = fmt.Sprint(attr.Value.Any())
		} else if applicationLogFields[key] {
			fields[key] = attr.Value.Any()
		}
	}
	for _, attr := range h.attrs {
		add(attr, "")
	}
	record.Attrs(func(attr slog.Attr) bool { add(attr, h.group); return true })
	if h.output.tracker != nil {
		if state := traceState(ctx); state != nil {
			state.mu.Lock()
			if state.failure != nil {
				exceptionErr = state.failure
			}
			state.mu.Unlock()
		}
		level := sentry.Level(strings.ToLower(logLevelName(record.Level)))
		if level == "critical" {
			level = sentry.LevelFatal
		}
		h.output.tracker.CaptureLog(ctx, name, level, record.Message, sentryFields, exceptionErr)
	}
	h.output.mu.Lock()
	defer h.output.mu.Unlock()
	if h.output.local {
		line := fmt.Sprintf("%s %s [%s] %s\n", record.Time.Local().Format("2006-01-02T15:04:05Z"), logLevelName(record.Level), name, record.Message)
		if exception, ok := fields["exception"]; ok {
			line += fmt.Sprint(exception) + "\n"
		}
		_, err := io.WriteString(h.output.w, line)
		return err
	}
	fields["timestamp"] = record.Time.UTC().Format("2006-01-02T15:04:05.000000+00:00")
	fields["level"] = logLevelName(record.Level)
	fields["logger"] = name
	fields["message"] = record.Message
	encoder := json.NewEncoder(h.output.w)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(fields)
}

// LogModule returns a logger with a stable module name for an audit action.
func LogModule(name string, contexts ...context.Context) *slog.Logger {
	logger := slog.Default().With("logger", strings.TrimSpace(name))
	if len(contexts) > 0 {
		return slog.New(&boundLogHandler{handler: logger.Handler(), ctx: contexts[0]})
	}
	return logger
}

type boundLogHandler struct {
	handler slog.Handler
	ctx     context.Context
}

func (h *boundLogHandler) Enabled(_ context.Context, level slog.Level) bool {
	return h.handler.Enabled(h.ctx, level)
}
func (h *boundLogHandler) Handle(_ context.Context, record slog.Record) error {
	return h.handler.Handle(h.ctx, record)
}
func (h *boundLogHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &boundLogHandler{handler: h.handler.WithAttrs(attrs), ctx: h.ctx}
}
func (h *boundLogHandler) WithGroup(group string) slog.Handler {
	return &boundLogHandler{handler: h.handler.WithGroup(group), ctx: h.ctx}
}
