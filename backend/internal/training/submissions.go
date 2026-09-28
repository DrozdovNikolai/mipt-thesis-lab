package training

import (
	"context"
	"errors"
	"net/http"
	"regexp"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func submitFinalizeInput(o platform.Object, id int64) platform.Object {
	result := platform.Object{"training_id": id, "comment_contract_version": o["comment_contract_version"]}
	if o["runtime_seal"] == nil {
		result["cm1"] = o["cm1"]
		result["cm2"] = o["cm2"]
		return result
	}
	blocks := append([]any{}, o["assessments"].([]any)...)
	sort.Slice(blocks, func(i, j int) bool {
		return blocks[i].(platform.Object).Int("assessment_id") < blocks[j].(platform.Object).Int("assessment_id")
	})
	if len(blocks) > 0 {
		result["cm1"] = blocks[0]
	}
	if len(blocks) > 1 {
		result["cm2"] = blocks[1]
	}
	return result
}
func legacySubmitKey(id int64, o platform.Object) (string, error) {
	if key := o.String("idempotency_key"); key != "" {
		return key, nil
	}
	projection := schemaWireObject(o, submitSchema)
	delete(projection, "speechFinishManagedByClient")
	projection["trainingId"] = id
	return canonical.SHA256(projection)
}
func committedSubmitResponse(ctx context.Context, db runtimeDB, id int64) (map[string]any, error) {
	t, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if err != nil {
		return nil, err
	}
	var submitted any
	if t["submitted_at"] != nil {
		parsed, err := time.Parse(time.RFC3339Nano, t.text("submitted_at"))
		if err != nil {
			return nil, err
		}
		submitted = apiTime(&parsed)
	}
	response := map[string]any{"trainingId": id, "trainingStatus": t["status"], "submissionStatus": submissionWithoutSpeech(t), "submittedAt": submitted, "submissionError": nil, "assessmentsCompleted": t.text("status") == "COMPLETED", "speechSessionId": nil, "speechStatus": nil, "speechExpectedChunks": nil, "speechReviewReady": nil, "speechError": nil, "submitReceipt": nil}
	state, err := queryRecord(ctx, db, `SELECT to_jsonb(s) FROM training_session_crew_state s WHERE training_session_id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return response, nil
	}
	if err != nil {
		return nil, err
	}
	key := state.text("sealed_submit_idempotency_key")
	if submitted != nil && state["sealed_at"] != nil && key == t.text("submit_idempotency_key") && regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(key) {
		response["submitReceipt"] = map[string]any{"version": 1, "trainingId": id, "submissionManifestHash": key, "writerInstanceId": state["writer_instance_id"], "writerEpoch": state["writer_epoch"], "currentEventId": state["current_event_public_id"], "acceptedThroughClientSequence": state["current_writer_sequence"], "serverRevision": state["current_revision"], "sealed": true}
	}
	return response, nil
}

// Compatibility-only lookup: validate the ownership of an old speech reference.
// It cannot schedule work, link sessions, modify chunks or inspect AI outputs.
func validateLegacySpeechReference(ctx context.Context, db runtimeDB, id int64, o platform.Object, user *auth.User) error {
	if o["speech_session_id"] == nil {
		return nil
	}
	var training *int64
	err := db.QueryRow(ctx, `SELECT training_session_id FROM speech_session WHERE id=$1 AND user_id=$2`, o["speech_session_id"], user.InternalID).Scan(&training)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Speech session not found")
	}
	if err != nil {
		return err
	}
	if training != nil && *training != id {
		return platform.Error(409, "Speech session is already linked to another training")
	}
	return nil
}

func (s *Service) submitInTransaction(ctx context.Context, db runtimeDB, id int64, o platform.Object, user *auth.User) error {
	if _, err := getRuntimeTraining(ctx, db, id, user); err != nil {
		return err
	}
	t, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1 FOR UPDATE`, id)
	if err != nil {
		return err
	}
	finalize := submitFinalizeInput(o, id)
	if err = validateCommentCompletion(finalize, t.number("comment_contract_version")); err != nil {
		return err
	}
	seal, _ := o["runtime_seal"].(platform.Object)
	key := o.String("submission_manifest_hash")
	if seal == nil {
		key, err = legacySubmitKey(id, o)
		if err != nil {
			return err
		}
	}
	stateRow, err := queryRecord(ctx, db, `SELECT to_jsonb(s) FROM training_session_crew_state s WHERE training_session_id=$1 FOR UPDATE`, id)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if t["submitted_at"] != nil {
		matches := t.text("submit_idempotency_key") == key
		if seal == nil && o["idempotency_key"] == nil && t["submit_idempotency_key"] == nil {
			matches = true
		}
		if !matches || seal != nil && (stateRow == nil || stateRow.text("sealed_submit_idempotency_key") != key) {
			return runtimeError("RUNTIME_MANIFEST_MISMATCH")
		}
		return persistSubmissionWithoutSpeech(ctx, db, id, false)
	}
	state, err := ensureSubmissionRuntime(ctx, db, t, user)
	if err != nil {
		return err
	}
	if state.SealedAt != nil {
		return runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	var hasSwaps bool
	if err = db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND event_kind='SWAP')`, id).Scan(&hasSwaps); err != nil {
		return err
	}
	if seal != nil {
		commentContract := t.number("comment_contract_version") == 1
		if !state.Entitled && !commentContract {
			return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
		}
		linked, err := queryRecords(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE training_session_id=$1`, id)
		if err != nil {
			return err
		}
		wanted := map[int64]bool{}
		for _, raw := range o["assessments"].([]any) {
			wanted[raw.(platform.Object).Int("assessment_id")] = true
		}
		if len(linked) != 2 {
			return platform.Error(400, "Assessments do not match path training_id")
		}
		for _, a := range linked {
			if !wanted[a.number("id")] {
				return platform.Error(400, "Assessments do not match path training_id")
			}
		}
		if err = s.ingestSubmissionRuntime(ctx, db, &state, seal, user, commentContract); err != nil {
			return err
		}
		projectionStarted := time.Now()
		runs, err := terminalizeSubmissionRuns(ctx, db, state)
		s.Auth.Config.Metrics.Observe("north55_training_runtime_projection_seconds", time.Since(projectionStarted).Seconds())
		if err != nil {
			s.Auth.Config.Metrics.Inc("north55_training_runtime_projection_failures_total", projectionFailureReason(err))
		}
		if err != nil {
			return err
		}
		key, err = verifySubmissionManifest(ctx, db, state, o, runs)
		if err != nil {
			return err
		}
	} else if state.Entitled || hasSwaps {
		return runtimeError("RUNTIME_SEAL_REQUIRED")
	}
	if _, err = db.Exec(ctx, `UPDATE training_session_crew_state SET sealed_at=$2,sealed_submit_idempotency_key=$3,updated_at=now() WHERE training_session_id=$1`, id, time.Now().UTC(), key); err != nil {
		return err
	}
	if seal != nil || len(finalizeBlocks(finalize)) > 0 {
		resolved, err := resolveFinalizeTraining(ctx, db, finalize)
		if err != nil {
			return err
		}
		if resolved != id {
			return platform.Error(400, "Assessments do not match path training_id")
		}
		if _, err = s.finalizeInTransaction(ctx, db, t, finalize, user, false); err != nil {
			return err
		}
	}
	if err = validateLegacySpeechReference(ctx, db, id, o, user); err != nil {
		return err
	}
	if _, err = db.Exec(ctx, `UPDATE training_session SET submit_idempotency_key=$2,updated_at=now() WHERE id=$1`, id, key); err != nil {
		return err
	}
	if err = persistSubmissionWithoutSpeech(ctx, db, id, true); err != nil {
		return err
	}
	_, err = db.Exec(ctx, `UPDATE training_session_draft SET submitted=true,submitted_at=COALESCE(submitted_at,$3),updated_at=CASE WHEN NOT submitted OR submitted_at IS NULL THEN now() ELSE updated_at END WHERE training_session_id=$1 AND user_id=$2`, id, user.InternalID, time.Now().UTC())
	return err
}

func (s *Service) readSubmitStatus(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	if _, err = getRuntimeTraining(r.Context(), s.Auth.DB, id, user); err != nil {
		return err
	}
	response, err := committedSubmitResponse(r.Context(), s.Auth.DB, id)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, response)
	return nil
}
func (s *Service) submitTraining(w http.ResponseWriter, r *http.Request) (resultErr error) {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	o, err := readAssessmentSchema(r, submitSchema)
	if err != nil {
		return err
	}
	if o["runtime_seal"] != nil {
		defer func() {
			outcome := "succeeded"
			if resultErr != nil {
				var domain *platform.APIError
				if errors.As(resultErr, &domain) {
					outcome = domain.Code
				} else {
					outcome = "INTERNAL_ERROR"
				}
			}
			s.Auth.Config.Metrics.Inc("north55_training_runtime_seal_total", outcome)
		}()
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = s.submitInTransaction(ctx, tx, id, o, user); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	response, err := committedSubmitResponse(ctx, s.Auth.DB, id)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, response)
	return nil
}
