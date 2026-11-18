package platform

import (
	"net/http"
	"strings"
)

// Router preserves FastAPI's method handling and 307 trailing-slash redirects.
// ServeMux still owns path parameter extraction and specificity.
type Router struct {
	mux            *http.ServeMux
	methods        []string
	operations     []string
	serviceMethods map[string]string
	operationMuxes map[string]*http.ServeMux
	metricRoutes   []metricRoute
}

func NewRouter() *Router {
	return &Router{mux: http.NewServeMux(), serviceMethods: map[string]string{}, operationMuxes: map[string]*http.ServeMux{}}
}
func (r *Router) HandleFunc(pattern string, handler http.HandlerFunc) {
	r.HandleOperationFunc(pattern, pattern, handler)
}

// HandleOperationFunc binds a transport pattern to the documented operation.
// Usually they are identical; the PDF route needs a final transport wildcard.
func (r *Router) HandleOperationFunc(pattern, operation string, handler http.HandlerFunc) {
	r.mux.HandleFunc(pattern, handler)
	method, _, _ := strings.Cut(pattern, " ")
	r.methods = append(r.methods, method)
	r.operations = append(r.operations, strings.TrimSuffix(operation, "{$}"))
	_, metricPath, _ := strings.Cut(operation, " ")
	if strings.Contains(metricPath, "{") && !strings.HasSuffix(metricPath, "{$}") {
		r.metricRoutes = append(r.metricRoutes, compileMetricRoute(metricPath))
	}
	if pattern != operation {
		canonical := http.NewServeMux()
		canonical.HandleFunc(operation, handler)
		r.operationMuxes[pattern] = canonical
	}
}

func (r *Router) handleDocumentation(path string, handler http.HandlerFunc) {
	for _, method := range []string{"GET", "HEAD"} {
		pattern := method + " " + path
		r.mux.HandleFunc(pattern, handler)
		r.methods = append(r.methods, method)
		r.serviceMethods[pattern] = "GET, HEAD"
	}
}
func (r *Router) match(req *http.Request) bool {
	_, pattern := r.mux.Handler(req)
	if pattern == "" || !strings.HasPrefix(pattern, req.Method+" ") {
		return false
	}
	if canonical := r.operationMuxes[pattern]; canonical != nil {
		_, operation := canonical.Handler(req)
		return operation != "" && strings.HasPrefix(operation, req.Method+" ")
	}
	return true
}
func (r *Router) allowed(req *http.Request) string {
	for _, method := range r.methods {
		probe := req.Clone(req.Context())
		probe.Method = method
		if r.match(probe) {
			_, pattern := r.mux.Handler(probe)
			if allow, ok := r.serviceMethods[pattern]; ok {
				return allow
			}
			return method
		}
	}
	return ""
}
func (r *Router) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	// ASGI routes match the decoded path: an encoded slash is a separator,
	// including inside a string parameter. ServeMux otherwise unescapes each
	// segment separately and would accept that slash as part of the parameter.
	if strings.Contains(strings.ToLower(req.URL.RawPath), "%2f") {
		req = req.Clone(req.Context())
		req.URL.RawPath = ""
	}
	if r.match(req) {
		r.mux.ServeHTTP(w, req)
		return
	}
	if allow := r.allowed(req); allow != "" {
		w.Header().Set("Allow", allow)
		WriteJSON(w, 405, map[string]string{"detail": "Method Not Allowed"})
		return
	}
	if req.URL.Path != "/" {
		probe := req.Clone(req.Context())
		if strings.HasSuffix(req.URL.Path, "/") {
			probe.URL.Path = strings.TrimRight(req.URL.Path, "/")
		} else {
			probe.URL.Path = req.URL.Path + "/"
		}
		if r.allowed(probe) != "" {
			scheme := "http"
			if req.TLS != nil {
				scheme = "https"
			}
			destination := scheme + "://" + req.Host + probe.URL.RequestURI()
			w.Header().Set("Location", destination)
			w.WriteHeader(307)
			return
		}
	}
	WriteJSON(w, 404, map[string]string{"detail": "Not Found"})
}
