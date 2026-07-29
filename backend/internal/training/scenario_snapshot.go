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
