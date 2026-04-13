package auth

import (
	"encoding/json"
	"time"

	"north55/backend/internal/platform"
)

func userAdminSchema(create bool) platform.Schema {
	fields := []platform.Field{
		{Name: "login", Kind: "string", Required: create, Nullable: !create, Min: 3, Max: 50},
		userEmailField(create),
		{Name: "password", Kind: "string", Required: create, Nullable: !create, Min: 8, Max: 128},
	}
	if create {
		fields = append(fields, platform.Field{Name: "roles", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "uuid"}})
	}
	fields = append(fields, platform.Field{Name: "airline_id", Alias: "airlineId", Kind: "integer", Nullable: true, AllowBigInteger: true})
	aircraft := platform.Field{Name: "aircraft_ids", Alias: "aircraftIds", Kind: "list", Nullable: !create, Item: &platform.Field{Kind: "integer_or_string", AllowBigInteger: true}}
	if create {
		aircraft.Default = []any{}
	}
	fields = append(fields, aircraft,
		platform.Field{Name: "first_name", Alias: "firstName", Kind: "string", Nullable: true, Max: 100},
		platform.Field{Name: "last_name", Alias: "lastName", Kind: "string", Nullable: true, Max: 100},
		platform.Field{Name: "date_of_birth", Alias: "dateOfBirth", Kind: "date", Nullable: true, Before: func(value any, loc []any) (any, []any) {
			switch value.(type) {
			case nil, string, json.Number:
				return value, nil
			default:
				return nil, []any{platform.Detail("date_type", "Input should be a valid date", loc, value, nil)}
			}
		}, Check: func(value any) string {
			if value == nil {
				return ""
			}
			year, month, day := time.Now().Date()
			if value.(time.Time).After(time.Date(year, month, day, 0, 0, 0, 0, time.UTC)) {
				return "date_of_birth cannot be in the future"
			}
			return ""
		}},
		platform.Field{Name: "position_id", Alias: "positionId", Kind: "integer", Nullable: true, Min: 1, AllowBigInteger: true},
		platform.Field{Name: "license_number", Alias: "licenseNumber", Kind: "string", Nullable: true, Max: 50},
		platform.Field{Name: "phone", Kind: "string", Nullable: true, Max: 30},
	)
	return platform.Schema{Fields: fields, ForbidExtra: true}
}
