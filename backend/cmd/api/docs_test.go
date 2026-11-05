package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/support"
	"north55/backend/internal/telemetry"
	"north55/backend/internal/training"
)

func TestDocumentationMatchesRegisteredAPI(t *testing.T) {
	for _, prefix := range []string{"/api", "/v2", "", "/север-v2"} {
		for _, environment := range []string{"local", "test", "prod"} {
			for _, metrics := range []bool{false, true} {
				t.Run(fmt.Sprint(environment, prefix, metrics), func(t *testing.T) {
					cfg := platform.Config{APIPrefix: prefix, Environment: environment, AppName: "55north docs", EnableMetrics: metrics, Metrics: telemetry.New(metrics)}
					svc := &auth.Service{Config: cfg}
					router := platform.NewRouter()
					(&platform.Health{Config: cfg}).Register(router)
					svc.Register(router)
					(&training.Service{Auth: svc}).Register(router)
					(&support.Service{Auth: svc}).Register(router)
					platform.RegisterMetrics(router, cfg)
					if err := platform.RegisterAPIDocumentation(router, cfg); err != nil {
						t.Fatal(err)
					}
					request := httptest.NewRequest("GET", "/openapi.json", nil)
					response := httptest.NewRecorder()
					router.ServeHTTP(response, request)
					if response.Code != 200 {
						t.Fatal(response.Code, response.Body.String())
					}
					var doc struct {
						OpenAPI string
						Info    struct{ Title string }
						Paths   map[string]map[string]json.RawMessage
					}
					if err := json.Unmarshal(response.Body.Bytes(), &doc); err != nil {
						t.Fatal(err)
					}
					count := 0
					for _, item := range doc.Paths {
						count += len(item)
					}
					expectedCount := 217
					if metrics {
						expectedCount++
					}
					if (doc.Paths["/metrics"]["get"] != nil) != metrics {
						t.Fatal("conditional metrics contract")
					}
					if count != expectedCount || doc.OpenAPI != "3.1.0" || doc.Info.Title != cfg.AppName || doc.Paths[prefix+"/auth/login"]["post"] == nil {
						t.Fatal("invalid runtime contract", count, doc.Info, doc.OpenAPI)
					}
					for _, path := range []string{"/docs", "/redoc", "/docs/oauth2-redirect"} {
						for _, method := range []string{"GET", "HEAD"} {
							response := httptest.NewRecorder()
							router.ServeHTTP(response, httptest.NewRequest(method, path, nil))
							want := 404
							if environment == "local" {
								want = 200
								if method == "HEAD" && response.Body.Len() != 0 {
									t.Fatal("HEAD includes body")
								}
							}
							if response.Code != want {
								t.Fatalf("%s %s got %d want %d", method, path, response.Code, want)
							}
						}
					}
				})
			}
		}
	}
}

func TestDocumentationRejectsIncompleteRegistration(t *testing.T) {
	router := platform.NewRouter()
	router.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {})
	if err := platform.RegisterAPIDocumentation(router, platform.Config{APIPrefix: "/api"}); err == nil {
		t.Fatal("incomplete API registration accepted")
	}
}

func TestStoredReportAndSignatureRouting(t *testing.T) {
	svc := &auth.Service{Config: platform.Config{APIPrefix: "/api"}}
	router := platform.NewRouter()
	(&training.Service{Auth: svc}).Register(router)
	for _, tc := range []struct {
		method, path string
		status       int
		allow        string
	}{
		{"GET", "/api/training/assessments/50/report.pdf", 401, ""},
		{"POST", "/api/training/assessments/50/report.pdf", 405, "GET"},
		{"HEAD", "/api/training/assessments/50/report.pdf", 405, "GET"},
		{"GET", "/api/training/assessments/50/unknown.pdf", 404, ""},
		{"POST", "/api/training/assessments/50/unknown.pdf", 404, ""},
		{"HEAD", "/api/training/assessments/50/unknown.pdf", 404, ""},
		{"POST", "/api/training/assessments/50/unknown.pdf/", 404, ""},
		{"GET", "/api/training/assessments/50/report%2Epdf", 401, ""},
		{"GET", "/api/training/assessments/50/report.pdf/", 307, ""},
		{"GET", "/api/training/assessments/50%2Fother/report.pdf", 404, ""},
		{"GET", "/api/training/assessments/signatures/50", 401, ""},
		{"POST", "/api/training/assessments/signatures/50", 405, "GET"},
	} {
		t.Run(tc.method+tc.path, func(t *testing.T) {
			response := httptest.NewRecorder()
			router.ServeHTTP(response, httptest.NewRequest(tc.method, tc.path, nil))
			if response.Code != tc.status || response.Header().Get("Allow") != tc.allow {
				t.Fatalf("got %d Allow=%q body=%s, want %d Allow=%q", response.Code, response.Header().Get("Allow"), response.Body.String(), tc.status, tc.allow)
			}
		})
	}
}
