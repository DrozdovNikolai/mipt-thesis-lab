package training

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

// A content write renews the edit lock in the same transaction as the graph.
// Contract/validation failures therefore roll back the renewal as well.
func (s *Service) ensureScenarioContentLock(ctx context.Context, db runtimeDB, scenarioID any, user *auth.User, client string) error {
	if err := lockScenarioSnapshotSource(ctx, db, scenarioID, true); err != nil {
		return err
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	var id int64
	err := db.QueryRow(ctx, `INSERT INTO scenario_edit_lock(scenario_id,user_id,client_session_id,expires_at) VALUES($1,$2,$3,$4)
ON CONFLICT(scenario_id) DO UPDATE SET user_id=EXCLUDED.user_id,client_session_id=EXCLUDED.client_session_id,expires_at=EXCLUDED.expires_at,updated_at=now()
WHERE scenario_edit_lock.expires_at<=$5 OR (scenario_edit_lock.user_id=$2 AND scenario_edit_lock.client_session_id=$3) RETURNING id`, scenarioID, user.InternalID, client, now.Add(s.Auth.Config.ScenarioLockTTL), now).Scan(&id)
	if !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	lock, err := scenarioLockRow(ctx, db, scenarioID, false)
	if err != nil {
		return err
	}
	value, err := scenarioLockDTO(ctx, db, scenarioID, lock, now, client, user)
	if err != nil {
		return err
	}
	return &platform.APIError{Status: 423, Code: "SCENARIO_LOCKED", Message: "Scenario is currently being edited", Extra: map[string]any{"lock": map[string]any(value)}}
}

func scenarioKindPayload(data record) error {
	kind := data.text("kind")
	if kind == "standard" {
		return nil
	}
	for _, field := range []string{"crew_member_number", "elements", "params", "competence_ids"} {
		invalid := data[field] != nil
		if field == "crew_member_number" && kind == "individual" {
			invalid = false
		}
		if field == "elements" || field == "competence_ids" {
			values, _ := data[field].([]any)
			invalid = len(values) > 0
		}
		if invalid {
			return platform.Error(400, fmt.Sprintf("Exercise kind '%s' does not allow %s", kind, field))
		}
	}
	return nil
}

// Keep the in-memory identity map current, including repeated UID/ID aliases.
func scenarioUpdateRow(ctx context.Context, db runtimeDB, table string, row, data record) error {
	if err := libraryUpdate(ctx, db, table, row, data); err != nil {
		return err
	}
	for key, value := range data {
		row[key] = value
	}
	return nil
}

const scenarioParamFields = "original_tl_id destination_tl_id intensity zfw_t guidance_doc guidance_plain_text"

func scenarioReplaceParams(ctx context.Context, db runtimeDB, exercise, payload record) error {
	old, err := libraryFind(ctx, db, "exercise_param", exercise["exercise_param_id"])
	if err != nil {
		return err
	}
	ids := []int64{}
	for _, key := range []string{"original_tl_id", "destination_tl_id"} {
		if id := old.number(key); id != 0 && !libraryContains(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) > 0 {
		if _, err = db.Exec(ctx, `DELETE FROM take_off_landing_param WHERE id=ANY($1::bigint[])`, ids); err != nil {
			return err
		}
	}
	if payload == nil {
		if old == nil {
			return nil
		}
		if err = scenarioUpdateRow(ctx, db, "exercise", exercise, record{"exercise_param_id": nil}); err != nil {
			return err
		}
		_, err = db.Exec(ctx, `DELETE FROM exercise_param WHERE id=$1`, old["id"])
		return err
	}
	if old == nil {
		old, err = insertTrainingRow(ctx, db, "exercise_param", record{}.project(scenarioParamFields))
		if err != nil {
			return err
		}
		if err = scenarioUpdateRow(ctx, db, "exercise", exercise, record{"exercise_param_id": old["id"]}); err != nil {
			return err
		}
	}
	if payload["original_tl"] != nil || payload["destination_tl"] != nil {
		if err = scenarioUpdateRow(ctx, db, "exercise_param", old, record{}.project(scenarioParamFields)); err != nil {
			return err
		}
	}
	data, err := libraryNewBlockParams(ctx, db, payload)
	if err != nil {
		return err
	}
	if jsonEqual(old["guidance_doc"], data["guidance_doc"]) {
		data["guidance_doc"] = old["guidance_doc"]
	}
	return scenarioUpdateRow(ctx, db, "exercise_param", old, data.project(scenarioParamFields))
}

func scenarioReplaceElements(ctx context.Context, db runtimeDB, exerciseID any, airline, aircraft int64, items []any) error {
	ids := []any{}
	for _, item := range items {
		ids = append(ids, libraryRecord(item)["element_id"])
	}
	if err := libraryValidateBlockElementIDs(ctx, db, airline, []int64{aircraft}, ids); err != nil {
		return err
	}
	if _, err := db.Exec(ctx, `DELETE FROM exercise_element WHERE exercise_id=$1`, exerciseID); err != nil {
		return err
	}
	for _, item := range items {
		data := libraryRecord(item).project("element_id order_index details starting_height ending_height profile_type")
		data["exercise_id"] = exerciseID
		if _, err := insertTrainingRow(ctx, db, "exercise_element", data); err != nil {
			return err
		}
	}
	return nil
}

func scenarioReplaceCompetences(ctx context.Context, db runtimeDB, exerciseID any, airline int64, items []any) error {
	if _, err := db.Exec(ctx, `DELETE FROM exercise_competence WHERE exercise_id=$1`, exerciseID); err != nil {
		return err
	}
	ids := []int64{}
	for _, item := range items {
		id, ok := item.(int64)
		if !ok {
			return fmt.Errorf("competence id exceeds PostgreSQL bigint range")
		}
		if !libraryContains(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	var count int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM competence WHERE airline_id=$1 AND id=ANY($2::bigint[])`, airline, ids).Scan(&count); err != nil {
		return err
	}
	if count != len(ids) {
		return platform.Error(400, "Invalid competence_ids")
	}
	for _, id := range ids {
		if _, err := insertTrainingRow(ctx, db, "exercise_competence", record{"exercise_id": exerciseID, "competence_id": id}); err != nil {
			return err
		}
	}
	return nil
}

func scenarioReplaceExerciseContent(ctx context.Context, db runtimeDB, exercise, payload record, airline, aircraft int64) error {
	standard := payload.text("kind") == "standard"
	if standard {
		if err := scenarioReplaceElements(ctx, db, exercise["id"], airline, aircraft, payload["elements"].([]any)); err != nil {
			return err
		}
	} else {
		for _, table := range []string{"exercise_element", "exercise_competence"} {
			if _, err := db.Exec(ctx, `DELETE FROM `+table+` WHERE exercise_id=$1`, exercise["id"]); err != nil {
				return err
			}
		}
	}
	params := libraryRecord(payload["params"])
	if !standard {
		params = nil
	}
	if err := scenarioReplaceParams(ctx, db, exercise, params); err != nil {
		return err
	}
	if standard {
		return scenarioReplaceCompetences(ctx, db, exercise["id"], airline, payload["competence_ids"].([]any))
	}
	return nil
}

func scenarioSyncDays(ctx context.Context, db runtimeDB, scenarioID any, starts map[int64]bool, kept []int64) error {
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(d) FROM scenario_day_module d WHERE scenario_id=$1`, scenarioID)
	if err != nil {
		return err
	}
	byModule := map[int64]record{}
	for _, row := range rows {
		byModule[row.number("module_id")] = row
	}
	modules, err := queryRecords(ctx, db, `SELECT to_jsonb(m) FROM module m WHERE scenario_id=$1 AND id=ANY($2::bigint[]) ORDER BY order_index,id`, scenarioID, kept)
	if err != nil {
		return err
	}
	day := 1
	for i, module := range modules {
		id := module.number("id")
		if i > 0 && starts[id] {
			day++
		}
		data := record{"day_index": day, "order_index": module["order_index"]}
		if old := byModule[id]; old != nil {
			if err = libraryUpdate(ctx, db, "scenario_day_module", old, data); err != nil {
				return err
			}
		} else {
			data["module_id"], data["scenario_id"] = id, scenarioID
			if _, err = insertTrainingRow(ctx, db, "scenario_day_module", data); err != nil {
				return err
			}
		}
		delete(byModule, id)
	}
	for _, row := range byModule {
		if _, err = db.Exec(ctx, `DELETE FROM scenario_day_module WHERE id=$1`, row["id"]); err != nil {
			return err
		}
	}
	return nil
}
