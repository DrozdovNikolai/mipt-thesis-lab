package training

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

const libraryTLFields = "airport_name time_of_day runway braking_action special_wx wind_dir wind_speed wind_gust visibility_value clouds_amount clouds_ceiling_ft rvr_h rvr_v temperature_c qnh_hpa fuel cg_percent"
const libraryTakeoffFields = "thrust_setting flaps_setting v2_speed vr_speed v1_speed sid squawk_code frequency climb"
const libraryParamFields = "duration_minutes crew_member_number original_tl_id destination_tl_id intensity zfw_t guidance_doc guidance_plain_text"
const libraryBlockElementFields = "element_id order_index details starting_height ending_height profile_type"

type libraryJSONOrder map[string][]string

func (o libraryJSONOrder) keys(value map[string]any) []string {
	if keys, ok := o[fmt.Sprintf("%p", value)]; ok {
		return keys
	}
	keys := make([]string, 0, len(value))
	for key := range value {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// The regular parser checks syntax, size and error locations first. A token
// pass retains key order for Python dict repr and rich-text error precedence.
func (o libraryJSONOrder) decode(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	switch token {
	case json.Delim('{'):
		value := map[string]any{}
		keys := []string{}
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return nil, err
			}
			key := keyToken.(string)
			if _, found := value[key]; !found {
				keys = append(keys, key)
			}
			value[key], err = o.decode(decoder)
			if err != nil {
				return nil, err
			}
		}
		_, err = decoder.Token()
		o[fmt.Sprintf("%p", value)] = keys
		return value, err
	case json.Delim('['):
		value := []any{}
		for decoder.More() {
			item, err := o.decode(decoder)
			if err != nil {
				return nil, err
			}
			value = append(value, item)
		}
		_, err = decoder.Token()
		return value, err
	default:
		return token, nil
	}
}

func libraryPythonQuote(value string) string {
	quote := '\''
	if strings.ContainsRune(value, '\'') && !strings.ContainsRune(value, '"') {
		quote = '"'
	}
	var out strings.Builder
	out.WriteRune(quote)
	for _, r := range value {
		switch {
		case r == quote || r == '\\':
			out.WriteRune('\\')
			out.WriteRune(r)
		case r == '\n':
			out.WriteString(`\n`)
		case r == '\r':
			out.WriteString(`\r`)
		case r == '\t':
			out.WriteString(`\t`)
		case !libraryPythonPrintable(r):
			if r <= 255 {
				fmt.Fprintf(&out, `\x%02x`, r)
			} else if r <= 65535 {
				fmt.Fprintf(&out, `\u%04x`, r)
			} else {
				fmt.Fprintf(&out, `\U%08x`, r)
			}
		default:
			out.WriteRune(r)
		}
	}
	out.WriteRune(quote)
	return out.String()
}
func (o libraryJSONOrder) pythonRepr(raw any) string {
	switch value := raw.(type) {
	case string:
		return libraryPythonQuote(value)
	case []any:
		parts := []string{}
		for _, item := range value {
			parts = append(parts, o.pythonRepr(item))
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		parts := []string{}
		for _, key := range o.keys(value) {
			parts = append(parts, libraryPythonQuote(key)+": "+o.pythonRepr(value[key]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case json.Number:
		if !strings.ContainsAny(string(value), ".eE") {
			n, _ := new(big.Int).SetString(string(value), 10)
			return n.String()
		}
		f, _ := strconv.ParseFloat(string(value), 64)
		if math.IsInf(f, 1) {
			return "inf"
		}
		if math.IsInf(f, -1) {
			return "-inf"
		}
		text, _ := canonical.FloatString(f)
		return text
	default:
		return pythonString(raw)
	}
}

func (o libraryJSONOrder) stringBefore(numericName string) func(any, []any) (any, []any) {
	return func(raw any, loc []any) (any, []any) {
		if raw == nil {
			return nil, nil
		}
		value, ok := raw.(string)
		if !ok {
			value = o.pythonRepr(raw)
		}
		if numericName != "" {
			value = pythonTrim(value)
			if value == "" {
				return nil, nil
			}
			_, _, digits := libraryDigits(strings.Replace(value, ".", "", 1))
			if !digits {
				return nil, []any{platform.ValueDetail(numericName+" must be a number", loc, raw)}
			}
		}
		return value, nil
	}
}

func libraryCamel(name string) string {
	parts := strings.Split(name, "_")
	for i := 1; i < len(parts); i++ {
		parts[i] = strings.ToUpper(parts[i][:1]) + parts[i][1:]
	}
	return strings.Join(parts, "")
}
func libraryTLModel(order libraryJSONOrder) platform.Schema {
	fields := []platform.Field{}
	numbers := " wind_dir wind_speed wind_gust visibility_value clouds_ceiling_ft rvr_h rvr_v temperature_c qnh_hpa fuel cg_percent v2_speed vr_speed v1_speed "
	for _, name := range strings.Fields(libraryTLFields + " " + libraryTakeoffFields) {
		f := platform.Field{Name: name, Alias: libraryCamel(name), Kind: "string", Nullable: true}
		if strings.Contains(numbers, " "+name+" ") {
			f.Before = order.stringBefore("")
		}
		if name == "fuel" {
			f.Before = order.stringBefore("fuel")
		}
		fields = append(fields, f)
	}
	return platform.Schema{Fields: fields}
}
func libraryParamModel(order libraryJSONOrder, fatal *error) platform.Schema {
	tl := libraryTLModel(order)
	return platform.Schema{Fields: []platform.Field{
		{Name: "intensity", Kind: "string", Nullable: true},
		{Name: "zfw_t", Alias: "zfwT", Kind: "string", Nullable: true, Before: order.stringBefore("zfw_t")},
		{Name: "guidance_doc", Alias: "guidanceDoc", Kind: "dictionary", Nullable: true, Before: func(raw any, loc []any) (any, []any) {
			value, err := normalizeGuidanceOrdered(raw, order.keys)
			if err == nil {
				if value == nil {
					return nil, nil
				}
				return value, nil
			}
			var unhandled *guidanceUnhandledError
			if errors.As(err, &unhandled) {
				*fatal = err
				return nil, nil
			}
			return nil, []any{platform.ValueDetail(err.Error(), loc, raw)}
		}},
		{Name: "guidance_plain_text", Alias: "guidancePlainText", Kind: "string", Nullable: true},
		{Name: "original_tl", Alias: "originalTl", Kind: "object", Schema: &tl, Nullable: true},
		{Name: "destination_tl", Alias: "destinationTl", Kind: "object", Schema: &tl, Nullable: true},
		{Name: "duration_minutes", Alias: "durationMinutes", Kind: "integer", NonNegative: true, Nullable: true, AllowBigInteger: true},
		{Name: "crew_member_number", Alias: "crewMemberNumber", Kind: "integer", Nullable: true, AllowBigInteger: true},
	}}
}
func libraryBlockElementModel(create, defaults bool) platform.Schema {
	fields := []platform.Field{}
	if create {
		fields = append(fields, platform.Field{Name: "id", Kind: "integer", Nullable: true, AllowBigInteger: true})
	}
	fields = append(fields,
		platform.Field{Name: "element_id", Alias: "elementId", Kind: "integer", Required: create, Nullable: !create, AllowBigInteger: true},
		platform.Field{Name: "order_index", Alias: "orderIndex", Kind: "integer", Nullable: !create, AllowBigInteger: true},
		platform.Field{Name: "details", Kind: "string", Nullable: true},
		platform.Field{Name: "starting_height", Alias: "startingHeight", Kind: "integer", NonNegative: true, Nullable: true, AllowBigInteger: true},
		platform.Field{Name: "ending_height", Alias: "endingHeight", Kind: "integer", NonNegative: true, Nullable: true, AllowBigInteger: true},
		platform.Field{Name: "profile_type", Alias: "profileType", Kind: "literal", Choices: []string{"FLAT", "UP", "DOWN", "LINKED"}, Nullable: !create})
	if defaults {
		for i := range fields {
			if fields[i].Name == "order_index" {
				fields[i].Default = int64(0)
			}
			if fields[i].Name == "profile_type" {
				fields[i].Default = "FLAT"
			}
		}
	}
	return platform.Schema{Fields: fields}
}
func libraryBlockModel(create bool, order libraryJSONOrder, fatal *error) platform.Schema {
	params := libraryParamModel(order, fatal)
	element := libraryBlockElementModel(true, create)
	fields := []platform.Field{
		{Name: "params", Kind: "object", Schema: &params, Nullable: true},
		{Name: "elements", Kind: "list", Item: &platform.Field{Kind: "object", Schema: &element}, Nullable: !create},
		{Name: "competence_ids", Alias: "competenceIds", Kind: "list", Item: &platform.Field{Kind: "integer", AllowBigInteger: true}, Nullable: !create},
	}
	if create {
		fields[1].Default, fields[2].Default = []any{}, []any{}
	}
	return platform.Schema{Fields: fields}
}
func libraryBlockInput(r *http.Request, create bool) (platform.Object, platform.Object, error) {
	pathSchema := platform.Schema{}
	if !create {
		pathSchema.Fields = []platform.Field{{Name: "block_id", Kind: "integer", Required: true, AllowBigInteger: true}}
	}
	var fatal error
	path, body, err := platform.ReadPathAndBodyUsing(r, pathSchema, func() (platform.Object, error) {
		var raw bytes.Buffer
		r.Body = io.NopCloser(io.TeeReader(r.Body, &raw))
		decoded, err := platform.ReadJSON(r)
		if err != nil {
			return nil, err
		}
		order := libraryJSONOrder{}
		decoder := json.NewDecoder(&raw)
		decoder.UseNumber()
		decoded, err = order.decode(decoder)
		if err != nil {
			return nil, err
		}
		return platform.ValidateBody(decoded, libraryBlockModel(create, order, &fatal))
	})
	if fatal != nil {
		return nil, nil, fatal
	}
	return path, body, err
}
