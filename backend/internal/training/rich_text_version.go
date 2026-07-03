package training

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
)

// The HTTP adapter returns a server error for these integer conversion failures.
type guidanceUnhandledError struct{ message string }

func (e *guidanceUnhandledError) Error() string { return e.message }

func guidanceVersion(raw any) (bool, error) {
	if !jsonTruthy(raw) {
		return false, nil
	}
	switch value := raw.(type) {
	case bool:
		return value, nil
	case int:
		return value == 1, nil
	case int64:
		return value == 1, nil
	case json.Number:
		if !strings.ContainsAny(string(value), ".eE") {
			n, ok := new(big.Int).SetString(string(value), 10)
			return ok && n.Cmp(big.NewInt(1)) == 0, nil
		}
		f, _ := strconv.ParseFloat(string(value), 64)
		if math.IsInf(f, 0) || math.IsNaN(f) {
			return false, &guidanceUnhandledError{"cannot convert non-finite float to integer"}
		}
		return f >= 1 && f < 2, nil
	case string:
		normalized := pythonTrim(value)
		var out strings.Builder
		for _, r := range normalized {
			if r == '+' || r == '-' || r == '_' {
				out.WriteRune(r)
				continue
			}
			digit, valid, _ := libraryDigits(string(r))
			if !valid {
				return false, fmt.Errorf("invalid literal for int() with base 10: %s", libraryPythonQuote(value))
			}
			out.WriteString(digit)
		}
		digits := out.String()
		if !regexp.MustCompile(`^[+-]?[0-9]+(?:_[0-9]+)*$`).MatchString(digits) {
			return false, fmt.Errorf("invalid literal for int() with base 10: %s", libraryPythonQuote(value))
		}
		digits = strings.ReplaceAll(digits, "_", "")
		if n := len(strings.TrimLeft(digits, "+-")); n > 4300 {
			return false, fmt.Errorf("Exceeds the limit (4300 digits) for integer string conversion: value has %d digits; use sys.set_int_max_str_digits() to increase the limit", n)
		}
		n, _ := new(big.Int).SetString(digits, 10)
		return n.Cmp(big.NewInt(1)) == 0, nil
	default:
		return false, &guidanceUnhandledError{"int argument has invalid type"}
	}
}
