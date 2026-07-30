package training

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"sort"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func scenarioSnapshotError(code, message string, extra map[string]any) error {
	return &platform.APIError{Status: 400, Code: code, Message: message, Extra: extra}
}

func scenarioInteger(value any) *big.Int {
	n, _ := new(big.Int).SetString(fmt.Sprint(value), 10)
	return n
}

// FastAPI reports path, query and body details in that order. Malformed JSON
// and uncaught before-validator errors retain their earlier precedence.
func scenarioSnapshotInput(r *http.Request) (platform.Object, platform.Object, platform.Object, error) {
	path, body, bodyErr := scenarioContentInput(r, func(order libraryJSONOrder, fatal *error) platform.Schema {
		model := scenarioSnapshotSchema(order, fatal)
		return platform.Schema{Fields: []platform.Field{{Name: "snapshot", Kind: "object", Required: true, Schema: &model}}}
	})
	query, queryErr := platform.QueryObject(r.URL.Query(), platform.Field{Name: "allow_missing_ids", Alias: "allowMissingIds", Kind: "boolean", Default: false}, platform.Field{Name: "expected_version", Alias: "expectedVersion", Kind: "integer", Nullable: true, AllowBigInteger: true})
	if queryErr == nil {
		return path, body, query, bodyErr
	}
	if bodyErr == nil {
		return path, body, query, queryErr
	}
	var b, q *platform.APIError
	if !errors.As(bodyErr, &b) || b.Code != "VALIDATION_ERROR" || !errors.As(queryErr, &q) {
		return path, body, query, bodyErr
	}
	details := b.Extra["details"].([]any)
	for _, raw := range details {
		if libraryRecord(raw).text("type") == "json_invalid" {
			return path, body, query, bodyErr
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
	return path, body, query, b
}

type scenarioSnapshotIndex struct {
	ids  map[string]record
	uids map[string]record
}

func newScenarioSnapshotIndex() scenarioSnapshotIndex {
	return scenarioSnapshotIndex{map[string]record{}, map[string]record{}}
}
func (index scenarioSnapshotIndex) add(row record) {
	index.ids[fmt.Sprint(row["id"])] = row
	index.uids[row.text("client_uid")] = row
}
func (index scenarioSnapshotIndex) match(payload record) record {
	if uid := payload.text("client_uid"); uid != "" && index.uids[uid] != nil {
		return index.uids[uid]
	}
	if scenarioInteger(payload["id"]).Sign() > 0 {
		return index.ids[fmt.Sprint(payload["id"])]
	}
	return nil
}

func scenarioValidateSnapshotIDs(modules, exercises []record, oldModules, oldExercises scenarioSnapshotIndex, allowMissing bool) error {
	for _, check := range []struct {
		rows                 []record
		field, code, message string
		truthy               bool
	}{
		{modules, "id", "DUPLICATE_MODULE_IDS", "Snapshot contains duplicate module ids", false},
		{exercises, "id", "DUPLICATE_EXERCISE_IDS", "Snapshot contains duplicate exercise ids", false},
		{modules, "client_uid", "DUPLICATE_MODULE_UIDS", "Snapshot contains duplicate module client_uid", true},
		{exercises, "client_uid", "DUPLICATE_EXERCISE_UIDS", "Snapshot contains duplicate exercise client_uid", true},
	} {
		seen := map[string]bool{}
		for _, row := range check.rows {
			if check.truthy && row.text(check.field) == "" {
				continue
			}
			key := fmt.Sprint(row[check.field])
			if seen[key] {
				return scenarioSnapshotError(check.code, check.message, nil)
			}
			seen[key] = true
		}
	}
	if allowMissing {
		return nil
	}
	for _, check := range []struct {
		rows               []record
		index              scenarioSnapshotIndex
		code, message, key string
	}{
		{modules, oldModules, "INVALID_MODULE_IDS", "Snapshot references unknown module id(s)", "module_ids"},
		{exercises, oldExercises, "INVALID_EXERCISE_IDS", "Snapshot references unknown exercise id(s)", "exercise_ids"},
	} {
		ids := []any{}
		for _, row := range check.rows {
			if scenarioInteger(row["id"]).Sign() > 0 && check.index.match(row) == nil {
				ids = append(ids, row["id"])
			}
		}
		if len(ids) > 0 {
			sort.Slice(ids, func(i, j int) bool { return scenarioInteger(ids[i]).Cmp(scenarioInteger(ids[j])) < 0 })
			return scenarioSnapshotError(check.code, check.message, map[string]any{check.key: ids})
		}
	}
	return nil
}

func scenarioSnapshotDayStarts(modules []record) map[string]bool {
	ordered := append([]record{}, modules...)
	sort.Slice(ordered, func(i, j int) bool {
		cmp := scenarioInteger(ordered[i]["order_index"]).Cmp(scenarioInteger(ordered[j]["order_index"]))
		if cmp == 0 {
			return scenarioInteger(ordered[i]["id"]).Cmp(scenarioInteger(ordered[j]["id"])) < 0
		}
		return cmp < 0
	})
	starts := map[string]bool{}
	previous := big.NewInt(1)
	for i, module := range ordered {
		day := previous
		if i > 0 && module["day_index"] != nil {
			incoming := scenarioInteger(module["day_index"])
			if incoming.Cmp(previous) > 0 {
				day = incoming
			}
		}
		starts[fmt.Sprint(module["id"])] = i > 0 && day.Cmp(previous) > 0
		previous = day
	}
	return starts
}

func (s *Service) applyScenarioSnapshot(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, query, err := scenarioSnapshotInput(r)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	result, err := s.saveScenarioSnapshot(ctx, tx, user, scenarioSnapshotCommand{
		ScenarioID: path["scenario_id"], Snapshot: libraryRecord(body["snapshot"]),
		ExpectedVersion: query["expected_version"], AllowMissing: query.Bool("allow_missing_ids"),
		ClientSessionID: r.Header.Get("X-Client-Session-Id"),
	})
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(result))
	return nil
}

type scenarioSnapshotCommand struct {
	ScenarioID      any
	Snapshot        record
	ExpectedVersion any
	AllowMissing    bool
	ClientSessionID string
}

// saveScenarioSnapshot commits the supplied content transaction, cleans removed
// media, then reloads and validates the persisted snapshot. The caller rolls the
// transaction back on failure; errors after commit retain the saved content.
func (s *Service) saveScenarioSnapshot(ctx context.Context, tx pgx.Tx, user *auth.User, command scenarioSnapshotCommand) (record, error) {
	scenario, err := s.revisionScenario(ctx, tx, user, command.ScenarioID, false)
	if err != nil {
		return nil, err
	}
	id := scenario.number("id")
	graph, err := loadSourceScenario(ctx, tx, id)
	if err != nil {
		return nil, err
	}
	sets, err := queryRecords(ctx, tx, `SELECT jsonb_build_object('id',l.content_set_id) FROM scenario_content_set_label l JOIN scenario_content_set_label_scenario x ON x.label_id=l.id WHERE x.scenario_id=$1`, id)
	if err != nil {
		return nil, err
	}
	client := command.ClientSessionID
	if client == "" {
		return nil, scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required for snapshot writes", nil)
	}
	if err = s.ensureScenarioContentLock(ctx, tx, id, user, client); err != nil {
		return nil, err
	}
	if command.ExpectedVersion == nil {
		return nil, scenarioSnapshotError("EXPECTED_VERSION_REQUIRED", "expected_version query parameter is required for snapshot writes", nil)
	}
	var version int64
	err = tx.QueryRow(ctx, `UPDATE scenario SET content_version=content_version+1,updated_by=$2,updated_at=now() WHERE id=$1 AND content_version=$3 AND deleted_at IS NULL RETURNING content_version`, id, user.InternalID, command.ExpectedVersion).Scan(&version)
	if errors.Is(err, pgx.ErrNoRows) {
		err = tx.QueryRow(ctx, `SELECT content_version FROM scenario WHERE id=$1 AND deleted_at IS NULL`, id).Scan(&version)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, platform.Error(404, "Scenario not found")
		}
		if err != nil {
			return nil, err
		}
		return nil, &platform.APIError{Status: 409, Code: "SCENARIO_VERSION_CONFLICT", Message: "Scenario was modified by another user", Extra: map[string]any{"current_version": version}}
	}
	if err != nil {
		return nil, err
	}
	oldModules, oldExercises := newScenarioSnapshotIndex(), newScenarioSnapshotIndex()
	for _, module := range graph.Modules {
		oldModules.add(module.Row)
		for _, exercise := range module.Exercises {
			oldExercises.add(exercise.Row)
		}
	}
	modules, exercises := []record{}, []record{}
	for _, raw := range command.Snapshot["modules"].([]any) {
		module := libraryRecord(raw)
		modules = append(modules, module)
		for _, raw := range module["exercises"].([]any) {
			exercises = append(exercises, libraryRecord(raw))
		}
	}
	if err = scenarioValidateSnapshotIDs(modules, exercises, oldModules, oldExercises, command.AllowMissing); err != nil {
		return nil, err
	}
	elementIDs := []any{}
	for _, exercise := range exercises {
		for _, raw := range exercise["elements"].([]any) {
			elementIDs = append(elementIDs, libraryRecord(raw)["element_id"])
		}
	}
	airline, aircraft := scenario.number("airline_id"), scenario.number("aircraft_id")
	if err = libraryValidateBlockElementIDs(ctx, tx, airline, []int64{aircraft}, elementIDs); err != nil {
		return nil, err
	}
	moduleMap, exerciseMap := map[string]int64{}, map[string]int64{}
	keepModules, keepExercises := []int64{}, []int64{}
	starts, dayStarts := scenarioSnapshotDayStarts(modules), map[int64]bool{}
	for _, payload := range modules {
		if column := payload["content_subcolumn_id"]; column != nil {
			row, err := libraryFind(ctx, tx, "scenario_content_subcolumn", column)
			if err != nil {
				return nil, err
			}
			valid := false
			for _, set := range sets {
				valid = valid || (row != nil && row.number("content_set_id") == set.number("id"))
			}
			if !valid {
				return nil, scenarioSnapshotError("INVALID_SUBCOLUMN", "Subcolumn does not belong to scenario's content sets", nil)
			}
		}
		module := oldModules.match(payload)
		data := payload.project("order_index duration_minutes content_subcolumn_id")
		if module == nil {
			data["scenario_id"] = id
			data["client_uid"] = payload.text("client_uid")
			if data["client_uid"] == "" {
				data["client_uid"] = uuid.NewString()
			}
			module, err = insertTrainingRow(ctx, tx, "module", data)
		} else {
			err = scenarioUpdateRow(ctx, tx, "module", module, data)
		}
		if err != nil {
			return nil, err
		}
		moduleID := module.number("id")
		if fmt.Sprint(payload["id"]) != fmt.Sprint(moduleID) {
			moduleMap[fmt.Sprint(payload["id"])] = moduleID
		}
		if !libraryContains(keepModules, moduleID) {
			keepModules = append(keepModules, moduleID)
		}
		dayStarts[moduleID] = starts[fmt.Sprint(payload["id"])]
		for _, raw := range payload["exercises"].([]any) {
			ep := libraryRecord(raw)
			if err = scenarioKindPayload(ep); err != nil {
				return nil, err
			}
			exercise := oldExercises.match(ep)
			data := ep.project("kind order_index duration_minutes crew_member_number")
			data["module_id"] = moduleID
			if exercise == nil {
				data["client_uid"] = ep.text("client_uid")
				if data["client_uid"] == "" {
					data["client_uid"] = uuid.NewString()
				}
				exercise, err = insertTrainingRow(ctx, tx, "exercise", data)
			} else {
				err = scenarioUpdateRow(ctx, tx, "exercise", exercise, data)
			}
			if err != nil {
				return nil, err
			}
			exerciseID := exercise.number("id")
			if fmt.Sprint(ep["id"]) != fmt.Sprint(exerciseID) {
				exerciseMap[fmt.Sprint(ep["id"])] = exerciseID
			}
			if err = scenarioReplaceExerciseContent(ctx, tx, exercise, ep, airline, aircraft); err != nil {
				return nil, err
			}
			if !libraryContains(keepExercises, exerciseID) {
				keepExercises = append(keepExercises, exerciseID)
			}
		}
	}
	deleted := []int64{}
	for _, exercise := range oldExercises.ids {
		if !libraryContains(keepExercises, exercise.number("id")) {
			deleted = append(deleted, exercise.number("id"))
		}
	}
	sort.Slice(deleted, func(i, j int) bool { return deleted[i] < deleted[j] })
	media, params, err := scenarioCollectDeletedMedia(ctx, tx, deleted)
	if err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM exercise WHERE module_id=ANY($1::bigint[]) AND NOT(id=ANY($2::bigint[]))`, keepModules, keepExercises); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM module WHERE scenario_id=$1 AND NOT(id=ANY($2::bigint[]))`, id, keepModules); err != nil {
		return nil, err
	}
	if err = scenarioSyncDays(ctx, tx, id, dayStarts, keepModules); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM exercise_param WHERE id=ANY($1::bigint[])`, params); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if err = s.scenarioDeleteUnreferencedMedia(ctx, media); err != nil {
		return nil, err
	}
	if _, err = s.revisionScenario(ctx, s.Auth.DB, user, id, false); err != nil {
		return nil, err
	}
	graph, err = loadSourceScenario(ctx, s.Auth.DB, id)
	if err != nil {
		return nil, err
	}
	snapshot, err := validatedScenarioSnapshot(graph)
	if err != nil {
		return nil, err
	}
	return record{"scenario_id": id, "content_version": version, "snapshot": snapshot, "module_id_map": moduleMap, "exercise_id_map": exerciseMap}, nil
}

// Both snapshot writes and exercise duplication validate the entire persisted
// editor snapshot after commit. Invalid legacy content elsewhere in the scenario
// can therefore fail the response without rolling back the completed mutation.
func validatedScenarioSnapshot(graph sourceScenario) (map[string]any, error) {
	snapshot, err := scenarioRevisionPayload(graph)
	if err != nil {
		return nil, err
	}
	// Validate the persisted response model, including defaults and string limits.
	raw, err := json.Marshal(snapshot)
	if err != nil {
		return nil, err
	}
	var decoded any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err = decoder.Decode(&decoded); err != nil {
		return nil, err
	}
	var fatal error
	model := scenarioSnapshotSchema(nil, &fatal)
	value, err := platform.ValidateObject(decoded, nil, model)
	if err != nil || fatal != nil {
		return nil, fmt.Errorf("invalid persisted scenario snapshot: %v %v", err, fatal)
	}
	return scenarioModelDefaults(value, model), nil
}
