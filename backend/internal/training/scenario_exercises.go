package training

import (
	"context"
	"fmt"
	"net/http"

	"github.com/google/uuid"
	"north55/backend/internal/platform"
)

func editorExercise(ctx context.Context, db runtimeDB, id any, airline int64, aircraft []int64) (record, record, record, error) {
	exercise, err := libraryFind(ctx, db, "exercise", id)
	if err != nil {
		return nil, nil, nil, err
	}
	var module, scenario record
	if exercise != nil {
		module, err = libraryFind(ctx, db, "module", exercise["module_id"])
		if err != nil {
			return nil, nil, nil, err
		}
	}
	if module != nil {
		scenario, err = libraryFind(ctx, db, "scenario", module["scenario_id"])
		if err != nil {
			return nil, nil, nil, err
		}
	}
	if scenario == nil || scenario.number("airline_id") != airline || !libraryContains(aircraft, scenario.number("aircraft_id")) {
		return nil, nil, nil, platform.Error(404, "Exercise not found")
	}
	return exercise, module, scenario, nil
}

func (s *Service) editorExerciseResponse(ctx context.Context, id any) (any, error) {
	row, err := libraryFind(ctx, s.Auth.DB, "exercise", id)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, platform.Error(404, "Exercise not found")
	}
	exercise := &sourceExercise{Row: row}
	if err = loadExerciseAssetsMode(ctx, s.Auth.DB, []*sourceExercise{exercise}, false, true); err != nil {
		return nil, err
	}
	value, err := scenarioExerciseDTO(exercise, s.Auth.Config.APIPrefix)
	if err != nil {
		return nil, err
	}
	return commanderWire(value), nil
}

func editorDeleteExerciseError(err error) error {
	if scenarioRevisionIntegrityError(err) {
		return platform.Error(409, "Exercise cannot be deleted because it is referenced by training history")
	}
	return err
}

func (s *Service) writeEditorExercise(w http.ResponseWriter, r *http.Request, action string) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, query, err := editorInput(r, "exercise", action)
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
	var exercise, module, scenario record
	if action == "create" {
		module, scenario, err = editorModule(ctx, tx, body["module_id"], airline, aircraft)
	} else {
		exercise, module, scenario, err = editorExercise(ctx, tx, path["exercise_id"], airline, aircraft)
	}
	if err != nil {
		return err
	}
	data := record{}
	for key, value := range body {
		data[key] = value
	}
	if action != "delete" {
		kind := "standard"
		if action == "update" {
			kind = exercise.text("kind")
		}
		if value, present := body["kind"]; present {
			kind, _ = value.(string)
		}
		if kind == "" {
			kind = "standard"
		}
		data["kind"] = kind
		if err = scenarioKindPayload(data); err != nil {
			return err
		}
		if action == "update" && body["module_id"] != nil && fmt.Sprint(body["module_id"]) != fmt.Sprint(module["id"]) {
			target, targetScenario, e := editorModule(ctx, tx, body["module_id"], airline, aircraft)
			if e != nil {
				if api, ok := e.(*platform.APIError); !ok || api.Status != 404 {
					return e
				}
				return platform.Error(400, "Invalid module_id")
			}
			if targetScenario.number("id") != scenario.number("id") {
				return platform.Error(400, "Invalid module_id")
			}
			data["module_id"] = target["id"]
		}
	}
	if err = s.applyLegacyContentContract(ctx, tx, scenario["id"], user, r.Header.Get("X-Client-Session-Id"), query["expected_version"]); err != nil {
		return err
	}
	media := []record{}
	switch action {
	case "create":
		row := data.project("module_id client_uid kind order_index duration_minutes crew_member_number")
		if row.text("client_uid") == "" {
			row["client_uid"] = uuid.NewString()
		}
		exercise, err = insertTrainingRow(ctx, tx, "exercise", row)
		if err != nil {
			return err
		}
		if err = scenarioReplaceElements(ctx, tx, exercise["id"], airline, scenario.number("aircraft_id"), body["elements"].([]any)); err != nil {
			return err
		}
		if err = scenarioReplaceCompetences(ctx, tx, exercise["id"], airline, body["competence_ids"].([]any)); err != nil {
			return err
		}
		if body["params"] != nil {
			if err = scenarioReplaceParams(ctx, tx, exercise, libraryRecord(body["params"])); err != nil {
				return err
			}
		}
	case "update":
		changes := record{}
		for _, key := range []string{"module_id", "kind", "order_index", "duration_minutes", "crew_member_number"} {
			if _, present := body[key]; present && (key != "module_id" || body[key] != nil) {
				changes[key] = data[key]
			}
		}
		kind := data.text("kind")
		if kind != "standard" && kind != "individual" {
			changes["crew_member_number"] = nil
		}
		if err = scenarioUpdateRow(ctx, tx, "exercise", exercise, changes); err != nil {
			return err
		}
		if kind != "standard" {
			for _, table := range []string{"exercise_element", "exercise_competence"} {
				if _, err = tx.Exec(ctx, `DELETE FROM `+table+` WHERE exercise_id=$1`, exercise["id"]); err != nil {
					return err
				}
			}
			if err = scenarioReplaceParams(ctx, tx, exercise, nil); err != nil {
				return err
			}
		} else {
			if raw, present := body["elements"]; present {
				values, _ := raw.([]any)
				if err = scenarioReplaceElements(ctx, tx, exercise["id"], airline, scenario.number("aircraft_id"), values); err != nil {
					return err
				}
			}
			if raw, present := body["params"]; present {
				if err = scenarioReplaceParams(ctx, tx, exercise, libraryRecord(raw)); err != nil {
					return err
				}
			}
			if raw, present := body["competence_ids"]; present {
				values, _ := raw.([]any)
				if err = scenarioReplaceCompetences(ctx, tx, exercise["id"], airline, values); err != nil {
					return err
				}
			}
		}
	case "delete":
		var params []int64
		media, params, err = scenarioCollectDeletedMedia(ctx, tx, []int64{exercise.number("id")})
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, `DELETE FROM exercise WHERE id=$1`, exercise["id"]); err != nil {
			return editorDeleteExerciseError(err)
		}
		if _, err = tx.Exec(ctx, `DELETE FROM exercise_param WHERE id=ANY($1::bigint[])`, params); err != nil {
			return editorDeleteExerciseError(err)
		}
	}
	if err = tx.Commit(ctx); err != nil {
		if action == "delete" {
			return editorDeleteExerciseError(err)
		}
		return err
	}
	if action == "delete" {
		if err = s.scenarioDeleteUnreferencedMedia(ctx, media); err != nil {
			return editorDeleteExerciseError(err)
		}
		w.WriteHeader(204)
		return nil
	}
	value, err := s.editorExerciseResponse(ctx, exercise["id"])
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
