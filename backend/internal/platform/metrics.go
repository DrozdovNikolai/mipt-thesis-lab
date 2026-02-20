package platform

import (
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"north55/backend/internal/telemetry"
)

var metricParameter = regexp.MustCompile(`\\\{[^{}]+\\\}`)

type metricRoute struct {
	path    string
	matcher *regexp.Regexp
}

func compileMetricRoute(path string) metricRoute {
	pattern := metricParameter.ReplaceAllString(regexp.QuoteMeta(path), `[^/]+`)
	return metricRoute{path: path, matcher: regexp.MustCompile("^" + pattern + "$")}
}

// Instrumentator resolves the route template before the handler, including
// method-mismatch requests; unmatched paths and slash redirects use "none".
func (r *Router) metricHandler(path string) string {
	for pattern := range r.serviceMethods {
		_, p, _ := strings.Cut(pattern, " ")
		if p == path {
			return p
		}
	}
	for _, operation := range r.operations {
		_, p, _ := strings.Cut(operation, " ")
		if !strings.Contains(p, "{") && p == path {
			return p
		}
	}
	for _, route := range r.metricRoutes {
		if route.matcher.MatchString(path) {
			return route.path
		}
	}
	return "none"
}

func RegisterMetrics(router *Router, cfg Config) {
	if cfg.EnableMetrics {
		router.HandleFunc("GET /metrics", cfg.Metrics.Handler)
	}
}

type metricResponseWriter struct {
	http.ResponseWriter
	status      int
	size        int64
	flushed     bool
	failed      bool
	failureSize int64
}

func (w *metricResponseWriter) metricFailure() {
	w.failed = true
	if w.status != 0 {
		w.failureSize, _ = strconv.ParseInt(w.Header().Get("Content-Length"), 10, 64)
	}
}

func (w *metricResponseWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *metricResponseWriter) WriteHeader(status int) {
	if status >= 200 && w.status == 0 {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}
func (w *metricResponseWriter) Write(body []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(200)
	}
	n, err := w.ResponseWriter.Write(body)
	w.size += int64(n)
	return n, err
}
func (w *metricResponseWriter) Flush() {
	w.flushed = true
	if w.status == 0 {
		w.WriteHeader(200)
	}
	_ = http.NewResponseController(w.ResponseWriter).Flush()
}
func metricsMiddleware(metrics *telemetry.Metrics, router *Router, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handler := router.metricHandler(r.URL.Path)
		excluded := strings.Contains(handler, "/metrics") || handler == "none" && strings.Contains(r.URL.Path, "/metrics")
		if excluded {
			next.ServeHTTP(w, r)
			return
		}
		started := time.Now()
		writer := &metricResponseWriter{ResponseWriter: w}
		defer func() {
			status := writer.status
			if status == 0 {
				status = 200
			}
			requestSize, _ := strconv.ParseInt(r.Header.Get("Content-Length"), 10, 64)
			responseSize, _ := strconv.ParseInt(w.Header().Get("Content-Length"), 10, 64)
			if w.Header().Get("Content-Length") == "" && !writer.flushed && writer.size < 2048 && status != 204 && status != 304 {
				// net/http adds this implicit length when finishing a small response.
				responseSize = writer.size
			}
			if writer.failed {
				// Keep headers already emitted by a streaming response. Before its
				// start, the source captures no headers for ServerErrorMiddleware.
				responseSize = writer.failureSize
			}
			metrics.HTTP(r.Method, handler, status, requestSize, responseSize, time.Since(started).Seconds())
		}()
		next.ServeHTTP(writer, r)
	})
}

func recordDomainError(metrics *telemetry.Metrics, path string, e *APIError) {
	endpoint := "other"
	p := strings.ToLower(path)
	switch {
	case strings.HasSuffix(p, "/submit"):
		endpoint = "submit"
	case strings.Contains(p, "/assessment/finalize"):
		endpoint = "finalize"
	case strings.Contains(p, "/report.pdf"):
		endpoint = "pdf_preview"
	case strings.Contains(p, "/draft"):
		endpoint = "draft"
	}
	switch e.Code {
	case "UNRESOLVED_QUICK_COMMENTS":
		metrics.Inc("training_unresolved_quick_rejections_total", endpoint)
	case "COMMENT_OB_REQUIRED":
		metrics.Inc("training_comment_ob_required_rejections_total", endpoint)
	case "COMMENT_CONTRACT_VERSION_REQUIRED", "QUICK_COMMENT_CAPABILITY_NOT_GRANTED", "QUICK_COMMENT_CONTRACT_INCOMPLETE":
		metrics.Inc("training_comment_contract_mismatch_total", endpoint)
	case "STALE_DRAFT_REVISION", "DRAFT_REVISION_HASH_CONFLICT", "DRAFT_WRITER_CONFLICT":
		metrics.Inc("training_draft_revision_conflicts_total", e.Code)
	}
}
