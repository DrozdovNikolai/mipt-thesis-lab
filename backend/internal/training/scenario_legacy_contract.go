package training

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func scenarioBumpContentVersion(ctx context.Context, db runtimeDB, id any, userID int64, expected any, message string) (int64, error) {
	query := `UPDATE scenario SET content_version=content_version+1,updated_by=$2,updated_at=now() WHERE id=$1 AND deleted_at IS NULL`
	args := []any{id, userID}
	if expected != nil {
		query += ` AND content_version=$3`
		args = append(args, expected)
	}
	var version int64
	err := db.QueryRow(ctx, query+` RETURNING content_version`, args...).Scan(&version)
	if !errors.Is(err, pgx.ErrNoRows) {
		return version, err
	}
	err = db.QueryRow(ctx, `SELECT content_version FROM scenario WHERE id=$1 AND deleted_at IS NULL`, id).Scan(&version)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, commanderError(404, "SCENARIO_NOT_FOUND", "Scenario not found")
	}
	if err != nil {
		return 0, err
	}
	return 0, &platform.APIError{Status: 409, Code: "SCENARIO_VERSION_CONFLICT", Message: message, Extra: map[string]any{"current_version": version}}
}

func (s *Service) applyLegacyContentContract(ctx context.Context, db runtimeDB, id any, user *auth.User, client string, expected any) error {
	required := s.Auth.Config.Environment == "prod"
	if flag := s.Auth.Config.ScenarioRequireLegacyContentContract; flag != nil {
		required = *flag
	}
	if required && client == "" {
		return scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required for production scenario content writes", nil)
	}
	if required && expected == nil {
		return scenarioSnapshotError("EXPECTED_VERSION_REQUIRED", "expectedVersion query parameter is required for production scenario content writes", nil)
	}
	if expected != nil && client == "" {
		return scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required when expectedVersion is provided", nil)
	}
	// Legacy content writes without an editor session still participate in
	// source/snapshot serialization before changing content or deleting media.
	if err := lockScenarioSnapshotSource(ctx, db, id, true); err != nil {
		return err
	}
	if client != "" {
		if err := s.ensureScenarioContentLock(ctx, db, id, user, client); err != nil {
			return err
		}
	}
	_, err := scenarioBumpContentVersion(ctx, db, id, user.InternalID, expected, "Scenario was modified by another request")
	return err
}

func scenarioQueryError(bodyErr, queryErr error) error {
	if queryErr == nil {
		return bodyErr
	}
	if bodyErr == nil {
		return queryErr
	}
	var b, q *platform.APIError
	if !errors.As(bodyErr, &b) || !errors.As(queryErr, &q) || b.Code != "VALIDATION_ERROR" || q.Code != "VALIDATION_ERROR" {
		return bodyErr
	}
	details := b.Extra["details"].([]any)
	for _, raw := range details {
		if libraryRecord(raw).text("type") == "json_invalid" {
			return bodyErr
		}
	}
	combined := []any{}
	for _, raw := range details {
		loc := libraryRecord(raw)["loc"].([]any)
		if len(loc) > 0 && loc[0] == "path" {
			combined = append(combined, raw)
		}
	}
	combined = append(combined, q.Extra["details"].([]any)...)
	for _, raw := range details {
		loc := libraryRecord(raw)["loc"].([]any)
		if len(loc) == 0 || loc[0] != "path" {
			combined = append(combined, raw)
		}
	}
	b.Extra["details"] = combined
	return b
}

func editorInput(r *http.Request, resource, action string) (platform.Object, platform.Object, platform.Object, error) {
	names := []string{}
	if action != "create" {
		names = append(names, resource+"_id")
	}
	var path, body platform.Object
	var inputErr error
	if action == "delete" {
		path, body, inputErr = libraryInput(r, nil, names...)
	} else {
		path, body, inputErr = scenarioResourceInput(r, func(order libraryJSONOrder, fatal *error) platform.Schema {
			return editorContentSchema(resource, action, order, fatal)
		}, false, names...)
	}
	query, queryErr := platform.QueryObject(r.URL.Query(), platform.Field{Name: "expected_version", Alias: "expectedVersion", Kind: "integer", Nullable: true, AllowBigInteger: true})
	return path, body, query, scenarioQueryError(inputErr, queryErr)
}

func editorContentSchema(resource, action string, order libraryJSONOrder, fatal *error) platform.Schema {
	create := action == "create"
	integer := func(name string, required, nullable bool) platform.Field {
		return platform.Field{Name: name, Alias: libraryCamel(name), Kind: "integer", Required: required, Nullable: nullable, AllowBigInteger: true}
	}
	client := platform.Field{Name: "client_uid", Alias: "clientUid", Kind: "string", Nullable: true, Max: 36}
	if action == "duplicate" {
		return platform.Schema{Fields: []platform.Field{client}}
	}
	ordering := integer("order_index", false, !create)
	ordering.NonNegative = !create
	if create {
		ordering.Default = int64(0)
	}
	duration := integer("duration_minutes", false, true)
	duration.NonNegative = true
	if resource == "module" {
		day := platform.Field{Name: "day_start", Alias: "dayStart", Kind: "boolean", Nullable: !create}
		if create {
			day.Default = false
		}
		column := integer("content_subcolumn_id", false, true)
		column.Min = 1
		fields := []platform.Field{ordering, day, duration, column}
		if create {
			fields = append([]platform.Field{integer("scenario_id", true, false), client}, fields...)
		}
		return platform.Schema{Fields: fields}
	}
	params := libraryParamModel(order, fatal)
	params.Fields = params.Fields[:6]
	element := libraryBlockElementModel(true, true)
	element.Fields = element.Fields[1:]
	element.Fields[0].Min = 1
	kind := platform.Field{Name: "kind", Kind: "literal", Choices: []string{"standard", "preparation", "coffee_break", "individual"}, Nullable: !create}
	if create {
		kind.Default = "standard"
	}
	elements := platform.Field{Name: "elements", Kind: "list", Nullable: !create, Item: &platform.Field{Kind: "object", Schema: &element}}
	competences := platform.Field{Name: "competence_ids", Alias: "competenceIds", Kind: "list", Nullable: !create, Item: &platform.Field{Kind: "integer", AllowBigInteger: true}}
	if create {
		elements.Default = []any{}
		competences.Default = []any{}
	}
	fields := []platform.Field{integer("module_id", create, !create)}
	if create {
		fields = append(fields, client)
	}
	fields = append(fields, kind, ordering, duration, integer("crew_member_number", false, true), elements, platform.Field{Name: "params", Kind: "object", Schema: &params, Nullable: true}, competences)
	return platform.Schema{Fields: fields}
}
