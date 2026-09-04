package training

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"sort"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func (s *Service) syncRuntime(w http.ResponseWriter, r *http.Request) (resultErr error) {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	// Parse before enforcing the runtime byte limit, matching FastAPI's model validation.
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024*1024+1))
	if err != nil {
		return err
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	o, err := platform.ReadSchema(r, runtimeSyncSchema)
	if err != nil {
		return err
	}
	started := time.Now()
	s.Auth.Config.Metrics.Observe("north55_training_runtime_sync_batch_size", float64(len(o["crew_assignment_events"].([]any))), "events")
	s.Auth.Config.Metrics.Observe("north55_training_runtime_sync_batch_size", float64(len(o["run_snapshots"].([]any))), "runs")
	if r.ContentLength > 1024*1024 || len(raw) > 1024*1024 {
		return runtimeError("RUNTIME_BATCH_TOO_LARGE")
	}
	if value := r.Header.Get("Content-Length"); value != "" {
		length, err := strconv.ParseInt(value, 10, 64)
		if err != nil || length > 1024*1024 {
			return runtimeError("RUNTIME_BATCH_TOO_LARGE")
		}
	}
	reason := "accepted"
	defer func() { s.observeRuntime(started, resultErr, "succeeded", reason) }()
	if !s.Auth.Config.RuntimeWriteEnabled {
		return runtimeError("RUNTIME_WRITE_PAUSED")
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	response, err := s.syncRuntimeInTransaction(ctx, tx, id, o, user)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	// The source returns sealed duplicate acknowledgements before audit emission.
	// Unified sync also omits these records because it invokes the transaction
	// body with commit=False. Only this standalone endpoint emits them.
	if !response["sealed"].(bool) {
		batch := parseRuntimeBatch(o)
		accepted := map[uuid.UUID]eventAck{}
		duplicates := 0
		for _, ack := range response["eventAcks"].([]eventAck) {
			if ack.Status == "ACCEPTED" {
				accepted[ack.ClientEventID] = ack
			} else if ack.Status == "DUPLICATE" {
				duplicates++
			}
		}
		for _, event := range batch.Events {
			if ack, ok := accepted[event.ClientEventID]; ok {
				platform.LogModule("app.audit", r.Context()).Info("Training crew assignment event accepted", "action", "assessment.runtime.crew_event.accepted", "training_id", id, "crew_event_id", event.ClientEventID.String(), "writer_instance_id", batch.Writer.String(), "writer_epoch", batch.Epoch, "server_revision", ack.ServerRevision, "event_scope", event.Scope)
			}
		}
		platform.LogModule("app.audit", r.Context()).Info("Training crew runtime synchronized", "action", "assessment.runtime.sync", "training_id", id, "writer_instance_id", batch.Writer.String(), "writer_epoch", batch.Epoch, "accepted_events", len(accepted), "duplicate_events", duplicates)
	}
	acks := response["eventAcks"].([]eventAck)
	duplicate := len(acks) > 0
	for _, ack := range acks {
		duplicate = duplicate && ack.Status == "DUPLICATE"
	}
	for _, ack := range response["runAcks"].([]runAck) {
		duplicate = duplicate && ack.Status == "DUPLICATE"
	}
	if duplicate {
		reason = "duplicate"
	}
	platform.WriteJSON(w, 200, response)
	return nil
}

// syncRuntimeInTransaction applies the runtime contract without committing.
// The HTTP endpoint and unified sync share this exact transaction body.
func (s *Service) syncRuntimeInTransaction(ctx context.Context, db runtimeDB, id int64, o platform.Object, user *auth.User) (map[string]any, error) {
	if !s.Auth.Config.RuntimeWriteEnabled {
		return nil, runtimeError("RUNTIME_WRITE_PAUSED")
	}
	training, err := getRuntimeTraining(ctx, db, id, user)
	if err != nil {
		return nil, err
	}
	if _, err = db.Exec(ctx, `SELECT id FROM training_session WHERE id=$1 FOR UPDATE`, id); err != nil {
		return nil, err
	}
	state, err := loadRuntimeState(ctx, db, id, true)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if err != nil {
		return nil, err
	}
	if training.Status != "IN_PROGRESS" && state.SealedAt == nil {
		return nil, runtimeError("TRAINING_NOT_IN_PROGRESS")
	}
	if !state.Entitled && training.CommentContractVersion != 1 {
		return nil, runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if state.Entitled && state.Version != 1 {
		return nil, runtimeError("RUNTIME_CAPABILITY_VERSION_UNSUPPORTED")
	}
	if state.Writer != o["writer_instance_id"].(uuid.UUID) || o.CompareInteger("writer_epoch", state.Epoch) != 0 {
		return nil, state.conflict(true)
	}
	if !state.Entitled && training.CommentContractVersion == 1 && len(o["crew_assignment_events"].([]any)) > 0 {
		return nil, runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if o.CompareInteger("base_server_revision", state.Revision) > 0 {
		return nil, state.conflict(false)
	}
	// Epoch equals the stored epoch, and the non-negative revision is bounded
	// above by the stored watermark. Both can now be represented as int64.
	batch := parseRuntimeBatch(o)
	var base uuid.UUID
	err = db.QueryRow(ctx, `SELECT public_id FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND server_revision=$2`, id, batch.BaseRevision).Scan(&base)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && base != batch.BaseEvent {
		return nil, state.conflict(false)
	}
	if err != nil {
		return nil, err
	}
	if batch.BaseRevision < state.Revision && len(batch.Events) == 0 {
		return nil, state.conflict(false)
	}
	var eventAcks []eventAck
	var runAcks []runAck
	if state.SealedAt != nil {
		eventAcks, runAcks, err = sealedRuntimeDuplicates(ctx, db, state, batch)
	} else {
		eventAcks, runAcks, err = ingestRuntime(ctx, db, &state, batch, user.InternalID)
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"trainingId": id, "serverRevision": state.Revision, "currentEventId": state.CurrentEvent, "currentCm1AssessmentId": state.CM1, "currentCm2AssessmentId": state.CM2, "acceptedThroughClientSequence": state.Sequence, "eventAcks": eventAcks, "runAcks": runAcks, "sealed": state.SealedAt != nil}, nil
}
func runtimeEventsByID(ctx context.Context, db runtimeDB, b runtimeBatch) (map[uuid.UUID]runtimeEvent, error) {
	out := map[uuid.UUID]runtimeEvent{}
	ids := []uuid.UUID{}
	for _, e := range b.Events {
		ids = append(ids, e.ClientEventID)
	}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, "SELECT "+runtimeEventColumns+runtimeEventFrom+" WHERE e.public_id=ANY($1)", ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		event, err := scanRuntimeEvent(rows)
		if err != nil {
			return nil, err
		}
		out[event.ID] = event
	}
	return out, rows.Err()
}
func runtimeRunsByKey(ctx context.Context, db runtimeDB, keys []uuid.UUID) (map[uuid.UUID]runtimeRun, error) {
	out := map[uuid.UUID]runtimeRun{}
	if len(keys) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, "SELECT "+runtimeRunColumns+" FROM training_session_exercise_run WHERE exercise_session_key=ANY($1)", keys)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		run, err := scanRuntimeRun(rows)
		if err != nil {
			return nil, err
		}
		out[run.ExerciseSessionKey] = run
	}
	return out, rows.Err()
}
func eventPayloadHash(id int64, b runtimeBatch, e runtimeEventInput) (string, error) {
	hash, err := canonical.SHA256(canonical.SwapPayload(id, b.Writer, b.Epoch, e.CrewEvent))
	if err != nil {
		return "", err
	}
	if !canonical.EqualHash(hash, e.Hash) {
		return "", runtimeError("RUNTIME_PAYLOAD_HASH_INVALID")
	}
	return hash, nil
}
func runPayloadHash(id int64, b runtimeBatch, r runtimeRunInput) (string, error) {
	hash, err := canonical.SHA256(canonical.RunPayload(id, b.Writer, b.Epoch, r.ExerciseRun))
	if err != nil {
		return "", err
	}
	if !canonical.EqualHash(hash, r.Hash) {
		return "", runtimeError("RUNTIME_PAYLOAD_HASH_INVALID")
	}
	return hash, nil
}
func sealedRuntimeDuplicates(ctx context.Context, db runtimeDB, state runtimeState, b runtimeBatch) ([]eventAck, []runAck, error) {
	events, err := runtimeEventsByID(ctx, db, b)
	if err != nil {
		return nil, nil, err
	}
	acks := []eventAck{}
	runs := []runAck{}
	expected := b.BaseRevision + 1
	for _, incoming := range b.Events {
		hash, err := eventPayloadHash(state.TrainingID, b, incoming)
		if err != nil {
			return nil, nil, err
		}
		e, ok := events[incoming.ClientEventID]
		if !ok {
			return nil, nil, runtimeError("TRAINING_RUNTIME_SEALED")
		}
		if e.TrainingID != state.TrainingID || e.ClientID == nil || *e.ClientID != incoming.ClientEventID || !canonical.EqualHash(e.Hash, hash) {
			return nil, nil, runtimeError("CREW_EVENT_IDEMPOTENCY_CONFLICT")
		}
		if e.Revision != expected {
			return nil, nil, state.conflict(false)
		}
		acks = append(acks, eventAck{incoming.ClientEventID, "DUPLICATE", e.Revision, e.ID})
		expected++
	}
	if expected-1 != state.Revision {
		return nil, nil, state.conflict(false)
	}
	keys := []uuid.UUID{}
	for _, r := range b.Runs {
		keys = append(keys, r.ExerciseSessionKey)
	}
	existing, err := runtimeRunsByKey(ctx, db, keys)
	if err != nil {
		return nil, nil, err
	}
	for _, incoming := range b.Runs {
		hash, err := runPayloadHash(state.TrainingID, b, incoming)
		if err != nil {
			return nil, nil, err
		}
		r, ok := existing[incoming.ExerciseSessionKey]
		if !ok || r.TrainingID != state.TrainingID || r.ClientRevision != incoming.ClientRevision {
			return nil, nil, runtimeError("TRAINING_RUNTIME_SEALED")
		}
		if !canonical.EqualHash(r.Hash, hash) {
			return nil, nil, runtimeError("RUN_REVISION_CONFLICT")
		}
		runs = append(runs, runAck{incoming.ExerciseSessionKey, incoming.ClientRevision, "DUPLICATE"})
	}
	return acks, runs, nil
}
func ingestRuntime(ctx context.Context, db runtimeDB, state *runtimeState, b runtimeBatch, userID int64) ([]eventAck, []runAck, error) {
	if state.SealedAt != nil {
		return nil, nil, runtimeError("TRAINING_RUNTIME_SEALED")
	}
	// Comment contracts allow durable run checkpoints without granting swaps.
	// Submission and both sync routes use this same entitlement boundary.
	if len(b.Events) > 0 && !state.Entitled {
		return nil, nil, runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	rows, err := db.Query(ctx, `SELECT id,runtime_exercise_id FROM training_session_exercise WHERE training_session_id=$1`, state.TrainingID)
	if err != nil {
		return nil, nil, err
	}
	exercises := map[int64]int64{}
	for rows.Next() {
		var id, runtimeID int64
		if err = rows.Scan(&id, &runtimeID); err != nil {
			rows.Close()
			return nil, nil, err
		}
		exercises[runtimeID] = id
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, nil, err
	}
	runAcks, err := upsertRuntimeRuns(ctx, db, *state, b, exercises)
	if err != nil {
		return nil, nil, err
	}
	eventAcks, err := appendRuntimeEvents(ctx, db, state, b, exercises, userID)
	if err != nil {
		return nil, nil, err
	}
	return eventAcks, runAcks, nil
}

var legalRunTransitions = map[string]map[string]bool{
	// The offline outbox sends the latest snapshot and may omit ACTIVE.
	"READY": {"READY": true, "ACTIVE": true, "PAUSED": true, "COMPLETED": true, "ABANDONED": true}, "ACTIVE": {"ACTIVE": true, "PAUSED": true, "COMPLETED": true, "ABANDONED": true}, "PAUSED": {"ACTIVE": true, "PAUSED": true, "COMPLETED": true, "ABANDONED": true}, "COMPLETED": {"COMPLETED": true}, "ABANDONED": {"ABANDONED": true},
}

func upsertRuntimeRuns(ctx context.Context, db runtimeDB, state runtimeState, b runtimeBatch, exercises map[int64]int64) ([]runAck, error) {
	acks := []runAck{}
	if len(b.Runs) == 0 {
		return acks, nil
	}
	keys, initialIDs := []uuid.UUID{}, []uuid.UUID{}
	for _, run := range b.Runs {
		keys = append(keys, run.ExerciseSessionKey)
		initialIDs = append(initialIDs, run.InitialAssignmentEventID)
	}
	existing, err := runtimeRunsByKey(ctx, db, keys)
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT public_id FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND public_id=ANY($2)`, state.TrainingID, initialIDs)
	if err != nil {
		return nil, err
	}
	valid := map[uuid.UUID]bool{}
	for rows.Next() {
		var id uuid.UUID
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		valid[id] = true
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, event := range b.Events {
		valid[event.ClientEventID] = true
	}
	runs := append([]runtimeRunInput{}, b.Runs...)
	sort.SliceStable(runs, func(i, j int) bool {
		if runs[i].RuntimeExerciseID != runs[j].RuntimeExerciseID {
			return runs[i].RuntimeExerciseID < runs[j].RuntimeExerciseID
		}
		return runs[i].RunIndex < runs[j].RunIndex
	})
	type runWrite struct {
		query string
		args  []any
		phase int
	}
	writes := []runWrite{}
	for _, incoming := range runs {
		exerciseID, ok := exercises[incoming.RuntimeExerciseID]
		if !ok || !valid[incoming.InitialAssignmentEventID] {
			return nil, runtimeError("CREW_EVENT_CONTEXT_INVALID")
		}
		hash, err := runPayloadHash(state.TrainingID, b, incoming)
		if err != nil {
			return nil, err
		}
		prior, exists := existing[incoming.ExerciseSessionKey]
		status := "ACCEPTED"
		if exists {
			if prior.TrainingID != state.TrainingID || prior.ExerciseID != exerciseID || prior.RuntimeExerciseID != incoming.RuntimeExerciseID || prior.RunIndex != incoming.RunIndex {
				return nil, runtimeError("CREW_EVENT_CONTEXT_INVALID")
			}
			if incoming.ClientRevision < prior.ClientRevision {
				status = "STALE_RUN_REVISION"
			} else if incoming.ClientRevision == prior.ClientRevision {
				if !canonical.EqualHash(prior.Hash, hash) {
					return nil, runtimeError("RUN_REVISION_CONFLICT")
				}
				status = "DUPLICATE"
			} else {
				if !legalRunTransitions[prior.Status][incoming.Status] || incoming.ActiveDurationMS < prior.ActiveDurationMS || prior.Status != "READY" && incoming.InitialAssignmentEventID != prior.InitialAssignmentEventID {
					return nil, runtimeError("RUN_REVISION_CONFLICT")
				}
			}
		}
		if status == "ACCEPTED" {
			args := []any{incoming.ExerciseSessionKey, state.TrainingID, exerciseID, incoming.RuntimeExerciseID, incoming.RunIndex, incoming.Status, incoming.InitialAssignmentEventID, incoming.PlannedDurationMS, incoming.ActiveDurationMS, incoming.StartedAt, incoming.EndedAt, incoming.ClientRevision, b.Writer, b.Epoch, hash}
			query := "INSERT INTO training_session_exercise_run(" + runtimeRunColumns + ") VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)"
			phase := 2
			if exists {
				query = `UPDATE training_session_exercise_run SET training_session_id=$2,training_session_exercise_id=$3,runtime_exercise_id=$4,run_index=$5,status=$6,initial_assignment_event_public_id=$7,planned_duration_ms=$8,active_duration_ms=$9,started_at=$10,ended_at=$11,client_revision=$12,writer_instance_id=$13,writer_epoch=$14,payload_hash=$15,updated_at=now() WHERE exercise_session_key=$1`
				phase = 1
				if incoming.Status == "COMPLETED" || incoming.Status == "ABANDONED" {
					phase = 0
				}
			}
			writes = append(writes, runWrite{query, args, phase})
		}
		acks = append(acks, runAck{incoming.ExerciseSessionKey, incoming.ClientRevision, status})
	}
	// Partial unique indexes check each statement immediately. Release existing
	// active slots, then update READY runs, then insert replacements. Validation,
	// all three phases and subsequent event ingestion share the caller's tx.
	for phase := 0; phase < 3; phase++ {
		for _, write := range writes {
			if write.phase == phase {
				if _, err = db.Exec(ctx, write.query, write.args...); err != nil {
					return nil, err
				}
			}
		}
	}
	return acks, nil
}
func appendRuntimeEvents(ctx context.Context, db runtimeDB, state *runtimeState, b runtimeBatch, exercises map[int64]int64, userID int64) ([]eventAck, error) {
	acks := []eventAck{}
	if len(b.Events) == 0 {
		return acks, nil
	}
	existing, err := runtimeEventsByID(ctx, db, b)
	if err != nil {
		return nil, err
	}
	hashes := map[uuid.UUID]string{}
	for _, e := range b.Events {
		hash, err := eventPayloadHash(state.TrainingID, b, e)
		if err != nil {
			return nil, err
		}
		hashes[e.ClientEventID] = hash
	}
	start, expected := 0, b.BaseRevision+1
	for ; start < len(b.Events); start++ {
		incoming := b.Events[start]
		e, ok := existing[incoming.ClientEventID]
		if !ok {
			break
		}
		if e.TrainingID != state.TrainingID || e.ClientID == nil || *e.ClientID != incoming.ClientEventID || !canonical.EqualHash(e.Hash, hashes[incoming.ClientEventID]) {
			return nil, runtimeError("CREW_EVENT_IDEMPOTENCY_CONFLICT")
		}
		if e.Revision != expected {
			return nil, state.conflict(false)
		}
		acks = append(acks, eventAck{incoming.ClientEventID, "DUPLICATE", e.Revision, e.ID})
		expected++
	}
	newEvents := b.Events[start:]
	for _, e := range newEvents {
		if _, ok := existing[e.ClientEventID]; ok {
			return nil, state.conflict(false)
		}
	}
	if expected-1 != state.Revision {
		return nil, state.conflict(false)
	}
	if len(newEvents) == 0 {
		return acks, nil
	}
	if newEvents[0].PreviousEventID != state.CurrentEvent || newEvents[0].ClientSequence != state.Sequence+1 {
		return nil, state.conflict(false)
	}
	keys := []uuid.UUID{}
	for _, e := range newEvents {
		if e.ExerciseSessionKey != nil {
			keys = append(keys, *e.ExerciseSessionKey)
		}
	}
	runs, err := runtimeRunsByKey(ctx, db, keys)
	if err != nil {
		return nil, err
	}
	offsets := map[uuid.UUID]int64{}
	if len(keys) > 0 {
		rows, err := db.Query(ctx, `SELECT exercise_session_key,max(exercise_offset_ms) FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND exercise_session_key=ANY($2) GROUP BY exercise_session_key`, state.TrainingID, keys)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var key uuid.UUID
			var offset *int64
			if err = rows.Scan(&key, &offset); err != nil {
				rows.Close()
				return nil, err
			}
			if offset != nil {
				offsets[key] = *offset
			}
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return nil, err
		}
	}
	updated := *state
	for _, e := range newEvents {
		if e.ClientSequence != updated.Sequence+1 || e.PreviousEventID != updated.CurrentEvent {
			return nil, state.conflict(false)
		}
		before := canonical.CrewMapping{CM1AssessmentID: updated.CM1, CM2AssessmentID: updated.CM2}
		after := canonical.CrewMapping{CM1AssessmentID: e.CM1AssessmentIDAfter, CM2AssessmentID: e.CM2AssessmentIDAfter}
		if canonical.ValidateExactSwap(before, after) != nil {
			return nil, runtimeError("CREW_ASSIGNMENT_INVALID")
		}
		var exerciseID *int64
		if e.Scope == "EXERCISE_RUN" {
			run, ok := runs[*e.ExerciseSessionKey]
			id, exists := exercises[*e.RuntimeExerciseID]
			if !ok || !exists || run.TrainingID != state.TrainingID || run.ExerciseID != id || run.RuntimeExerciseID != *e.RuntimeExerciseID {
				return nil, runtimeError("CREW_EVENT_CONTEXT_INVALID")
			}
			if *e.ExerciseOffsetMS < offsets[*e.ExerciseSessionKey] || *e.ExerciseOffsetMS > run.ActiveDurationMS {
				return nil, runtimeError("CREW_EVENT_OFFSET_INVALID")
			}
			offsets[*e.ExerciseSessionKey] = *e.ExerciseOffsetMS
			exerciseID = &id
		}
		updated.Revision++
		_, err = db.Exec(ctx, `INSERT INTO training_session_crew_assignment_event(public_id,client_event_id,training_session_id,server_revision,event_kind,event_scope,writer_instance_id,writer_epoch,client_sequence,previous_event_public_id,occurred_at,created_by,training_session_exercise_id,exercise_session_key,exercise_offset_ms,timer_state,cm1_assessment_id_after,cm2_assessment_id_after,payload_hash,client_app_version,client_platform) VALUES($1,$1,$2,$3,'SWAP',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)`, e.ClientEventID, state.TrainingID, updated.Revision, e.Scope, b.Writer, b.Epoch, e.ClientSequence, e.PreviousEventID, e.OccurredAt, userID, exerciseID, e.ExerciseSessionKey, e.ExerciseOffsetMS, e.TimerState, e.CM1AssessmentIDAfter, e.CM2AssessmentIDAfter, hashes[e.ClientEventID], e.AppVersion, e.Platform)
		if err != nil {
			return nil, err
		}
		acks = append(acks, eventAck{e.ClientEventID, "ACCEPTED", updated.Revision, e.ClientEventID})
		updated.CurrentEvent = e.ClientEventID
		updated.Sequence = e.ClientSequence
		updated.CM1 = e.CM1AssessmentIDAfter
		updated.CM2 = e.CM2AssessmentIDAfter
	}
	if err = saveRuntimeState(ctx, db, updated); err != nil {
		return nil, err
	}
	*state = updated
	return acks, nil
}
