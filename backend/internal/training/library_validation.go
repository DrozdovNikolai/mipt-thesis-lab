package training

import (
	"encoding/json"
	"fmt"
	"math/big"
	"net/http"
	"strings"

	"north55/backend/internal/platform"
)

// Python distinguishes decimal digits (accepted by int) from the larger
// isdigit set, which also includes superscripts and circled digits.
func libraryDigits(raw string) (string, bool, bool) {
	var out strings.Builder
	allDigits, allDecimal := raw != "", raw != ""
	for _, r := range raw {
		digit := -1
		// Decimal blocks from Unicode 14.
		for _, start := range []rune{48, 1632, 1776, 1984, 2406, 2534, 2662, 2790, 2918, 3046, 3174, 3302, 3430, 3558, 3664, 3792, 3872, 4160, 4240, 6112, 6160, 6470, 6608, 6784, 6800, 6992, 7088, 7232, 7248, 42528, 43216, 43264, 43472, 43504, 43600, 44016, 65296, 66720, 68912, 69734, 69872, 69942, 70096, 70384, 70736, 70864, 71248, 71360, 71472, 71904, 72016, 72784, 73040, 73120, 92768, 92864, 93008, 120782, 120792, 120802, 120812, 120822, 123200, 123632, 125264, 130032} {
			if r >= start && r < start+10 {
				digit = int(r - start)
				break
			}
		}
		if digit >= 0 {
			out.WriteByte(byte('0' + digit))
			continue
		}
		allDecimal = false
		other := false
		for _, span := range [][2]rune{{178, 179}, {185, 185}, {4969, 4977}, {6618, 6618}, {8304, 8304}, {8308, 8313}, {8320, 8329}, {9312, 9320}, {9332, 9340}, {9352, 9360}, {9450, 9450}, {9461, 9469}, {9471, 9471}, {10102, 10110}, {10112, 10120}, {10122, 10130}, {68160, 68163}, {69216, 69224}, {69714, 69722}, {127232, 127242}} {
			if r >= span[0] && r <= span[1] {
				other = true
				break
			}
		}
		allDigits = allDigits && other
	}
	return out.String(), allDecimal, allDigits
}

func librarySeverity(raw any, loc []any) (any, []any) {
	value, ok := raw.(string)
	if !ok {
		return raw, nil
	}
	value = pythonTrim(value)
	if value == "" {
		return nil, nil
	}
	switch assessmentUpper(value) {
	case "HIGH":
		return json.Number("8"), nil
	case "MEDIUM":
		return json.Number("5"), nil
	case "LOW":
		return json.Number("2"), nil
	}
	decimal, valid, digits := libraryDigits(value)
	if valid {
		if len(decimal) > 4300 {
			return nil, []any{platform.ValueDetail(fmt.Sprintf("Exceeds the limit (4300 digits) for integer string conversion: value has %d digits; use sys.set_int_max_str_digits() to increase the limit", len(decimal)), loc, raw)}
		}
		n, _ := new(big.Int).SetString(decimal, 10)
		return json.Number(n.String()), nil
	}
	if digits {
		return nil, []any{platform.ValueDetail(fmt.Sprintf("invalid literal for int() with base 10: '%s'", value), loc, raw)}
	}
	return raw, nil
}

func libraryAircraftField() platform.Field {
	return platform.Field{Name: "aircraft_id", Alias: "aircraftId", Kind: "integer_or_string", Nullable: true, AllowBigInteger: true}
}
func libraryElementSchema(create bool) platform.Schema {
	return platform.Schema{Fields: []platform.Field{
		{Name: "name", Kind: "string", Max: 255, Required: create, Nullable: !create},
		{Name: "default_duration_minutes", Alias: "defaultDurationMinutes", Kind: "integer", NonNegative: true, Nullable: true, AllowBigInteger: true},
		{Name: "severity", Kind: "integer", NonNegative: true, Max: 10, Nullable: true, AllowBigInteger: true, Before: librarySeverity},
		libraryAircraftField(),
	}}
}
func libraryFolderSchema(create bool) platform.Schema {
	return platform.Schema{Fields: []platform.Field{
		{Name: "name", Kind: "string", Max: 255, Required: create, Nullable: !create},
		{Name: "color_hex", Alias: "colorHex", Kind: "string", Max: 7, Nullable: true},
		{Name: "library_kind", Alias: "libraryKind", Kind: "literal", Choices: []string{"exercise", "competence"}, Nullable: true},
		{Name: "parent_id", Alias: "parentId", Kind: "integer", Nullable: true, AllowBigInteger: true}, libraryAircraftField(),
		{Name: "order_index", Alias: "orderIndex", Kind: "integer", Nullable: true, AllowBigInteger: true},
	}}
}
func libraryItemSchema(create bool, c libraryCollection) platform.Schema {
	fields := []platform.Field{{Name: "folder_id", Alias: "folderId", Kind: "integer", Required: create, Nullable: !create, AllowBigInteger: true}, {Name: "element_id", Alias: "elementId", Kind: "integer", Required: create, Nullable: !create, AllowBigInteger: true}, {Name: "order_index", Alias: "orderIndex", Kind: "integer", Nullable: !create, AllowBigInteger: true}}
	if c == blockLibrary {
		fields[1].Name, fields[1].Alias = "block_id", "blockId"
	}
	if create {
		fields[2].Default = int64(0)
	} else if c == elementLibrary {
		fields = []platform.Field{fields[1], fields[2], fields[0]}
	}
	return platform.Schema{Fields: fields}
}

// The API accepts integer IDs beyond PostgreSQL bigint's range. They reach the
// database after service access checks, instead of becoming request errors.
func libraryInput(r *http.Request, bodySchema *platform.Schema, names ...string) (platform.Object, platform.Object, error) {
	pathSchema := catalogPathSchema(names...)
	for i := range pathSchema.Fields {
		pathSchema.Fields[i].AllowBigInteger = true
	}
	if bodySchema != nil {
		return platform.ReadPathAndBody(r, pathSchema, *bodySchema)
	}
	raw := map[string]any{}
	for _, name := range names {
		raw[name] = r.PathValue(name)
	}
	path, err := platform.ValidateObject(raw, []any{"path"}, pathSchema)
	return path, nil, err
}
