// Package canonical implements the existing Dart/Python training wire hash profile.
package canonical

import (
	"bytes"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// JSON matches json.dumps(ensure_ascii=False, allow_nan=False,
// separators=(',', ':'), sort_keys=True). In particular it does not HTML-escape
// or escape U+2028/U+2029, and preserves Python's float/integer distinction.
func JSON(payload map[string]any) ([]byte, error) {
	var out bytes.Buffer
	if err := appendValue(&out, reflect.ValueOf(payload)); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}
func SHA256(payload map[string]any) (string, error) {
	data, err := JSON(payload)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}
func EqualHash(expected, actual string) bool {
	return subtle.ConstantTimeCompare([]byte(strings.ToLower(expected)), []byte(strings.ToLower(actual))) == 1
}

func appendString(out *bytes.Buffer, s string) error {
	if !utf8.ValidString(s) {
		return fmt.Errorf("canonical string is not valid UTF-8")
	}
	out.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			out.WriteString(`\"`)
		case '\\':
			out.WriteString(`\\`)
		case '\b':
			out.WriteString(`\b`)
		case '\f':
			out.WriteString(`\f`)
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		default:
			if r < 0x20 {
				fmt.Fprintf(out, `\u%04x`, r)
			} else {
				out.WriteRune(r)
			}
		}
	}
	out.WriteByte('"')
	return nil
}

// FloatString renders a finite float like Python str/repr, including the .0
// suffix and the threshold for scientific notation.
func FloatString(value float64) (string, error) {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return "", fmt.Errorf("non-finite canonical float")
	}
	// Decide notation from the shortest decimal representation, avoiding log10
	// rounding at powers of ten.
	exponential := strconv.FormatFloat(value, 'e', -1, 64)
	_, expText, _ := strings.Cut(exponential, "e")
	exponent, _ := strconv.Atoi(expText)
	if value != 0 && (exponent >= 16 || exponent < -4) {
		return exponential, nil
	}
	text := strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return text, nil
}
func appendValue(out *bytes.Buffer, value reflect.Value) error {
	if !value.IsValid() {
		out.WriteString("null")
		return nil
	}
	if value.Kind() == reflect.Interface || value.Kind() == reflect.Pointer {
		if value.IsNil() {
			out.WriteString("null")
			return nil
		}
		return appendValue(out, value.Elem())
	}
	if value.Type() == reflect.TypeOf(json.Number("")) {
		number := value.Interface().(json.Number)
		if strings.ContainsAny(string(number), ".eE") {
			f, err := number.Float64()
			if err != nil {
				return err
			}
			text, err := FloatString(f)
			if err != nil {
				return err
			}
			out.WriteString(text)
		} else {
			integer, ok := new(big.Int).SetString(string(number), 10)
			if !ok {
				return fmt.Errorf("invalid canonical integer")
			}
			out.WriteString(integer.String())
		}
		return nil
	}
	if value.Type() == reflect.TypeOf(big.Int{}) {
		integer := value.Interface().(big.Int)
		out.WriteString(integer.String())
		return nil
	}
	switch value.Kind() {
	case reflect.String:
		return appendString(out, value.String())
	case reflect.Bool:
		out.WriteString(strconv.FormatBool(value.Bool()))
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		out.WriteString(strconv.FormatInt(value.Int(), 10))
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		out.WriteString(strconv.FormatUint(value.Uint(), 10))
	case reflect.Float32, reflect.Float64:
		text, err := FloatString(value.Float())
		if err != nil {
			return err
		}
		out.WriteString(text)
	case reflect.Map:
		if value.IsNil() {
			out.WriteString("null")
			return nil
		}
		if value.Type().Key().Kind() != reflect.String {
			return fmt.Errorf("canonical object keys must be strings")
		}
		keys := value.MapKeys()
		sort.Slice(keys, func(i, j int) bool { return keys[i].String() < keys[j].String() })
		out.WriteByte('{')
		for i, key := range keys {
			if i > 0 {
				out.WriteByte(',')
			}
			if err := appendString(out, key.String()); err != nil {
				return err
			}
			out.WriteByte(':')
			if err := appendValue(out, value.MapIndex(key)); err != nil {
				return err
			}
		}
		out.WriteByte('}')
	case reflect.Slice, reflect.Array:
		out.WriteByte('[')
		for i := 0; i < value.Len(); i++ {
			if i > 0 {
				out.WriteByte(',')
			}
			if err := appendValue(out, value.Index(i)); err != nil {
				return err
			}
		}
		out.WriteByte(']')
	default:
		return fmt.Errorf("unsupported canonical type %s", value.Type())
	}
	return nil
}
