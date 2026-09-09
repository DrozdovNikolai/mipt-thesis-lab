package training

import (
	"encoding/json"
	"fmt"
	"math/big"
	"reflect"
	"strconv"
	"strings"
	"unicode"

	"github.com/google/uuid"
)

func jsonMap(v any) map[string]any {
	switch x := v.(type) {
	case map[string]any:
		return x
	case record:
		return map[string]any(x)
	}
	return nil
}
func jsonCopy(v any) any {
	if m := jsonMap(v); m != nil {
		out := map[string]any{}
		for k, x := range m {
			out[k] = jsonCopy(x)
		}
		return out
	}
	if a, ok := v.([]any); ok {
		out := make([]any, len(a))
		for i, x := range a {
			out[i] = jsonCopy(x)
		}
		return out
	}
	return v
}
func jsonDefault(m map[string]any, key string, fallback any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return fallback
}
func pythonTrim(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f })
}
func jsonTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		n, ok := new(big.Rat).SetString(string(x))
		return !ok || n.Sign() != 0
	case int64:
		return x != 0
	case int:
		return x != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}
func pythonString(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case json.Number:
		return string(x)
	}
	return fmt.Sprint(v)
}
func jsonText(v any) string {
	if !jsonTruthy(v) {
		return ""
	}
	return pythonString(v)
}
func jsonNumeric(v any) (*big.Rat, bool) {
	switch v.(type) {
	case json.Number, int, int64, float64, bool, *big.Int:
	default:
		return nil, false
	}
	if b, ok := v.(bool); ok {
		if b {
			return big.NewRat(1, 1), true
		}
		return big.NewRat(0, 1), true
	}
	return new(big.Rat).SetString(fmt.Sprint(v))
}

// Python compares JSON numeric values by value, including bool/int. Hash proofs
// remain stricter and use the original values with the canonical encoder.
func jsonEqual(a, b any) bool {
	if x, ok := jsonNumeric(a); ok {
		y, ok := jsonNumeric(b)
		return ok && x.Cmp(y) == 0
	}
	if x := jsonMap(a); x != nil {
		y := jsonMap(b)
		if y == nil || len(x) != len(y) {
			return false
		}
		for k, v := range x {
			w, ok := y[k]
			if !ok || !jsonEqual(v, w) {
				return false
			}
		}
		return true
	}
	if x, ok := a.([]any); ok {
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !jsonEqual(x[i], y[i]) {
				return false
			}
		}
		return true
	}
	return reflect.DeepEqual(a, b)
}
func draftInteger(v any, field string, positive bool) (int64, error) {
	reason := "must be a non-negative integer"
	if positive {
		reason = "must be a positive integer"
	}
	if _, ok := v.(bool); ok {
		return 0, invalidDraft(field, reason)
	}
	s := pythonTrim(pythonString(v))
	// int(str(value)) accepts separators between digits, but no fractional notation.
	if strings.Contains(s, "_") {
		for i, r := range s {
			if r == '_' && (i == 0 || i == len(s)-1 || s[i-1] < '0' || s[i-1] > '9' || s[i+1] < '0' || s[i+1] > '9') {
				return 0, invalidDraft(field, reason)
			}
		}
		s = strings.ReplaceAll(s, "_", "")
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil || n < 0 || positive && n == 0 {
		return 0, invalidDraft(field, reason)
	}
	return n, nil
}
func draftUUID(v any, field string) (string, error) {
	s := strings.ToLower(pythonTrim(jsonText(v)))
	id, err := uuid.Parse(s)
	if err != nil || id.Version() != 7 || id.Variant() != uuid.RFC4122 {
		return "", invalidDraft(field, "must be RFC4122 UUIDv7")
	}
	return id.String(), nil
}
