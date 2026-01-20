package platform

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRouterPreservesMethodsSlashesAndPathValues(t *testing.T) {
	router := NewRouter()
	router.HandleFunc("GET /api/things/{item_id}", func(w http.ResponseWriter, r *http.Request) {
		WriteJSON(w, 200, map[string]string{"id": r.PathValue("item_id")})
	})
	for _, test := range []struct {
		method, path   string
		status         int
		body, location string
	}{
		{"GET", "/api/things/123", 200, "{\"id\":\"123\"}\n", ""},
		{"POST", "/api/things/123", 405, "{\"detail\":\"Method Not Allowed\"}\n", ""},
		{"HEAD", "/api/things/123", 405, "{\"detail\":\"Method Not Allowed\"}\n", ""},
		{"GET", "/api/things/123/?a=1", 307, "", "http://example.com/api/things/123?a=1"},
		{"GET", "/api/unknown", 404, "{\"detail\":\"Not Found\"}\n", ""},
		{"GET", "/api/things/1%2F2", 404, "{\"detail\":\"Not Found\"}\n", ""},
		{"POST", "/api/things/1%2f2", 404, "{\"detail\":\"Not Found\"}\n", ""},
		{"GET", "/api%2Fthings/123", 200, "{\"id\":\"123\"}\n", ""},
		{"GET", "/api/things/%252F", 200, "{\"id\":\"%2F\"}\n", ""},
		{"GET", "/api/things/123%2f?a=1", 307, "", "http://example.com/api/things/123?a=1"},
	} {
		t.Run(test.method+test.path, func(t *testing.T) {
			request := httptest.NewRequest(test.method, "http://example.com"+test.path, nil)
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			if response.Code != test.status || response.Body.String() != test.body || response.Header().Get("Location") != test.location {
				t.Fatalf("%d %q %q", response.Code, response.Body.String(), response.Header().Get("Location"))
			}
			if response.Code == 405 && response.Header().Get("Allow") != "GET" {
				t.Fatal("missing Allow")
			}
		})
	}
}
