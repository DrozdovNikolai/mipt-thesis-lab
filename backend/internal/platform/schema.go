package platform

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

var naiveDateTime = time.FixedZone("naive", 0)

func HasTimeZone(value time.Time) bool { return value.Location() != naiveDateTime }

func ValueDetail(message string, loc []any, input any) map[string]any {
	return Detail("value_error", "Value error, "+message, loc, input, map[string]any{"error": map[string]any{}})
}

func validateExtended(v any, loc []any, f Field) (any, []any) {
	fail := func(kind, message string, ctx map[string]any) (any, []any) {
		return nil, []any{Detail(kind, message, loc, v, ctx)}
	}
	switch f.Kind {
	case "integer_or_string":
		// Pydantic's smart union keeps strings as strings before attempting
		// coercion to an integer. Failed alternatives retain their own locations.
		if value, ok := v.(string); ok {
			return value, nil
		}
		value, err := ValidateObject(map[string]any{"int": v}, loc, Schema{Fields: []Field{{Name: "int", Kind: "integer", Required: true, AllowBigInteger: f.AllowBigInteger}}})
		if err == nil {
			return value["int"], nil
		}
		details := err.(*APIError).Extra["details"].([]any)
		details = append(details, Detail("string_type", "Input should be a valid string", append(append([]any{}, loc...), "str"), v, nil))
		return nil, details
	case "decimal":
		return validateDecimal(v, loc, f)
	case "date":
		parsed, details := validateExtended(v, loc, Field{Kind: "datetime"})
		if len(details) > 0 {
			message := dateParseMessage(v)
			if raw, ok := v.(string); ok && len(raw) > 10 && len(raw) < 19 && message == "unexpected extra characters at the end of the input" {
				message = "input is too short"
			}
			return fail("date_from_datetime_parsing", "Input should be a valid date or datetime, "+message, map[string]any{"error": message})
		}
		t := parsed.(time.Time)
		if raw, ok := v.(string); ok {
			normalized := strings.ReplaceAll(strings.ReplaceAll(strings.Replace(raw, " ", "T", 1), "t", "T"), "z", "Z")
			if local, err := time.Parse(time.RFC3339Nano, normalized); err == nil {
				t = local
			}
		}
		if t.Hour() != 0 || t.Minute() != 0 || t.Second() != 0 || t.Nanosecond() != 0 {
			return fail("date_from_datetime_inexact", "Datetimes provided to dates should have zero time - e.g. be exact dates", nil)
		}
		return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC), nil
	case "dictionary", "string_dictionary":
		value, ok := v.(map[string]any)
		if !ok {
			return fail("dict_type", "Input should be a valid dictionary", nil)
		}
		if f.Kind == "string_dictionary" {
			details := []any{}
			for key, item := range value {
				if _, ok := item.(string); !ok {
					path := append(append([]any{}, loc...), key)
					details = append(details, Detail("string_type", "Input should be a valid string", path, item, nil))
				}
			}
			if len(details) > 0 {
				return nil, details
			}
		}
		return value, nil
	case "literal_integer":
		for _, choice := range f.Choices {
			n, _ := strconv.ParseInt(choice, 10, 64)
			if raw, ok := v.(json.Number); ok {
				if value, err := integralNumber(string(raw)); err == nil && value == n {
					return n, nil
				}
			}
			if b, ok := v.(bool); ok && (b && n == 1 || !b && n == 0) {
				return n, nil
			}
		}
		expected := strings.Join(f.Choices, " or ")
		return fail("literal_error", "Input should be "+expected, map[string]any{"expected": expected})
	case "literal":
		for _, choice := range f.Choices {
			if v == choice {
				return choice, nil
			}
		}
		quoted := make([]string, len(f.Choices))
		for i, choice := range f.Choices {
			quoted[i] = "'" + choice + "'"
		}
		expected := strings.Join(quoted, ", ")
		if len(quoted) > 1 {
			expected = strings.Join(quoted[:len(quoted)-1], ", ") + " or " + quoted[len(quoted)-1]
		}
		return fail("literal_error", "Input should be "+expected, map[string]any{"expected": expected})
	case "uuid", "uuid7":
		value, ok := v.(string)
		if !ok {
			return fail("uuid_type", "UUID input should be a string, bytes or UUID object", nil)
		}
		id, err := uuid.Parse(value)
		if err != nil {
			message := uuidParseMessage(value)
			return fail("uuid_parsing", "Input should be a valid UUID, "+message, map[string]any{"error": message})
		}
		if f.Kind == "uuid7" && (id.Version() != 7 || id.Variant() != uuid.RFC4122) {
			return nil, []any{ValueDetail(f.Name+" must be RFC4122 UUIDv7", loc, v)}
		}
		return id, nil
	case "datetime":
		var parsed time.Time
		var err error
		switch value := v.(type) {
		case string:
			value = strings.Replace(value, " ", "T", 1)
			value = strings.ReplaceAll(strings.ReplaceAll(value, "t", "T"), "z", "Z")
			if regexp.MustCompile(`^[+-]?[0-9]+(?:\.[0-9]+)?$`).MatchString(value) {
				return validateExtended(json.Number(value), loc, f)
			}
			if regexp.MustCompile(`[+-][0-9]{4}$`).MatchString(value) && len(value) > 10 {
				value = value[:len(value)-2] + ":" + value[len(value)-2:]
			}
			parsed, err = time.Parse(time.RFC3339Nano, value)
			if err != nil {
				for _, layout := range []string{"2006-01-02T15:04:05.999999999", "2006-01-02T15:04", "2006-01-02"} {
					if naive, e := time.Parse(layout, value); e == nil {
						return naive.In(naiveDateTime), nil
					} // Field validator rejects a missing offset.
				}
			}
		case json.Number:
			var number float64
			number, err = strconv.ParseFloat(string(value), 64)
			if err == nil {
				if number > 2e10 || number < -2e10 {
					number /= 1000
				}
				seconds := int64(number)
				parsed = time.Unix(seconds, int64((number-float64(seconds))*1e9)).UTC()
			}
		default:
			return fail("datetime_type", "Input should be a valid datetime", nil)
		}
		if err != nil {
			message := dateParseMessage(v)
			return fail("datetime_from_date_parsing", "Input should be a valid datetime or date, "+message, map[string]any{"error": message})
		}
		// Python's datetime persists microseconds. UTC is a distinct location from the
		// marker attached to naive inputs below; timezone validation uses HasTimeZone.
		return parsed.UTC().Truncate(time.Microsecond), nil
	case "object":
		object, err := ValidateObject(v, loc, *f.Schema)
		if err != nil {
			return nil, err.(*APIError).Extra["details"].([]any)
		}
		return object, nil
	case "list":
		values, ok := v.([]any)
		if !ok {
			return fail("list_type", "Input should be a valid list", nil)
		}
		if f.Max > 0 && len(values) > f.Max {
			return fail("too_long", fmt.Sprintf("List should have at most %d items after validation, not %d", f.Max, len(values)), map[string]any{"fieldType": "List", "maxLength": f.Max, "actualLength": len(values)})
		}
		out := make([]any, 0, len(values))
		details := []any{}
		for i, value := range values {
			item := *f.Item
			item.Name = "item"
			item.Alias = "item"
			item.Required = true
			object, err := ValidateObject(map[string]any{"item": value}, nil, Schema{Fields: []Field{item}})
			if err != nil {
				for _, raw := range err.(*APIError).Extra["details"].([]any) {
					d := raw.(map[string]any)
					path := d["loc"].([]any)
					d["loc"] = append(append(append([]any{}, loc...), i), path[1:]...)
					details = append(details, d)
				}
			} else {
				out = append(out, object["item"])
			}
		}
		if len(details) == 0 && f.Min > 0 && len(out) < f.Min {
			unit := "items"
			if f.Min == 1 {
				unit = "item"
			}
			return fail("too_short", fmt.Sprintf("List should have at least %d %s after validation, not %d", f.Min, unit, len(out)), map[string]any{"fieldType": "List", "minLength": f.Min, "actualLength": len(out)})
		}
		return out, details
	}
	return fail("value_error", "Unsupported schema type", nil)
}

// Pydantic's non-strict datetime parser falls back to parsing a date, and reports
// that parser's error when both forms fail.
func dateParseMessage(value any) string {
	text, ok := value.(string)
	if !ok {
		return "invalid datetime value"
	}
	if len(text) < 10 {
		return "input is too short"
	}
	if _, err := strconv.Atoi(text[:4]); err != nil {
		return "invalid character in year"
	}
	if text[4] != '-' {
		return "invalid date separator, expected `-`"
	}
	month, err := strconv.Atoi(text[5:7])
	if err != nil {
		return "invalid character in month"
	}
	if month < 1 || month > 12 {
		return "month value is outside expected range of 1-12"
	}
	if text[7] != '-' {
		return "invalid date separator, expected `-`"
	}
	day, err := strconv.Atoi(text[8:10])
	if err != nil {
		return "invalid character in day"
	}
	year, _ := strconv.Atoi(text[:4])
	last := time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
	if day < 1 || day > last {
		return "day value is outside expected range"
	}
	return "unexpected extra characters at the end of the input"
}

func uuidParseMessage(value string) string {
	normalized := strings.TrimPrefix(value, "urn:uuid:")
	normalized = strings.TrimPrefix(strings.TrimSuffix(normalized, "}"), "{")
	for i, r := range normalized {
		if !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f' || r >= 'A' && r <= 'F' || r == '-') {
			return fmt.Sprintf("invalid character: expected an optional prefix of `urn:uuid:` followed by [0-9a-fA-F-], found `%c` at %d", r, i+1)
		}
	}
	if !strings.Contains(normalized, "-") {
		return fmt.Sprintf("invalid length: expected length 32 for simple format, found %d", len(normalized))
	}
	groups := strings.Split(normalized, "-")
	if len(groups) != 5 {
		return fmt.Sprintf("invalid group count: expected 5, found %d", len(groups))
	}
	for i, n := range []int{8, 4, 4, 4, 12} {
		if len(groups[i]) != n {
			return fmt.Sprintf("invalid group length in group %d: expected %d, found %d", i, n, len(groups[i]))
		}
	}
	return "invalid UUID format"
}

// QueryObject shares the body's scalar coercion and accumulates ordered errors.
func QueryObject(values map[string][]string, fields ...Field) (Object, error) {
	raw := map[string]any{}
	for key, items := range values {
		if len(items) > 0 {
			raw[key] = items[len(items)-1]
		}
	}
	// FastAPI Query aliases apply to query parameters independently of the JSON
	// model's populate_by_name setting. The snake_case name is not an alias here.
	for _, f := range fields {
		if f.Alias != "" && f.Alias != f.Name {
			delete(raw, f.Name)
		}
	}
	out, err := ValidateObject(raw, []any{"query"}, Schema{Fields: fields})
	if e, ok := err.(*APIError); ok {
		for _, item := range e.Extra["details"].([]any) {
			detail := item.(map[string]any)
			if detail["type"] == "missing" {
				detail["input"] = nil
			}
		}
	}
	return out, err
}
