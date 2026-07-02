package training

import (
	"fmt"
	"reflect"
	"regexp"
	"strings"
	"unicode/utf8"
)

var colorPattern = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)

func normalizedColor(value string) *string {
	value = strings.ToUpper(pythonTrim(value))
	if !colorPattern.MatchString(value) {
		return nil
	}
	return &value
}
func normalizeGuidance(raw any) (map[string]any, error) {
	return normalizeGuidanceOrdered(raw, libraryJSONOrder(nil).keys)
}
func normalizeGuidanceOrdered(raw any, keys func(map[string]any) []string) (map[string]any, error) {
	if raw == nil {
		return nil, nil
	}
	doc, ok := raw.(map[string]any)
	if !ok {
		if r, valid := raw.(record); valid {
			doc = map[string]any(r)
		} else {
			return nil, fmt.Errorf("guidance_doc must be an object")
		}
	}
	if format, exists := doc["format"]; exists && format != "quill-delta" {
		return nil, fmt.Errorf("guidance_doc format must be quill-delta")
	}
	validVersion, err := guidanceVersion(jsonDefault(doc, "version", 1))
	if err != nil {
		return nil, err
	}
	if !validVersion {
		return nil, fmt.Errorf("guidance_doc version must be 1")
	}
	items, ok := doc["ops"].([]any)
	if !ok {
		return nil, fmt.Errorf("guidance_doc ops must be a list")
	}
	if len(items) > 400 {
		return nil, fmt.Errorf("guidance_doc cannot contain more than 400 ops")
	}
	out := []map[string]any{}
	plain := ""
	for _, item := range items {
		op, ok := item.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("rich text op must be an object")
		}
		text, ok := op["insert"].(string)
		if !ok {
			return nil, fmt.Errorf("rich text op insert must be a string")
		}
		attrs := map[string]any{}
		if op["attributes"] != nil {
			values, ok := op["attributes"].(map[string]any)
			if !ok {
				return nil, fmt.Errorf("rich text attributes must be an object")
			}
			for _, key := range keys(values) {
				value := values[key]
				switch key {
				case "bold":
					if value == true {
						attrs[key] = true
					} else if value != nil && !jsonEqual(value, false) {
						return nil, fmt.Errorf("rich text bold attribute must be boolean")
					}
				case "color":
					if value == nil || value == "" {
						continue
					}
					s, ok := value.(string)
					if !ok {
						return nil, fmt.Errorf("rich text color must use #RRGGBB")
					}
					color := normalizedColor(s)
					if color == nil {
						return nil, fmt.Errorf("rich text color must use #RRGGBB")
					}
					attrs[key] = *color
				default:
					return nil, fmt.Errorf("unsupported rich text attribute: %s", key)
				}
			}
		}
		text = strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n")
		if text == "" {
			continue
		}
		plain += text
		if len(out) > 0 {
			previous, _ := out[len(out)-1]["attributes"].(map[string]any)
			if len(previous) == 0 && len(attrs) == 0 || reflect.DeepEqual(previous, attrs) {
				out[len(out)-1]["insert"] = out[len(out)-1]["insert"].(string) + text
				continue
			}
		}
		normalized := map[string]any{"insert": text}
		if len(attrs) > 0 {
			normalized["attributes"] = attrs
		}
		out = append(out, normalized)
	}
	plain = strings.ReplaceAll(strings.TrimSuffix(plain, "\n"), "\u00a0", " ")
	if pythonTrim(plain) == "" {
		return nil, nil
	}
	if utf8.RuneCountInString(plain) > 2000 {
		return nil, fmt.Errorf("guidance text cannot exceed 2000 characters")
	}
	ops := make([]any, len(out))
	for i := range out {
		ops[i] = out[i]
	}
	return map[string]any{"version": 1, "format": "quill-delta", "ops": ops}, nil
}
