package platform

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// DecimalConstraints describe an exact SQL numeric value. The validated result
// is a canonical decimal string; database writes never go through binary floats.
type DecimalConstraints struct {
	MaxDigits, Places int
	Minimum, Maximum  string
	// Unbounded leaves precision/scale validation to the receiving operation.
	// Scientific notation keeps very large exponents compact in memory.
	Unbounded bool
}

var decimalSyntax = regexp.MustCompile(`^([+-]?)([0-9]*)(?:\.([0-9]*))?(?:[eE]([+-]?[0-9]+))?$`)
var decimalSpecial = regexp.MustCompile(`^[+-]?(?i:inf(?:inity)?|s?nan[0-9]*)$`)

func decimalDigits(s string) string {
	return strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		for _, group := range unicode.Digit.R16 {
			if uint32(r) >= uint32(group.Lo) && uint32(r) <= uint32(group.Hi) && (uint32(r)-uint32(group.Lo))%uint32(group.Stride) == 0 {
				return '0' + rune((uint32(r)-uint32(group.Lo))/uint32(group.Stride)%10)
			}
		}
		for _, group := range unicode.Digit.R32 {
			if uint32(r) >= group.Lo && uint32(r) <= group.Hi && (uint32(r)-group.Lo)%group.Stride == 0 {
				return '0' + rune((uint32(r)-group.Lo)/group.Stride%10)
			}
		}
		return r
	}, s)
}

func validateDecimal(v any, loc []any, field Field) (any, []any) {
	fail := func(kind, message string, ctx map[string]any) (any, []any) {
		return nil, []any{Detail(kind, message, loc, v, ctx)}
	}
	var raw string
	switch value := v.(type) {
	case string:
		raw = decimalDigits(strings.ReplaceAll(strings.TrimSpace(value), "_", ""))
	case json.Number:
		raw = string(value)
		if strings.ContainsAny(raw, ".eE") {
			// Python's JSON decoder first produces a float for these JSON tokens.
			// Match that input coercion, then keep all subsequent arithmetic exact.
			n, _ := strconv.ParseFloat(raw, 64)
			if math.IsInf(n, 0) || math.IsNaN(n) {
				return fail("finite_number", "Input should be a finite number", nil)
			}
			raw = strconv.FormatFloat(n, 'g', -1, 64)
		}
	default:
		return fail("decimal_type", "Decimal input should be an integer, float, string or Decimal object", nil)
	}
	if decimalSpecial.MatchString(raw) {
		return fail("finite_number", "Input should be a finite number", nil)
	}
	parts := decimalSyntax.FindStringSubmatch(raw)
	if parts == nil || parts[2] == "" && parts[3] == "" {
		return fail("decimal_parsing", "Input should be a valid decimal", nil)
	}
	exponent := int64(0)
	if parts[4] != "" {
		var err error
		exponent, err = strconv.ParseInt(parts[4], 10, 64)
		if err != nil || exponent > 999999999999999999 || exponent < -999999999999999999 {
			return fail("decimal_parsing", "Input should be a valid decimal", nil)
		}
	}
	coefficient := strings.TrimLeft(parts[2]+parts[3], "0")
	exponent -= int64(len(parts[3]))
	if coefficient == "" {
		coefficient, exponent = "0", 0
	} else {
		trimmed := strings.TrimRight(coefficient, "0")
		exponent += int64(len(coefficient) - len(trimmed))
		coefficient = trimmed
	}
	places := max(-exponent, 0)
	whole := max(int64(len(coefficient))+exponent, 0)
	digits := whole + places
	rules := field.Decimal
	if rules == nil {
		return fail("value_error", "Decimal constraints are required", nil)
	}
	if rules.Unbounded {
		if field.GreaterThanZero && (coefficient == "0" || parts[1] == "-") {
			return fail("greater_than", "Input should be greater than 0", map[string]any{"gt": 0})
		}
		value := coefficient + "e" + strconv.FormatInt(exponent, 10)
		if parts[1] == "-" && coefficient != "0" {
			value = "-" + value
		}
		return value, nil
	}
	if digits > int64(rules.MaxDigits) {
		return fail("decimal_max_digits", fmt.Sprintf("Decimal input should have no more than %d digits in total", rules.MaxDigits), map[string]any{"maxDigits": rules.MaxDigits})
	}
	if places > int64(rules.Places) {
		return fail("decimal_max_places", fmt.Sprintf("Decimal input should have no more than %d decimal places", rules.Places), map[string]any{"decimalPlaces": rules.Places})
	}
	if whole > int64(rules.MaxDigits-rules.Places) {
		return fail("decimal_whole_digits", fmt.Sprintf("Decimal input should have no more than %d digits before the decimal point", rules.MaxDigits-rules.Places), map[string]any{"wholeDigits": rules.MaxDigits - rules.Places})
	}
	// Expand only after the digit bounds have passed, even for hostile exponents.
	value := coefficient
	if exponent >= 0 {
		value += strings.Repeat("0", int(exponent))
	} else {
		if places >= int64(len(value)) {
			value = strings.Repeat("0", int(places)-len(value)+1) + value
		}
		cut := len(value) - int(places)
		value = value[:cut] + "." + value[cut:]
	}
	if parts[1] == "-" && coefficient != "0" {
		value = "-" + value
	}
	n, _ := new(big.Rat).SetString(value)
	for _, bound := range []struct {
		raw, kind, label, key string
		lower                 bool
	}{
		{rules.Minimum, "greater_than_equal", "greater than or equal to", "ge", true},
		{rules.Maximum, "less_than_equal", "less than or equal to", "le", false},
	} {
		if bound.raw == "" {
			continue
		}
		limit, _ := new(big.Rat).SetString(bound.raw)
		if bound.lower && n.Cmp(limit) < 0 || !bound.lower && n.Cmp(limit) > 0 {
			return fail(bound.kind, "Input should be "+bound.label+" "+bound.raw, map[string]any{bound.key: json.Number(bound.raw)})
		}
	}
	return value, nil
}
