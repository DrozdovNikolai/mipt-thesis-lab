package datamigration

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func legacyChange(t *testing.T, key *string, artifacts map[string]int64) Change {
	t.Helper()
	before := map[string]any{"status": "COMPLETED", "submission_status": "WAITING_SPEECH", "submitted_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:00Z", "submit_idempotency_key": key}
	context := map[string]any{"speech": map[string]any{"status": "completed"}, "crew_state": nil, "runtime_artifacts": artifacts,
		"assessments": []any{map[string]any{"id": 1, "user_id": 1, "training_role": "cm1", "summary": "Complete", "result": true}, map[string]any{"id": 2, "user_id": 2, "training_role": "cm2", "summary": "Complete", "result": false}}}
	beforeJSON, err := json.Marshal(before)
	if err != nil {
		t.Fatal(err)
	}
	contextJSON, err := json.Marshal(context)
	if err != nil {
		t.Fatal(err)
	}
	return Change{Before: beforeJSON, Context: contextJSON}
}

func TestScopeValidation(t *testing.T) {
	for _, ids := range [][]int64{{0}, {-1}, {5, 5}} {
		if _, err := normalizeScope(ids); err == nil {
			t.Fatalf("invalid scope accepted: %v", ids)
		}
	}
	input := []int64{6, 1, 5}
	got, err := normalizeScope(input)
	if err != nil || !reflect.DeepEqual(got, []int64{1, 5, 6}) || input[0] != 6 {
		t.Fatalf("scope not normalized without changing input: %v, %v", got, err)
	}
	got, err = normalizeScope(nil)
	if err != nil || got == nil || len(got) != 0 {
		t.Fatalf("empty scope must encode as []: %v", err)
	}
}

func TestDeletedTrainingIsBlocked(t *testing.T) {
	change := legacyChange(t, nil, map[string]int64{})
	var before map[string]any
	if err := json.Unmarshal(change.Before, &before); err != nil {
		t.Fatal(err)
	}
	before["status"] = "DELETED"
	var err error
	change.Before, err = json.Marshal(before)
	if err != nil {
		t.Fatal(err)
	}
	if err = classify(&change); err != nil {
		t.Fatal(err)
	}
	if change.Target != "" || !reflect.DeepEqual(change.Blocked, []string{"unsupported_training_status"}) {
		t.Fatalf("deleted training misclassified: %v", change.Blocked)
	}
}

func TestLegacyKeysBeforeRuntime(t *testing.T) {
	explicit, implicit := "legacy-client-key", strings.Repeat("a", 64)
	for _, key := range []*string{nil, &explicit, &implicit} {
		change := legacyChange(t, key, map[string]int64{})
		if err := classify(&change); err != nil {
			t.Fatal(err)
		}
		if len(change.Blocked) != 0 || change.Target != "COMPLETED" {
			t.Fatalf("legitimate legacy key rejected: %v", change.Blocked)
		}
	}
}

func TestDetachedRuntimeBlocksTransition(t *testing.T) {
	key := strings.Repeat("a", 64)
	for _, name := range []string{"crew_events", "exercise_runs", "crew_segments"} {
		for _, candidate := range []*string{nil, &key} {
			change := legacyChange(t, candidate, map[string]int64{name: 1})
			if err := classify(&change); err != nil {
				t.Fatal(err)
			}
			if change.Target != "" || len(change.Blocked) != 1 || change.Blocked[0] != "runtime_artifacts_without_state" {
				t.Fatalf("orphan %s not rejected: %v", name, change.Blocked)
			}
		}
	}
}
