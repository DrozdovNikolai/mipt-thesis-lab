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

func Middleware(cfg Config, next http.Handler, limiters ...RateLimiter) http.Handler {
	original := next
	next = requestMiddleware(next, cfg.Metrics)
	if cfg.EnableRateLimit {
		var limiter RateLimiter = newMemoryRateLimiter(cfg.RateLimitPerMinute, cfg.RateLimitPerSecond)
		if len(limiters) > 0 && limiters[0] != nil {
			limiter = limiters[0]
		}
		next = rateLimitMiddleware(limiter, next)
	}
	next = corsMiddleware(cfg, next)
	if cfg.EnableMetrics {
		if router, ok := original.(*Router); ok {
			next = metricsMiddleware(cfg.Metrics, router, next)
		}
	}
	if router, ok := original.(*Router); ok {
		next = cfg.ErrorTracker.Middleware(router, next)
	}
	return next
}

func requestMiddleware(next http.Handler, metrics ...*telemetry.Metrics) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		state := &requestLogState{path: r.URL.Path, tracking: traceState(r.Context())}
		if len(metrics) > 0 {
			state.metrics = metrics[0]
		}
		r = requestLogContext(r, state)
		writer := &requestLogWriter{ResponseWriter: w, state: state}
		requestID := r.Header.Get("X-Request-ID")
		if requestID == "" {
			requestID = uuid.NewString()
		}
		w.Header().Set("X-Request-ID", requestID)
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-XSS-Protection", "1; mode=block")
		w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
		w.Header().Set("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
		defer func() {
			if recoverValue := recover(); recoverValue != nil {
				WriteError(writer, fmt.Errorf("request panic: %v", recoverValue))
			}
			recordRequestCompletion(r, writer, requestID, started)
		}()
		next.ServeHTTP(writer, r)
	})
}

func corsMiddleware(cfg Config, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		hasOrigin := len(r.Header.Values("Origin")) > 0
		allowed := false
		wildcard := false
		if cfg.EnableCORS && hasOrigin {
			w.Header().Set("Access-Control-Allow-Credentials", "true")
			for _, v := range cfg.AllowedOrigins {
				v = strings.TrimSpace(v)
				if v == "*" {
					wildcard = true
					allowed = true
				}
				if v == origin {
					allowed = true
				}
			}
			if allowed {
				if wildcard && len(r.Header.Values("Cookie")) == 0 {
					w.Header().Set("Access-Control-Allow-Origin", "*")
				} else {
					w.Header().Set("Access-Control-Allow-Origin", origin)
					w.Header().Add("Vary", "Origin")
				}
			}
		}
		if cfg.EnableCORS && r.Method == http.MethodOptions && len(r.Header.Values("Access-Control-Request-Method")) > 0 && hasOrigin {
			w.Header().Del("Access-Control-Allow-Origin")
			if allowed {
				w.Header().Set("Access-Control-Allow-Origin", origin)
			}
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT")
			if len(r.Header.Values("Access-Control-Request-Headers")) > 0 {
				w.Header().Set("Access-Control-Allow-Headers", r.Header.Get("Access-Control-Request-Headers"))
			}
			w.Header().Set("Access-Control-Max-Age", "600")
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			failures := []string{}
			if !allowed {
				failures = append(failures, "origin")
			}
			switch r.Header.Get("Access-Control-Request-Method") {
			case "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT":
			default:
				failures = append(failures, "method")
			}
			if len(failures) > 0 {
				w.WriteHeader(400)
				_, _ = w.Write([]byte("Disallowed CORS " + strings.Join(failures, ", ")))
				return
			}
			_, _ = w.Write([]byte("OK"))
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Object retains presence and null independently for partial update semantics.
type Object map[string]any
type Field struct {
	Name, Alias, Kind, Pattern string
	Required, Nullable         bool
	Min, Max                   int
	Default                    any
	NonNegative                bool
	GreaterThanZero            bool
	AllowBigInteger            bool
	Decimal                    *DecimalConstraints
	Choices                    []string
	Schema                     *Schema
	Item                       *Field
	Before                     func(any, []any) (any, []any)
	Check                      func(any) string
}

type Schema struct {
	Fields      []Field
	Check       func(Object) string
	ForbidExtra bool
}

func (o Object) Has(name string) bool      { _, ok := o[name]; return ok }
func (o Object) String(name string) string { v, _ := o[name].(string); return v }
func (o Object) StringPtr(name string) *string {
	v, ok := o[name].(string)
	if !ok {
		return nil
	}
	return &v
}
func (o Object) Int(name string) int64 { v, _ := o[name].(int64); return v }

// CompareInteger compares an unbounded client watermark without narrowing it.
func (o Object) CompareInteger(name string, other int64) int {
	if value, ok := o[name].(*big.Int); ok {
		return value.Cmp(big.NewInt(other))
	}
	value := o.Int(name)
	if value < other {
		return -1
	}
	if value > other {
		return 1
	}
	return 0
}
func (o Object) Bool(name string) bool { v, _ := o[name].(bool); return v }

func validationError(details []any) *APIError {
	return &APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": details}}
}
func Detail(kind, message string, loc []any, input any, ctx map[string]any) map[string]any {
	d := map[string]any{"type": kind, "loc": loc, "msg": message, "input": input, "url": "https://errors.pydantic.dev/2.6/v/" + kind}
	if ctx != nil {
		d["ctx"] = ctx
	}
	return d
}

func ReadObject(r *http.Request, fields ...Field) (Object, error) {
	return ReadSchema(r, Schema{Fields: fields})
}

func ReadSchema(r *http.Request, schema Schema) (Object, error) {
	decoded, err := ReadJSON(r)
	if err != nil {
		return nil, err
	}
	return ValidateBody(decoded, schema)
}

func ValidateBody(decoded any, schema Schema) (Object, error) {
	if decoded == nil {
		return nil, validationError([]any{Detail("missing", "Field required", []any{"body"}, nil, nil)})
	}
	return ValidateObject(decoded, []any{"body"}, schema)
}

func ReadJSON(r *http.Request) (any, error) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024*1024+1))
	if err != nil {
		return nil, Error(400, "There was an error parsing the body")
	}
	if len(raw) > 16*1024*1024 {
		return nil, Error(413, "Request body too large")
	}
	var decoded any
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	if len(raw) == 0 {
		return nil, validationError([]any{Detail("missing", "Field required", []any{"body"}, nil, nil)})
	}
	if err := decoder.Decode(&decoded); err != nil {
		return nil, jsonDecodeError(raw, err)
	}
	end := int(decoder.InputOffset())
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		for end < len(raw) && strings.ContainsRune(" \t\r\n", rune(raw[end])) {
			end++
		}
		return nil, jsonErrorAt(raw, end, "Extra data")
	}
	return decoded, nil
}

func ValidateObject(decoded any, location []any, schema Schema) (Object, error) {
	body, ok := decoded.(map[string]any)
	if !ok {
		return nil, validationError([]any{Detail("model_attributes_type", "Input should be a valid dictionary or object to extract fields from", location, decoded, nil)})
	}
	output := Object{}
	details := []any{}
	consumed := map[string]bool{}
	for _, f := range schema.Fields {
		alias := f.Alias
		if alias == "" {
			alias = f.Name
		}
		v, present := body[alias]
		locName := alias
		if !present {
			v, present = body[f.Name]
			if present {
				locName = f.Name
			}
		}
		loc := append(append([]any{}, location...), locName)
		if present {
			consumed[locName] = true
		}
		if !present {
			if f.Required {
				details = append(details, Detail("missing", "Field required", loc, body, nil))
			} else if f.Default != nil {
				output[f.Name] = f.Default
			}
			continue
		}
		if f.Before != nil {
			var more []any
			v, more = f.Before(v, loc)
			if len(more) > 0 {
				details = append(details, more...)
				continue
			}
		}
		if v == nil && f.Nullable {
			output[f.Name] = nil
			continue
		}
		switch f.Kind {
		case "string":
			value, ok := v.(string)
			if !ok {
				details = append(details, Detail("string_type", "Input should be a valid string", loc, v, nil))
				continue
			}
			length := utf8.RuneCountInString(value)
			if f.Min > 0 && length < f.Min {
				details = append(details, Detail("string_too_short", stringLengthMessage("at least", f.Min), loc, v, map[string]any{"minLength": f.Min}))
				continue
			}
			if f.Max > 0 && length > f.Max {
				details = append(details, Detail("string_too_long", stringLengthMessage("at most", f.Max), loc, v, map[string]any{"maxLength": f.Max}))
				continue
			}
			if f.Pattern != "" && !regexp.MustCompile(f.Pattern).MatchString(value) {
				details = append(details, Detail("string_pattern_mismatch", fmt.Sprintf("String should match pattern '%s'", f.Pattern), loc, v, map[string]any{"pattern": f.Pattern}))
				continue
			}
			output[f.Name] = value
		case "integer":
			var value int64
			var wide *big.Int
			var err error
			kind, message := "int_parsing", "Input should be a valid integer, unable to parse string as an integer"
			switch n := v.(type) {
			case json.Number:
				value, err = integralNumber(string(n))
				if err != nil && f.AllowBigInteger {
					wide, err = bigInteger(string(n))
				}
				kind, message = "int_from_float", "Input should be a valid integer, got a number with a fractional part"
			case string:
				if regexp.MustCompile(`^[+-]?[0-9]+(?:_[0-9]+)*(?:\.0+)?$`).MatchString(n) {
					value, err = integralNumber(strings.ReplaceAll(n, "_", ""))
					if err != nil && f.AllowBigInteger {
						wide, err = bigInteger(strings.ReplaceAll(n, "_", ""))
					}
				} else {
					err = fmt.Errorf("invalid integer string")
				}
			case bool:
				if n {
					value = 1
				}
			default:
				err = fmt.Errorf("type")
				kind, message = "int_type", "Input should be a valid integer"
			}
			if err != nil {
				details = append(details, Detail(kind, message, loc, v, nil))
				continue
			}
			compare := func(other int64) int {
				if wide != nil {
					return wide.Cmp(big.NewInt(other))
				}
				if value < other {
					return -1
				}
				if value > other {
					return 1
				}
				return 0
			}
			if f.GreaterThanZero && compare(0) <= 0 {
				details = append(details, Detail("greater_than", "Input should be greater than 0", loc, v, map[string]any{"gt": 0}))
				continue
			}
			if (f.Min > 0 || f.NonNegative) && compare(int64(f.Min)) < 0 {
				details = append(details, Detail("greater_than_equal", fmt.Sprintf("Input should be greater than or equal to %d", f.Min), loc, v, map[string]any{"ge": f.Min}))
				continue
			}
			if f.Max > 0 && compare(int64(f.Max)) > 0 {
				details = append(details, Detail("less_than_equal", fmt.Sprintf("Input should be less than or equal to %d", f.Max), loc, v, map[string]any{"le": f.Max}))
				continue
			}
			output[f.Name] = value
			if wide != nil {
				output[f.Name] = wide
			}
		case "boolean":
			var value bool
			valid := true
			kind, message := "bool_parsing", "Input should be a valid boolean, unable to interpret input"
			switch n := v.(type) {
			case bool:
				value = n
			case string:
				switch strings.ToLower(n) {
				case "true", "1", "on", "yes", "y", "t":
					value = true
				case "false", "0", "off", "no", "n", "f":
					value = false
				default:
					valid = false
				}
			case json.Number:
				number, err := integralNumber(string(n))
				if err == nil && number == 1 {
					value = true
				} else if err != nil || number != 0 {
					valid = false
				}
			default:
				valid = false
				kind, message = "bool_type", "Input should be a valid boolean"
			}
			if !valid {
				details = append(details, Detail(kind, message, loc, v, nil))
				continue
			}
			output[f.Name] = value
		default:
			value, more := validateExtended(v, loc, f)
			if len(more) > 0 {
				details = append(details, more...)
				continue
			}
			output[f.Name] = value
		}
		if f.Check != nil {
			if message := f.Check(output[f.Name]); message != "" {
				details = append(details, ValueDetail(message, loc, v))
			}
		}
	}
	if schema.ForbidExtra {
		keys := []string{}
		for key := range body {
			if !consumed[key] {
				keys = append(keys, key)
			}
		}
		sort.Strings(keys)
		for _, key := range keys {
			loc := append(append([]any{}, location...), key)
			details = append(details, Detail("extra_forbidden", "Extra inputs are not permitted", loc, body[key], nil))
		}
	}
	if len(details) > 0 {
		return nil, validationError(details)
	}
	if schema.Check != nil {
		if message := schema.Check(output); message != "" {
			return nil, validationError([]any{ValueDetail(message, location, decoded)})
		}
	}
	return output, nil
}

func stringLengthMessage(bound string, count int) string {
	unit := "characters"
	if count == 1 {
		unit = "character"
	}
	return fmt.Sprintf("String should have %s %d %s", bound, count, unit)
}

func integralNumber(text string) (int64, error) {
	n, ok := new(big.Rat).SetString(text)
	if !ok || !n.IsInt() || !n.Num().IsInt64() {
		return 0, fmt.Errorf("not a representable integer")
	}
	return n.Num().Int64(), nil
}

func bigInteger(text string) (*big.Int, error) {
	n, ok := new(big.Rat).SetString(text)
	if !ok || !n.IsInt() {
		return nil, fmt.Errorf("not an integer")
	}
	return new(big.Int).Set(n.Num()), nil
}

func jsonErrorAt(raw []byte, offset int, message string) *APIError {
	if offset < 0 {
		offset = 0
	}
	if offset > len(raw) {
		offset = len(raw)
	}
	detail := Detail("json_invalid", "JSON decode error", []any{"body", utf8.RuneCount(raw[:offset])}, map[string]any{}, map[string]any{"error": message})
	delete(detail, "url")
	return validationError([]any{detail})
}
func jsonDecodeError(raw []byte, err error) *APIError {
	offset := len(raw)
	message := "Expecting value"
	var syntax *json.SyntaxError
	if errors.As(err, &syntax) {
		offset = int(syntax.Offset) - 1
		text := syntax.Error()
		switch {
		case strings.Contains(text, "object key string"):
			message = "Expecting property name enclosed in double quotes"
		case strings.Contains(text, "after object key:value pair"), strings.Contains(text, "after array element"):
			message = "Expecting ',' delimiter"
		case strings.Contains(text, "after object key"):
			message = "Expecting ':' delimiter"
		case strings.Contains(text, "string escape code"):
			message = `Invalid \escape`
			offset--
		case strings.Contains(text, "in string literal"):
			message = "Invalid control character at"
		}
	} else {
		trimmed := strings.TrimRight(string(raw), " \t\r\n")
		if strings.HasSuffix(trimmed, "{") {
			message = "Expecting property name enclosed in double quotes"
		} else if strings.HasSuffix(trimmed, "\"") || strings.HasSuffix(trimmed, "}") || strings.HasSuffix(trimmed, "]") {
			message = "Expecting ',' delimiter"
		}
	}
	// An unterminated JSON string reports its opening quote, including after a key.
	quoted, escaped, start := false, false, 0
	for i, b := range raw {
		if quoted {
			if escaped {
				escaped = false
			} else if b == '\\' {
				escaped = true
			} else if b == '"' {
				quoted = false
			}
		} else if b == '"' {
			quoted = true
			start = i
		}
	}
	if quoted && (err == io.ErrUnexpectedEOF || err == io.EOF) {
		offset = start
		message = "Unterminated string starting at"
	}
	return jsonErrorAt(raw, offset, message)
}

func PathInt(r *http.Request, name string) (int64, error) {
	raw := r.PathValue(name)
	v, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return 0, validationError([]any{Detail("int_parsing", "Input should be a valid integer, unable to parse string as an integer", []any{"path", name}, raw, nil)})
	}
	return v, nil
}

// ReadPathAndBody preserves FastAPI's combined validation details, while a JSON
// parsing failure takes precedence over both path and model validation.
func ReadPathAndBody(r *http.Request, pathSchema, bodySchema Schema) (Object, Object, error) {
	return ReadPathAndBodyUsing(r, pathSchema, func() (Object, error) { return ReadSchema(r, bodySchema) })
}

// ReadPathAndBodyUsing preserves combined FastAPI validation errors for bodies
// that need additional decoding information, such as JSON object insertion order.
func ReadPathAndBodyUsing(r *http.Request, pathSchema Schema, readBody func() (Object, error)) (Object, Object, error) {
	raw := map[string]any{}
	for _, field := range pathSchema.Fields {
		raw[field.Name] = r.PathValue(field.Name)
	}
	path, pathErr := ValidateObject(raw, []any{"path"}, pathSchema)
	body, bodyErr := readBody()
	if bodyErr != nil {
		var p, b *APIError
		if errors.As(pathErr, &p) && errors.As(bodyErr, &b) && p.Code == "VALIDATION_ERROR" && b.Code == "VALIDATION_ERROR" {
			details := b.Extra["details"].([]any)
			if len(details) > 0 && details[0].(map[string]any)["type"] != "json_invalid" {
				p.Extra["details"] = append(p.Extra["details"].([]any), details...)
				return path, body, p
			}
		}
		return path, body, bodyErr
	}
	return path, body, pathErr
}
