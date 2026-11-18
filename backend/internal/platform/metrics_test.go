package platform

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"north55/backend/internal/telemetry"
)

func TestHTTPMetricsRoutingAndMiddleware(t *testing.T) {
	cfg := Config{EnableMetrics: true, Metrics: telemetry.New(true), EnableCORS: true, AllowedOrigins: []string{"https://example.test"}}
	router := NewRouter()
	router.HandleFunc("POST /api/items/{id}", func(w http.ResponseWriter, r *http.Request) { WriteJSON(w, 200, map[string]string{"result": "ok"}) })
	router.HandleFunc("GET /api/chunked", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("stream"))
		_ = http.NewResponseController(w).Flush()
	})
	router.HandleFunc("GET /api/domain", Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return &APIError{Status: 409, Code: "DRAFT_WRITER_CONFLICT", Message: "conflict"}
	}))
	RegisterMetrics(router, cfg)
	server := httptest.NewServer(Middleware(cfg, router))
	defer server.Close()
	client := server.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	for _, tc := range []struct {
		method, path, body, origin string
		status                     int
	}{
		{"POST", "/api/items/7", "{}", "", 200},
		{"GET", "/api/items/7", "", "", 405},
		{"POST", "/api/items/7/", "{}", "", 307},
		{"GET", "/unknown", "", "", 404},
		{"GET", "/api/chunked", "", "", 200},
		{"OPTIONS", "/api/items/7", "", "https://example.test", 200},
		{"GET", "/api/domain", "", "", 409},
		{"HEAD", "/metrics", "", "", 405},
		{"GET", "/not/metrics/path", "", "", 404},
	} {
		req, _ := http.NewRequest(tc.method, server.URL+tc.path, strings.NewReader(tc.body))
		if tc.origin != "" {
			req.Header.Set("Origin", tc.origin)
			req.Header.Set("Access-Control-Request-Method", "POST")
		}
		res, err := client.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		io.Copy(io.Discard, res.Body)
		res.Body.Close()
		if res.StatusCode != tc.status {
			t.Fatalf("%s %s: %d", tc.method, tc.path, res.StatusCode)
		}
	}
	response, err := client.Get(server.URL + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	data, _ := io.ReadAll(response.Body)
	text := string(data)
	for _, expected := range []string{
		`http_requests_total{handler="/api/items/{id}",method="POST",status="2xx"} 1`,
		`http_requests_total{handler="/api/items/{id}",method="GET",status="4xx"} 1`,
		`http_requests_total{handler="/api/items/{id}",method="OPTIONS",status="2xx"} 1`,
		`http_requests_total{handler="none",method="POST",status="3xx"} 1`,
		`http_requests_total{handler="none",method="GET",status="4xx"} 1`,
		`http_request_size_bytes_sum{handler="/api/items/{id}"} 2`,
		`http_response_size_bytes_sum{handler="/api/chunked"} 0`,
		`training_draft_revision_conflicts_total{reason="DRAFT_WRITER_CONFLICT"} 1`,
	} {
		if !strings.Contains(text, expected) {
			t.Fatal("missing metric:", expected, text)
		}
	}
	if strings.Contains(text, `handler="/metrics"`) || strings.Contains(text, `method="HEAD"`) {
		t.Fatal("metrics endpoint counted", text)
	}
}

func TestDomainErrorMetricSourceEndpointRules(t *testing.T) {
	m := telemetry.New(false)
	for _, path := range []string{"/api/training/assessments/finalize", "/api/training/assessments/7/report-preview.pdf", "/api/training/assessments/7/report.pdf", "/api/training/trainings/7/draft", "/api/training/trainings/7/submit"} {
		recordDomainError(m, path, &APIError{Code: "UNRESOLVED_QUICK_COMMENTS"})
	}
	recorder := httptest.NewRecorder()
	m.Handler(recorder, httptest.NewRequest("GET", "/metrics", nil))
	text := recorder.Body.String()
	for _, expected := range []string{`endpoint="other"} 2`, `endpoint="pdf_preview"} 1`, `endpoint="draft"} 1`, `endpoint="submit"} 1`} {
		if !strings.Contains(text, expected) {
			t.Fatal("source endpoint rule", expected, text)
		}
	}
}

func TestHTTPMetricsIncludeRateLimitReplies(t *testing.T) {
	cfg := Config{EnableMetrics: true, Metrics: telemetry.New(true), EnableRateLimit: true, RateLimitPerMinute: 1, RateLimitPerSecond: 1}
	router := NewRouter()
	router.HandleFunc("GET /api/ping", func(w http.ResponseWriter, r *http.Request) { WriteJSON(w, 200, map[string]bool{"ok": true}) })
	handler := Middleware(cfg, router)
	for _, status := range []int{200, 429} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", "/api/ping", nil))
		if response.Code != status {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	response := httptest.NewRecorder()
	cfg.Metrics.Handler(response, httptest.NewRequest("GET", "/metrics", nil))
	for _, sample := range []string{`http_requests_total{handler="/api/ping",method="GET",status="2xx"} 1`, `http_requests_total{handler="/api/ping",method="GET",status="4xx"} 1`} {
		if !strings.Contains(response.Body.String(), sample) {
			t.Fatal("rate reply not counted", sample)
		}
	}
}

func TestHTTPMetricsCaptureHeadersBeforeUnexpectedFailure(t *testing.T) {
	cfg := Config{EnableMetrics: true, Metrics: telemetry.New(true)}
	router := NewRouter()
	router.HandleFunc("GET /before", Wrap(func(w http.ResponseWriter, r *http.Request) error { return io.ErrUnexpectedEOF }))
	router.HandleFunc("GET /after", Wrap(func(w http.ResponseWriter, r *http.Request) error {
		w.Header().Set("Content-Length", "123")
		w.WriteHeader(200)
		w.Write([]byte("partial"))
		return io.ErrUnexpectedEOF
	}))
	handler := Middleware(cfg, router)
	for _, path := range []string{"/before", "/after"} {
		handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", path, nil))
	}
	response := httptest.NewRecorder()
	cfg.Metrics.Handler(response, httptest.NewRequest("GET", "/metrics", nil))
	text := response.Body.String()
	for _, sample := range []string{`http_requests_total{handler="/before",method="GET",status="5xx"} 1`, `http_requests_total{handler="/after",method="GET",status="2xx"} 1`, `http_response_size_bytes_sum{handler="/before"} 0`, `http_response_size_bytes_sum{handler="/after"} 123`} {
		if !strings.Contains(text, sample) {
			t.Fatal("unexpected failure headers", sample)
		}
	}
}
