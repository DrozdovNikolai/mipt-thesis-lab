package platform

import (
	"embed"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
)

// The embedded API documentation is checked against registered routes.
//
//go:embed assets/openapi.json assets/docs-unicode.json assets/*.html
var apiDocumentation embed.FS

var docsUnicode = func() struct {
	Word, Cased, Ignorable [][2]rune
	Lower, Title           map[rune]string
} {
	var value struct {
		Word, Cased, Ignorable [][2]rune
		Lower, Title           map[rune]string
	}
	raw, _ := apiDocumentation.ReadFile("assets/docs-unicode.json")
	if err := json.Unmarshal(raw, &value); err != nil {
		panic(err)
	}
	return value
}()

func docsInRanges(r rune, intervals [][2]rune) bool {
	i := sort.Search(len(intervals), func(i int) bool { return intervals[i][1] > r })
	return i < len(intervals) && intervals[i][0] <= r
}

func openAPISanitize(value string) string {
	return strings.Map(func(r rune) rune {
		if docsInRanges(r, docsUnicode.Word) || r == '_' {
			return r
		}
		return '_'
	}, value)
}

// Pydantic's definition keys use ASCII names, unlike FastAPI operation IDs.
func openAPIDefinitionName(value string) string {
	return strings.ReplaceAll(strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '-' || r == '_' {
			return r
		}
		return '_'
	}, value), ".", "__")
}

func openAPIResponseTitle(id string) string {
	value := "Response " + strings.ReplaceAll(id, "_", " ")
	cased := false
	runes := []rune(value)
	var result strings.Builder
	for i, r := range runes {
		previous := cased
		cased = docsInRanges(r, docsUnicode.Cased)
		mapping := docsUnicode.Title
		if previous {
			mapping = docsUnicode.Lower
		}
		if previous && r == 'Σ' {
			final := false
			for j := i - 1; j >= 0; j-- {
				if docsInRanges(runes[j], docsUnicode.Ignorable) {
					continue
				}
				final = docsInRanges(runes[j], docsUnicode.Cased)
				break
			}
			for _, next := range runes[i+1:] {
				if docsInRanges(next, docsUnicode.Ignorable) {
					continue
				}
				final = final && !docsInRanges(next, docsUnicode.Cased)
				break
			}
			if final {
				result.WriteRune('ς')
				continue
			}
		}
		if changed, ok := mapping[r]; ok {
			result.WriteString(changed)
		} else {
			result.WriteRune(r)
		}
	}
	return result.String()
}

func rewriteOpenAPIValues(value any, replacements map[string]string) {
	switch value := value.(type) {
	case map[string]any:
		for key, item := range value {
			if raw, ok := item.(string); ok {
				if replacement, exists := replacements[raw]; exists {
					value[key] = replacement
				}
			} else {
				rewriteOpenAPIValues(item, replacements)
			}
		}
	case []any:
		for _, item := range value {
			rewriteOpenAPIValues(item, replacements)
		}
	}
}

func openAPIDocument(cfg Config, router *Router) ([]byte, error) {
	raw, err := apiDocumentation.ReadFile("assets/openapi.json")
	if err != nil {
		return nil, err
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, err
	}
	doc["info"].(map[string]any)["title"] = cfg.AppName
	paths := doc["paths"].(map[string]any)
	adjusted := map[string]any{}
	operations := map[string]bool{}
	replacements := map[string]string{}
	modelRenames := map[string]string{}
	for path, rawItem := range paths {
		newPath := path
		if strings.HasPrefix(path, "/api/") {
			newPath = cfg.APIPrefix + strings.TrimPrefix(path, "/api")
		}
		item := rawItem.(map[string]any)
		for method, rawOperation := range item {
			switch method {
			case "get", "post", "put", "patch", "delete", "head", "options", "trace":
			default:
				continue
			}
			operation := rawOperation.(map[string]any)
			id := operation["operationId"].(string)
			baseSuffix := openAPISanitize(path) + "_" + method
			if !strings.HasSuffix(id, baseSuffix) {
				return nil, fmt.Errorf("OpenAPI operation ID does not match %s %s", method, path)
			}
			newID := strings.TrimSuffix(id, baseSuffix) + openAPISanitize(newPath) + "_" + method
			operation["operationId"] = newID
			replacements[openAPIResponseTitle(id)] = openAPIResponseTitle(newID)
			bodyName, newBodyName := "Body_"+id, "Body_"+newID
			replacements[bodyName] = newBodyName
			oldKey, newKey := openAPIDefinitionName(bodyName), openAPIDefinitionName(newBodyName)
			modelRenames[oldKey] = newKey
			replacements["#/components/schemas/"+oldKey] = "#/components/schemas/" + newKey
			operations[strings.ToUpper(method)+" "+newPath] = true
		}
		adjusted[newPath] = item
	}
	if cfg.EnableMetrics {
		adjusted["/metrics"] = map[string]any{"get": map[string]any{"summary": "Metrics", "description": "Endpoint that serves Prometheus metrics.", "operationId": "metrics_metrics_get", "responses": map[string]any{"200": map[string]any{"description": "Successful Response", "content": map[string]any{"application/json": map[string]any{"schema": map[string]any{}}}}}}}
		operations["GET /metrics"] = true
	}
	registered := map[string]bool{}
	for _, operation := range router.operations {
		registered[operation] = true
	}
	var missing, extra []string
	for operation := range operations {
		if !registered[operation] {
			missing = append(missing, operation)
		}
	}
	for operation := range registered {
		if !operations[operation] {
			extra = append(extra, operation)
		}
	}
	if len(missing)+len(extra) > 0 {
		sort.Strings(missing)
		sort.Strings(extra)
		return nil, fmt.Errorf("OpenAPI registration mismatch: missing=%v extra=%v", missing, extra)
	}
	doc["paths"] = adjusted
	models := doc["components"].(map[string]any)["schemas"].(map[string]any)
	for old, renamed := range modelRenames {
		if old == renamed {
			continue
		}
		if model, ok := models[old]; ok {
			delete(models, old)
			models[renamed] = model
		}
	}
	rewriteOpenAPIValues(doc, replacements)
	return json.Marshal(doc)
}

// RegisterAPIDocumentation must run after all business route registration.
func RegisterAPIDocumentation(router *Router, cfg Config) error {
	document, err := openAPIDocument(cfg, router)
	if err != nil {
		return err
	}
	serve := func(path, contentType string, body []byte) {
		router.handleDocumentation(path, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", contentType)
			w.Header().Set("Content-Length", strconv.Itoa(len(body)))
			if r.Method != http.MethodHead {
				_, _ = w.Write(body)
			}
		})
	}
	serve("/openapi.json", "application/json", document)
	if cfg.Environment == "local" {
		for path, asset := range map[string]string{"/docs": "swagger.html", "/redoc": "redoc.html", "/docs/oauth2-redirect": "oauth2-redirect.html"} {
			body, err := apiDocumentation.ReadFile("assets/" + asset)
			if err != nil {
				return err
			}
			body = []byte(strings.ReplaceAll(string(body), "__55NORTH_APP_TITLE__", cfg.AppName))
			serve(path, "text/html; charset=utf-8", body)
		}
	}
	return nil
}
