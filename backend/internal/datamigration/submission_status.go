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

func Apply(ctx context.Context, db *pgxpool.Pool, runID uuid.UUID, expected string) (Result, error) {
	return ApplyForTrainings(ctx, db, runID, expected, nil)
}

func ApplyForTrainings(ctx context.Context, db *pgxpool.Pool, runID uuid.UUID, expected string, ids []int64) (Result, error) {
	result := Result{Version: Version, RunID: runID, Action: "apply", IDs: []int64{}}
	if runID == uuid.Nil || len(expected) != 64 {
		return result, errors.New("apply requires a nonzero run UUID and reviewed plan SHA-256")
	}
	scope, err := normalizeScope(ids)
	if err != nil {
		return result, err
	}
	tx, err := begin(ctx, db)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, ledgerDDL); err != nil {
		return result, err
	}
	var prior, version string
	var priorScope []int64
	var rolledBack bool
	err = tx.QueryRow(ctx, `SELECT version,plan_sha256,rolled_back_at IS NOT NULL,training_ids FROM north55_submission_status_runs WHERE run_id=$1`, runID).Scan(&version, &prior, &rolledBack, &priorScope)
	if err == nil {
		if version != Version || prior != expected || rolledBack || !slices.Equal(priorScope, scope) {
			return result, errors.New("run ID already belongs to a different or rolled-back migration")
		}
		result.IDs, err = verifyStored(ctx, tx, runID, false)
		if err != nil {
			return result, err
		}
		result.Repeated = true
		return result, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return result, err
	}
	report, err := collect(ctx, tx, scope)
	if err != nil {
		return result, err
	}
	if report.PlanSHA256 != expected {
		return result, errors.New("plan changed; review a fresh plan before applying")
	}
	if report.Blocked > 0 {
		return result, fmt.Errorf("plan contains %d inconsistent or unverified rows; no rows changed", report.Blocked)
	}
	if _, err = tx.Exec(ctx, `INSERT INTO north55_submission_status_runs(run_id,version,plan_sha256,training_ids) VALUES($1,$2,$3,$4)`, runID, Version, expected, scope); err != nil {
		return result, err
	}
	for _, c := range report.Changes {
		if err = lockContext(ctx, tx, c.ID); err != nil {
			return result, err
		}
		var after []byte
		err = tx.QueryRow(ctx, `UPDATE training_session t SET submission_status=$2,submission_error=NULL,updated_at=now() WHERE id=$1 AND to_jsonb(t)=$3::jsonb RETURNING to_jsonb(t)`, c.ID, c.Target, []byte(c.Before)).Scan(&after)
		if err != nil {
			return result, err
		}
		_, err = tx.Exec(ctx, `INSERT INTO north55_submission_status_changes(run_id,training_id,before_row,after_row,source_context) VALUES($1,$2,$3::jsonb,$4::jsonb,$5::jsonb)`, runID, c.ID, []byte(c.Before), after, []byte(c.Context))
		if err != nil {
			return result, err
		}
		result.IDs = append(result.IDs, c.ID)
	}
	return result, tx.Commit(ctx)
}

// Compare the whole row and its assessment/runtime/speech context. Rollback may
// never overwrite a legitimate edit made after the migration.
func verifyStored(ctx context.Context, tx pgx.Tx, runID uuid.UUID, before bool) ([]int64, error) {
	field := "after_row"
	if before {
		field = "before_row"
	}
	rows, err := tx.Query(ctx, `SELECT c.training_id,c.`+field+`,c.source_context,to_jsonb(t),CASE WHEN t.id IS NOT NULL THEN `+contextSQL+` END FROM north55_submission_status_changes c LEFT JOIN training_session t ON t.id=c.training_id WHERE c.run_id=$1 ORDER BY c.training_id`, runID)
	if err != nil {
		return nil, err
	}
	ids := []int64{}
	for rows.Next() {
		var id int64
		var wanted, contextBefore, actual, contextAfter []byte
		if err = rows.Scan(&id, &wanted, &contextBefore, &actual, &contextAfter); err != nil {
			rows.Close()
			return nil, err
		}
		if !bytes.Equal(wanted, actual) || !bytes.Equal(contextBefore, contextAfter) {
			rows.Close()
			return nil, fmt.Errorf("training %d or its assessment/runtime/speech context changed; no rows changed", id)
		}
		ids = append(ids, id)
	}
	rows.Close()
	return ids, rows.Err()
}
