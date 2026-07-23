package training

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"

	"north55/backend/internal/platform"
)

var scenarioRevisionKinds = []string{"AUTO", "MANUAL"}

// The legacy "ai" action is inert history metadata. These routes only store
// user-supplied snapshots; they do not start generation or speech processing.
var scenarioRevisionActions = []string{"edit", "restore", "autosave", "manual", "ai", "branch"}

func scenarioSnapshotSchema(order libraryJSONOrder, fatal *error) platform.Schema {
	params := libraryParamModel(order, fatal)
	params.Fields = params.Fields[:6] // ExerciseParamPayload has no block duration/crew fields.
	element := libraryBlockElementModel(true, true)
	element.Fields = element.Fields[1:] // Snapshot elements have no association ID.
	element.Fields[0].Min = 1
	integer := func(name string, required, nullable bool) platform.Field {
		return platform.Field{Name: name, Alias: libraryCamel(name), Kind: "integer", Required: required, Nullable: nullable, AllowBigInteger: true}
	}
	duration := integer("duration_minutes", false, true)
	duration.NonNegative = true
	exercise := platform.Schema{Fields: []platform.Field{
		integer("id", true, false),
		{Name: "client_uid", Alias: "clientUid", Kind: "string", Nullable: true, Max: 36},
		integer("module_id", true, false),
		{Name: "kind", Kind: "literal", Choices: []string{"standard", "preparation", "coffee_break", "individual"}, Default: "standard"},
		integer("order_index", true, false), duration, integer("crew_member_number", false, true),
		{Name: "competence_ids", Alias: "competenceIds", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "integer", AllowBigInteger: true}},
		{Name: "elements", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &element}},
		{Name: "params", Kind: "object", Schema: &params, Nullable: true},
	}}
	day, column := integer("day_index", false, true), integer("content_subcolumn_id", false, true)
	day.Min, column.Min = 1, 1
	module := platform.Schema{Fields: []platform.Field{
		integer("id", true, false),
		{Name: "client_uid", Alias: "clientUid", Kind: "string", Nullable: true, Max: 36},
		integer("scenario_id", true, false), integer("order_index", true, false), day,
		{Name: "day_start", Alias: "dayStart", Kind: "boolean", Default: false}, duration, column,
		{Name: "exercises", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &exercise}},
	}}
	return platform.Schema{Fields: []platform.Field{{Name: "modules", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &module}}}}
}

func scenarioRevisionSchema(batch bool, order libraryJSONOrder, fatal *error) platform.Schema {
	snapshot := scenarioSnapshotSchema(order, fatal)
	client := platform.Field{Name: "client_entry_id", Alias: "clientEntryId", Kind: "string", Nullable: !batch, Required: batch, Max: 80}
	created := platform.Field{Name: "client_created_at_ms", Alias: "clientCreatedAtMs", Kind: "integer", NonNegative: true, Nullable: !batch, Required: batch, AllowBigInteger: true}
	kind := platform.Field{Name: "kind", Kind: "literal", Choices: scenarioRevisionKinds, Default: "AUTO"}
	label := platform.Field{Name: "label", Kind: "string", Nullable: true, Max: 255}
	fields := []platform.Field{kind, label, client, created}
	if batch {
		fields = []platform.Field{client, created, kind, label}
	}
	fields = append(fields, platform.Field{Name: "action", Kind: "literal", Choices: scenarioRevisionActions, Nullable: true})
	for _, name := range []string{"branch_id", "parent_client_entry_id", "base_client_entry_id", "restored_from_client_entry_id"} {
		fields = append(fields, platform.Field{Name: name, Alias: libraryCamel(name), Kind: "string", Nullable: true, Max: 80})
	}
	fields = append(fields, platform.Field{Name: "snapshot", Kind: "object", Schema: &snapshot, Required: true})
	model := platform.Schema{Fields: fields}
	if !batch {
		return model
	}
	return platform.Schema{Fields: []platform.Field{{Name: "items", Kind: "list", Default: []any{}, Min: 1, Max: 25, Item: &platform.Field{Kind: "object", Schema: &model}}}}
}

// Snapshot signatures include every model default, unlike partial update DTOs.
// Build fresh maps/lists so shared default values never acquire request data.
func scenarioModelDefaults(value any, schema platform.Schema) map[string]any {
	input := libraryRecord(value)
	out := map[string]any{}
	for _, field := range schema.Fields {
		v, ok := input[field.Name]
		if !ok {
			v = field.Default
		}
		if v != nil && field.Kind == "object" {
			v = scenarioModelDefaults(v, *field.Schema)
		} else if v != nil && field.Kind == "list" {
			items := []any{}
			for _, item := range v.([]any) {
				if field.Item.Kind == "object" {
					item = scenarioModelDefaults(item, *field.Item.Schema)
				}
				items = append(items, item)
			}
			v = items
		}
		out[field.Name] = v
	}
	return out
}

func scenarioContentInput(r *http.Request, model func(libraryJSONOrder, *error) platform.Schema) (platform.Object, platform.Object, error) {
	return scenarioResourceInput(r, model, true, "scenario_id")
}

func scenarioResourceInput(r *http.Request, model func(libraryJSONOrder, *error) platform.Schema, defaults bool, names ...string) (platform.Object, platform.Object, error) {
	pathSchema := platform.Schema{}
	for _, name := range names {
		pathSchema.Fields = append(pathSchema.Fields, platform.Field{Name: name, Kind: "integer", Required: true, AllowBigInteger: true})
	}
	var fatal error
	path, body, err := platform.ReadPathAndBodyUsing(r, pathSchema, func() (platform.Object, error) {
		var raw bytes.Buffer
		r.Body = io.NopCloser(io.TeeReader(r.Body, &raw))
		if _, err := platform.ReadJSON(r); err != nil {
			return nil, err
		}
		order := libraryJSONOrder{}
		decoder := json.NewDecoder(&raw)
		decoder.UseNumber()
		decoded, err := order.decode(decoder)
		if err != nil {
			return nil, err
		}
		schema := model(order, &fatal)
		value, err := platform.ValidateBody(decoded, schema)
		if err != nil {
			return nil, err
		}
		if defaults {
			return platform.Object(scenarioModelDefaults(value, schema)), nil
		}
		return value, nil
	})
	if fatal != nil {
		return nil, nil, fatal
	}
	return path, body, err
}
