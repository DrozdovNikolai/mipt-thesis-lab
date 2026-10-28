// Package datamigration contains explicit, reviewable changes to historical data.
// It is never called by the API process or by a GET request.
package datamigration

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"unicode"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const Version = "no-speech-submission-v2"
const lockKey int64 = 550015092026

type Change struct {
	ID      int64           `json:"trainingId"`
	Target  string          `json:"targetStatus,omitempty"`
	Blocked []string        `json:"blocked,omitempty"`
	Before  json.RawMessage `json:"before"`
	Context json.RawMessage `json:"context"`
}
type Report struct {
	Version     string   `json:"version"`
	TrainingIDs []int64  `json:"trainingIds"`
	PlanSHA256  string   `json:"planSha256"`
	Eligible    int      `json:"eligible"`
	Blocked     int      `json:"blocked"`
	Changes     []Change `json:"changes"`
}
type Result struct {
	Version  string    `json:"version"`
	RunID    uuid.UUID `json:"runId"`
	Action   string    `json:"action"`
	IDs      []int64   `json:"trainingIds"`
	Repeated bool      `json:"repeated"`
}

const contextSQL = `jsonb_build_object(
 'assessments',COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id) FROM crew_member_assessment a WHERE a.training_session_id=t.id),'[]'::jsonb),
 'crew_state',(SELECT to_jsonb(s) FROM training_session_crew_state s WHERE s.training_session_id=t.id),
 'runtime_artifacts',jsonb_build_object(
   'crew_events',(SELECT count(*) FROM training_session_crew_assignment_event e WHERE e.training_session_id=t.id),
   'exercise_runs',(SELECT count(*) FROM training_session_exercise_run e WHERE e.training_session_id=t.id),
   'crew_segments',(SELECT count(*) FROM training_session_exercise_crew_segment e WHERE e.training_session_id=t.id)),
 'runtime_rows',jsonb_build_object(
   'crew_events',COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM training_session_crew_assignment_event e WHERE e.training_session_id=t.id),'[]'::jsonb),
   'exercise_runs',COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.exercise_session_key) FROM training_session_exercise_run e WHERE e.training_session_id=t.id),'[]'::jsonb),
   'crew_segments',COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM training_session_exercise_crew_segment e WHERE e.training_session_id=t.id),'[]'::jsonb)),
 'speech',(SELECT to_jsonb(s) FROM speech_session s WHERE s.training_session_id=t.id AND s.user_id=t.instructor_id ORDER BY s.created_at DESC,s.id DESC LIMIT 1))`

type trainingRow struct {
	Status           string  `json:"status"`
	SubmissionStatus string  `json:"submission_status"`
	SubmissionError  *string `json:"submission_error"`
	SubmittedAt      *string `json:"submitted_at"`
	CompletedAt      *string `json:"completed_at"`
	Key              *string `json:"submit_idempotency_key"`
}
type rowContext struct {
	RuntimeArtifacts struct {
		CrewEvents   int64 `json:"crew_events"`
		ExerciseRuns int64 `json:"exercise_runs"`
		CrewSegments int64 `json:"crew_segments"`
	} `json:"runtime_artifacts"`
	Assessments []struct {
		ID      int64   `json:"id"`
		UserID  *int64  `json:"user_id"`
		Role    string  `json:"training_role"`
		Summary *string `json:"summary"`
		Result  *bool   `json:"result"`
	} `json:"assessments"`
	State *struct {
		CapabilityVersion int64   `json:"capability_version"`
		SealedAt          *string `json:"sealed_at"`
		Key               *string `json:"sealed_submit_idempotency_key"`
	} `json:"crew_state"`
	Speech *struct {
		Status string  `json:"status"`
		Error  *string `json:"error"`
	} `json:"speech"`
}

func sameString(a, b *string) bool { return a == nil && b == nil || a != nil && b != nil && *a == *b }
func pythonSpace(r rune) bool      { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }

func classify(change *Change) error {
	var t trainingRow
	var c rowContext
	if err := json.Unmarshal(change.Before, &t); err != nil {
		return err
	}
	if err := json.Unmarshal(change.Context, &c); err != nil {
		return err
	}
	reject := func(reason string) { change.Blocked = append(change.Blocked, reason) }
	if t.SubmittedAt == nil {
		reject("missing_submitted_at")
	}
	if t.Status != "COMPLETED" && t.Status != "IN_PROGRESS" {
		reject("unsupported_training_status")
	}
	if c.Speech == nil {
		reject("missing_owned_speech_session")
	} else if t.SubmissionStatus == "ERROR" {
		expected := "Speech processing failed"
		if c.Speech.Error != nil && *c.Speech.Error != "" {
			expected = *c.Speech.Error
		}
		verified := c.Speech.Status == "error" && t.SubmissionError != nil && *t.SubmissionError == expected
		enqueue := t.SubmissionError != nil && *t.SubmissionError == "Failed to enqueue speech finalization"
		if !verified && !enqueue {
			reject("unverified_error_origin")
		}
	}
	roles := map[string]bool{}
	users := map[int64]bool{}
	completed := 0
	for _, a := range c.Assessments {
		role := strings.ToLower(a.Role)
		roles[role] = true
		if a.UserID != nil {
			users[*a.UserID] = true
		}
		if a.Summary != nil && strings.TrimFunc(*a.Summary, pythonSpace) != "" && a.Result != nil {
			completed++
		}
	}
	if len(c.Assessments) != 2 || !roles["cm1"] || !roles["cm2"] || len(users) != 2 {
		reject("invalid_assessment_participants")
	}
	if t.Status == "COMPLETED" {
		if completed != 2 {
			reject("completed_training_has_incomplete_assessments")
		}
		if t.CompletedAt == nil {
			reject("missing_completed_at")
		}
		change.Target = "COMPLETED"
	} else if t.Status == "IN_PROGRESS" {
		if completed == 2 || t.CompletedAt != nil {
			reject("inconsistent_in_progress_training")
		}
		change.Target = "WAITING_ASSESSMENTS"
	}
	// Historical records may predate runtime entirely; any existing seal/key must
	// remain a coherent receipt, and is never synthesized by this migration.
	if c.State != nil {
		if c.State.CapabilityVersion >= 1 {
			valid := t.Key != nil && len(*t.Key) == 64
			if valid {
				for _, char := range *t.Key {
					if !(char >= '0' && char <= '9' || char >= 'a' && char <= 'f') {
						valid = false
						break
					}
				}
			}
			if !valid {
				reject("runtime_submission_receipt_missing")
			}
		}
		if c.State.SealedAt == nil {
			reject("submitted_runtime_is_unsealed")
		}
		if !sameString(t.Key, c.State.Key) {
			reject("submission_receipt_key_mismatch")
		}
	} else if c.RuntimeArtifacts.CrewEvents > 0 || c.RuntimeArtifacts.ExerciseRuns > 0 || c.RuntimeArtifacts.CrewSegments > 0 {
		// Legacy submissions can have an explicit/implicit key before runtime
		// existed. A detached runtime graph is evidence of missing state.
		reject("runtime_artifacts_without_state")
	}
	if len(change.Blocked) > 0 {
		change.Target = ""
	}
	return nil
}

func normalizeScope(ids []int64) ([]int64, error) {
	scope := append([]int64{}, ids...)
	slices.Sort(scope)
	for i, id := range scope {
		if id <= 0 || i > 0 && id == scope[i-1] {
			return nil, errors.New("training IDs must be positive and unique")
		}
	}
	return scope, nil
}

func collect(ctx context.Context, tx pgx.Tx, scope []int64) (Report, error) {
	report := Report{Version: Version, TrainingIDs: scope, Changes: []Change{}}
	if len(scope) > 0 {
		rows, err := tx.Query(ctx, `SELECT id FROM training_session WHERE id=ANY($1::bigint[]) ORDER BY id FOR UPDATE`, scope)
		if err != nil {
			return report, err
		}
		found := []int64{}
		for rows.Next() {
			var id int64
			if err = rows.Scan(&id); err != nil {
				rows.Close()
				return report, err
			}
			found = append(found, id)
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return report, err
		}
		if !slices.Equal(found, scope) {
			return report, errors.New("one or more selected trainings do not exist")
		}
	}
	rows, err := tx.Query(ctx, `SELECT t.id,to_jsonb(t),`+contextSQL+` FROM training_session t WHERE t.submission_status IN ('WAITING_SPEECH','ERROR') AND (cardinality($1::bigint[])=0 OR t.id=ANY($1::bigint[])) ORDER BY t.id FOR UPDATE OF t`, scope)
	if err != nil {
		return report, err
	}
	for rows.Next() {
		var c Change
		if err = rows.Scan(&c.ID, &c.Before, &c.Context); err != nil {
			rows.Close()
			return report, err
		}
		if err = classify(&c); err != nil {
			rows.Close()
			return report, err
		}
		if len(c.Blocked) > 0 {
			report.Blocked++
		} else {
			report.Eligible++
		}
		report.Changes = append(report.Changes, c)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return report, err
	}
	raw, err := json.Marshal(struct {
		Version     string   `json:"version"`
		TrainingIDs []int64  `json:"trainingIds"`
		Changes     []Change `json:"changes"`
	}{Version, scope, report.Changes})
	if err != nil {
		return report, err
	}
	sum := sha256.Sum256(raw)
	report.PlanSHA256 = hex.EncodeToString(sum[:])
	return report, nil
}

func begin(ctx context.Context, db *pgxpool.Pool) (pgx.Tx, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1)`, lockKey); err != nil {
		tx.Rollback(ctx)
		return nil, err
	}
	return tx, nil
}

func Plan(ctx context.Context, db *pgxpool.Pool) (Report, error) {
	return PlanForTrainings(ctx, db, nil)
}

func PlanForTrainings(ctx context.Context, db *pgxpool.Pool, ids []int64) (Report, error) {
	scope, err := normalizeScope(ids)
	if err != nil {
		return Report{}, err
	}
	tx, err := begin(ctx, db)
	if err != nil {
		return Report{}, err
	}
	defer tx.Rollback(ctx)
	return collect(ctx, tx, scope)
}

func lockContext(ctx context.Context, tx pgx.Tx, id int64) error {
	for _, query := range []string{
		`SELECT training_session_id FROM training_session_crew_state WHERE training_session_id=$1 FOR UPDATE`,
		`SELECT id FROM crew_member_assessment WHERE training_session_id=$1 ORDER BY id FOR UPDATE`,
		`SELECT id FROM speech_session WHERE training_session_id=$1 ORDER BY id FOR UPDATE`,
		`SELECT id FROM training_session_crew_assignment_event WHERE training_session_id=$1 ORDER BY id FOR UPDATE`,
		`SELECT exercise_session_key FROM training_session_exercise_run WHERE training_session_id=$1 ORDER BY exercise_session_key FOR UPDATE`,
		`SELECT id FROM training_session_exercise_crew_segment WHERE training_session_id=$1 ORDER BY id FOR UPDATE`,
	} {
		if _, err := tx.Exec(ctx, query, id); err != nil {
			return err
		}
	}
	return nil
}

const ledgerDDL = `CREATE TABLE IF NOT EXISTS north55_submission_status_runs (
 run_id uuid PRIMARY KEY,version text NOT NULL,plan_sha256 text NOT NULL,
 applied_at timestamptz NOT NULL DEFAULT now(),rolled_back_at timestamptz,
 training_ids bigint[] NOT NULL DEFAULT '{}'::bigint[]);
 ALTER TABLE north55_submission_status_runs ADD COLUMN IF NOT EXISTS training_ids bigint[] NOT NULL DEFAULT '{}'::bigint[];
 CREATE TABLE IF NOT EXISTS north55_submission_status_changes (
 run_id uuid NOT NULL REFERENCES north55_submission_status_runs(run_id),
 training_id bigint NOT NULL,before_row jsonb NOT NULL,after_row jsonb NOT NULL,
 source_context jsonb NOT NULL,PRIMARY KEY(run_id,training_id))`
