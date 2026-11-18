package training

import (
	"context"
	"net/http"

	"github.com/google/uuid"
	"north55/backend/internal/platform"
)

func (s *Service) registerScenarioContentCRUD(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("POST "+p+"/exercises/{exercise_id}/duplicate", platform.Wrap(s.duplicateEditorExercise))
	for _, entry := range []struct{ method, route, resource, action string }{
		{"POST", "/modules", "module", "create"}, {"PUT", "/modules/{module_id}", "module", "update"}, {"DELETE", "/modules/{module_id}", "module", "delete"},
		{"POST", "/exercises", "exercise", "create"}, {"PUT", "/exercises/{exercise_id}", "exercise", "update"}, {"DELETE", "/exercises/{exercise_id}", "exercise", "delete"},
	} {
		mux.HandleFunc(entry.method+" "+p+entry.route, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			if entry.resource == "module" {
				return s.writeEditorModule(w, r, entry.action)
			}
			return s.writeEditorExercise(w, r, entry.action)
		}))
	}
}

func editorModule(ctx context.Context, db runtimeDB, id any, airline int64, aircraft []int64) (record, record, error) {
	module, err := libraryFind(ctx, db, "module", id)
	if err != nil {
		return nil, nil, err
	}
	var scenario record
	if module != nil {
		scenario, err = libraryFind(ctx, db, "scenario", module["scenario_id"])
		if err != nil {
			return nil, nil, err
		}
	}
	if scenario == nil || scenario.number("airline_id") != airline || !libraryContains(aircraft, scenario.number("aircraft_id")) {
		return nil, nil, platform.Error(404, "Module not found")
	}
	return module, scenario, nil
}

func editorDayMeta(ctx context.Context, db runtimeDB, scenarioID any) (map[int64]int64, map[int64]bool, []int64, error) {
	rows, err := queryRecords(ctx, db, `SELECT jsonb_build_object('id',m.id,'day_index',d.day_index) FROM module m LEFT JOIN scenario_day_module d ON d.module_id=m.id WHERE m.scenario_id=$1 ORDER BY m.order_index,m.id`, scenarioID)
	if err != nil {
		return nil, nil, nil, err
	}
	days, starts, ids := map[int64]int64{}, map[int64]bool{}, []int64{}
	previous := int64(1)
	for i, row := range rows {
		day := max(1, row.number("day_index"))
		if i == 0 {
			day = 1
		}
		day = max(day, previous)
		id := row.number("id")
		days[id], starts[id] = day, i > 0 && day > previous
		ids = append(ids, id)
		previous = day
	}
	return days, starts, ids, nil
}

func editorValidateSubcolumn(ctx context.Context, db runtimeDB, scenarioID, column any) error {
	if column == nil {
		return nil
	}
	var valid bool
	err := db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM scenario_content_subcolumn c JOIN scenario_content_set_label l ON l.content_set_id=c.content_set_id JOIN scenario_content_set_label_scenario x ON x.label_id=l.id WHERE c.id=$1 AND x.scenario_id=$2)`, column, scenarioID).Scan(&valid)
	if err != nil {
		return err
	}
	if !valid {
		return scenarioSnapshotError("INVALID_SUBCOLUMN", "Subcolumn does not belong to scenario's content sets", nil)
	}
	return nil
}

func (s *Service) editorModuleResponse(ctx context.Context, id any) (any, error) {
	row, err := libraryFind(ctx, s.Auth.DB, "module", id)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, platform.Error(404, "Module not found")
	}
	graph, err := loadSourceScenarioMode(ctx, s.Auth.DB, row.number("scenario_id"), true)
	if err != nil {
		return nil, err
	}
	days, starts, _, err := editorDayMeta(ctx, s.Auth.DB, row["scenario_id"])
	if err != nil {
		return nil, err
	}
	for _, module := range graph.Modules {
		if module.Row.number("id") != row.number("id") {
			continue
		}
		value := module.Row.project("id client_uid scenario_id order_index duration_minutes content_subcolumn_id created_at updated_at")
		value["day_index"], value["day_start"], value["content_subcolumn"] = days[row.number("id")], starts[row.number("id")], nil
		if column := module.Row.object("content_subcolumn"); column != nil {
			value["content_subcolumn"] = column.project("id content_set_id name order_index created_at updated_at")
		}
		exercises := []record{}
		for _, exercise := range module.Exercises {
			dto, err := scenarioExerciseDTO(exercise, s.Auth.Config.APIPrefix)
			if err != nil {
				return nil, err
			}
			exercises = append(exercises, dto)
		}
		value["exercises"] = exercises
		return commanderWire(value), nil
	}
	return nil, platform.Error(404, "Module not found")
}

func (s *Service) writeEditorModule(w http.ResponseWriter, r *http.Request, action string) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, query, err := editorInput(r, "module", action)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var module, scenario record
	if action == "create" {
		scenario, err = scenarioGet(ctx, tx, body["scenario_id"], airline, aircraft, false, false)
	} else {
		module, scenario, err = editorModule(ctx, tx, path["module_id"], airline, aircraft)
	}
	if err != nil {
		return err
	}
	if action == "create" {
		if err = editorValidateSubcolumn(ctx, tx, scenario["id"], body["content_subcolumn_id"]); err != nil {
			return err
		}
	}
	_, starts, _, err := editorDayMeta(ctx, tx, scenario["id"])
	if err != nil {
		return err
	}
	if action == "update" {
		if _, present := body["content_subcolumn_id"]; present {
			if err = editorValidateSubcolumn(ctx, tx, scenario["id"], body["content_subcolumn_id"]); err != nil {
				return err
			}
		}
	}
	if err = s.applyLegacyContentContract(ctx, tx, scenario["id"], user, r.Header.Get("X-Client-Session-Id"), query["expected_version"]); err != nil {
		return err
	}
	media := []record{}
	paramIDs := []int64{}
	switch action {
	case "create":
		data := record(body).project("scenario_id client_uid order_index duration_minutes content_subcolumn_id")
		if data.text("client_uid") == "" {
			data["client_uid"] = uuid.NewString()
		}
		module, err = insertTrainingRow(ctx, tx, "module", data)
		if err != nil {
			return err
		}
		starts[module.number("id")] = body.Bool("day_start")
	case "update":
		data := record{}
		for _, key := range []string{"order_index", "duration_minutes", "content_subcolumn_id"} {
			if v, ok := body[key]; ok {
				data[key] = v
			}
		}
		if err = scenarioUpdateRow(ctx, tx, "module", module, data); err != nil {
			return err
		}
		if _, present := body["day_start"]; present {
			starts[module.number("id")] = body.Bool("day_start")
		}
	case "delete":
		rows, err := queryRecords(ctx, tx, `SELECT to_jsonb(e) FROM exercise e WHERE module_id=$1`, module["id"])
		if err != nil {
			return err
		}
		ids := []int64{}
		for _, row := range rows {
			ids = append(ids, row.number("id"))
		}
		media, paramIDs, err = scenarioCollectDeletedMedia(ctx, tx, ids)
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, `DELETE FROM module WHERE id=$1`, module["id"]); err != nil {
			return err
		}
		delete(starts, module.number("id"))
	}
	_, _, kept, err := editorDayMeta(ctx, tx, scenario["id"])
	if err != nil {
		return err
	}
	if err = scenarioSyncDays(ctx, tx, scenario["id"], starts, kept); err != nil {
		return err
	}
	if action == "delete" {
		if _, err = tx.Exec(ctx, `DELETE FROM exercise_param WHERE id=ANY($1::bigint[])`, paramIDs); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if action == "delete" {
		if err = s.scenarioDeleteUnreferencedMedia(ctx, media); err != nil {
			return err
		}
		w.WriteHeader(204)
		return nil
	}
	value, err := s.editorModuleResponse(ctx, module["id"])
	if err != nil {
		return err
	}
	status := 200
	if action == "create" {
		status = 201
	}
	platform.WriteJSON(w, status, value)
	return nil
}
