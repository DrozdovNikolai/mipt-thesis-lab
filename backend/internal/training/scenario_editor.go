package training

import (
	"context"
	"net/http"
	"strings"
	"time"

	"north55/backend/internal/platform"
)

func (s *Service) registerScenarioEditor(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/scenarios"
	mux.HandleFunc("GET "+p, platform.Wrap(s.listEditorScenarios))
	mux.HandleFunc("GET "+p+"/summary", platform.Wrap(s.listEditorScenarioSummary))
	mux.HandleFunc("POST "+p, platform.Wrap(s.createEditorScenario))
	mux.HandleFunc("GET "+p+"/{scenario_id}", platform.Wrap(s.readEditorScenario))
	mux.HandleFunc("PUT "+p+"/{scenario_id}", platform.Wrap(s.updateEditorScenario))
	for _, operation := range []struct{ method, path, action string }{{"DELETE", "", "archive"}, {"POST", "/delete", "delete"}, {"POST", "/restore", "restore"}} {
		mux.HandleFunc(operation.method+" "+p+"/{scenario_id}"+operation.path, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			return s.changeEditorScenarioState(w, r, operation.action)
		}))
	}
	s.registerScenarioLocks(mux)
	s.registerScenarioRevisions(mux)
	s.registerScenarioContentCRUD(mux)
	mux.HandleFunc("PUT "+p+"/{scenario_id}/snapshot", platform.Wrap(s.applyScenarioSnapshot))
	mux.HandleFunc("POST "+p+"/{scenario_id}/duplicate", platform.Wrap(s.duplicateEditorScenario))
	for _, suffix := range []string{"content-set-subcolumns", "publish-validation"} {
		mux.HandleFunc("GET "+p+"/{scenario_id}/"+suffix, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			return s.readScenarioPublication(w, r, suffix == "publish-validation")
		}))
	}
}

func scenarioEditorSchema(create bool) platform.Schema {
	fields := []platform.Field{libraryAircraftField(),
		{Name: "code", Kind: "string", Nullable: true, Max: 50},
		{Name: "title", Kind: "string", Nullable: !create, Required: create, Max: 255},
		{Name: "engines", Kind: "string", Nullable: true, Max: 50},
		{Name: "comments", Kind: "string", Nullable: true},
		{Name: "status", Kind: "string", Nullable: true, Max: 50},
		{Name: "published_at", Alias: "publishedAt", Kind: "datetime", Nullable: true},
		{Name: "valid_until", Alias: "validUntil", Kind: "datetime", Nullable: true},
	}
	model := platform.Schema{Fields: fields}
	if create {
		model.Fields = append(model.Fields, platform.Field{Name: "content_set_id", Alias: "contentSetId", Kind: "integer", Min: 1, Nullable: true, AllowBigInteger: true}, platform.Field{Name: "set_label_id", Alias: "setLabelId", Kind: "integer", Min: 1, Nullable: true, AllowBigInteger: true})
		model.Check = func(o platform.Object) string {
			if (o["content_set_id"] == nil) != (o["set_label_id"] == nil) {
				return "content_set_id and set_label_id must be provided together"
			}
			return ""
		}
	}
	return model
}

func scenarioStorageChanges(data record) error {
	if value, exists := data["engines"]; exists {
		s, _ := value.(string)
		s = pythonTrim(s)
		data["engines"] = nil
		if s != "" {
			data["engines"] = s
		}
	}
	for _, field := range []string{"published_at", "valid_until"} {
		if stamp, ok := data[field].(time.Time); ok {
			data[field] = stamp.UTC().Truncate(time.Microsecond)
		}
	}
	return nil
}

func (s *Service) listEditorScenarios(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := libraryQuery(r)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAircraft(r.Context(), s.Auth.DB, u, q["aircraft_id"], false, false)
	if err != nil {
		return err
	}
	rows, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(s) FROM scenario s WHERE airline_id=$1 AND aircraft_id=ANY($2::bigint[]) AND deleted_at IS NULL AND ($3 OR status<>'ARCHIVED')`, airline, aircraft, q.Bool("include_archived"))
	if err != nil {
		return err
	}
	ids := make([]int64, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.number("id"))
	}
	graphs, err := loadEditorScenarioList(r.Context(), s.Auth.DB, ids)
	if err != nil {
		return err
	}
	items := []any{}
	for _, graph := range graphs {
		item, err := scenarioEditorDTO(graph, s.Auth.Config.APIPrefix)
		if err != nil {
			return err
		}
		items = append(items, item)
	}
	platform.WriteJSON(w, 200, items)
	return nil
}

func (s *Service) readEditorScenario(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "scenario_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(u)
	if err != nil {
		return err
	}
	row, err := scenarioGet(r.Context(), s.Auth.DB, path["scenario_id"], airline, aircraft, true, false)
	if err != nil {
		return err
	}
	return s.writeEditorScenario(r.Context(), w, row.number("id"), 200)
}

func (s *Service) writeEditorScenario(ctx context.Context, w http.ResponseWriter, id int64, status int) error {
	value, err := s.scenarioReadDTO(ctx, s.Auth.DB, id)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, status, value)
	return nil
}

func (s *Service) createEditorScenario(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, scenarioEditorSchema(true))
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	ctx := r.Context()
	aircraft, err := libraryAircraft(ctx, s.Auth.DB, u, body["aircraft_id"], true, false)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if body["content_set_id"] != nil {
		content, err := libraryFind(ctx, tx, "scenario_content_set", body["content_set_id"])
		if err != nil {
			return err
		}
		if content == nil || content.number("airline_id") != airline || !libraryContains(u.AircraftIDs, content.number("aircraft_id")) {
			return platform.Error(404, "Content set not found")
		}
		label, err := libraryFind(ctx, tx, "scenario_content_set_label", body["set_label_id"])
		if err != nil {
			return err
		}
		if label == nil || label.number("content_set_id") != content.number("id") {
			return platform.Error(404, "Content set label not found")
		}
		if aircraft[0] != content.number("aircraft_id") {
			return commanderError(400, "INVALID_CONTENT_SET", "Scenario aircraft_id does not match the selected content set")
		}
	}
	data := record(body).project("code title engines comments status published_at valid_until")
	data["airline_id"], data["aircraft_id"], data["created_by"], data["updated_by"] = airline, aircraft[0], u.InternalID, u.InternalID
	if data["status"] == nil || data["status"] == "" {
		data["status"] = "DRAFT"
	}
	if err = scenarioStorageChanges(data); err != nil {
		return err
	}
	row, err := insertTrainingRow(ctx, tx, "scenario", data)
	if err != nil {
		return err
	}
	if body["content_set_id"] != nil {
		if _, err = insertTrainingRow(ctx, tx, "scenario_content_set_label_scenario", record{"label_id": body["set_label_id"], "scenario_id": row["id"]}); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	// The source rechecks active visibility after commit, including a create
	// whose supplied status was ARCHIVED. Preserve the persisted write on 404.
	if _, err = scenarioGet(ctx, s.Auth.DB, row["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	return s.writeEditorScenario(ctx, w, row.number("id"), 201)
}

func (s *Service) updateEditorScenario(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	model := scenarioEditorSchema(false)
	path, body, err := libraryInput(r, &model, "scenario_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(u)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	row, err := scenarioGet(ctx, tx, path["scenario_id"], airline, aircraft, false, false)
	if err != nil {
		return err
	}
	if body.Has("aircraft_id") {
		ids, err := libraryAircraft(ctx, tx, u, body["aircraft_id"], true, false)
		if err != nil {
			return err
		}
		body["aircraft_id"] = ids[0]
	}
	data := record(body)
	data["updated_by"] = u.InternalID
	if err = scenarioStorageChanges(data); err != nil {
		return err
	}
	for _, field := range []string{"published_at", "valid_until"} {
		if value, ok := data[field].(time.Time); ok {
			if old, err := time.Parse(time.RFC3339Nano, row.text(field)); err == nil && old.Equal(value) {
				delete(data, field)
			}
		}
	}
	if err = libraryUpdate(ctx, tx, "scenario", row, data); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if _, err = scenarioGet(ctx, s.Auth.DB, row["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	return s.writeEditorScenario(ctx, w, row.number("id"), 200)
}
