package training

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func ensureSubmissionRuntime(ctx context.Context, db runtimeDB, t record, user *auth.User) (runtimeState, error) {
	id := t.number("id")
	state, err := loadRuntimeState(ctx, db, id, true)
	if err == nil {
		return state, nil
	}
	if err.Error() == "runtime initial event missing" {
		return state, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return state, err
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE training_session_id=$1`, id)
	if err != nil {
		return state, err
	}
	roles := map[string]int64{}
	for _, r := range rows {
		roles[strings.ToLower(r.text("training_role"))] = r.number("id")
	}
	if len(roles) != 2 || roles["cm1"] == 0 || roles["cm2"] == 0 {
		return state, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	writer, err := uuid.NewV7()
	if err != nil {
		return state, err
	}
	return createInitialRuntime(ctx, db, id, roles["cm1"], roles["cm2"], user.InternalID, writer, false)
}

func (s *Service) ingestSubmissionRuntime(ctx context.Context, db runtimeDB, state *runtimeState, seal platform.Object, user *auth.User, commentContract bool) error {
	if !s.Auth.Config.RuntimeWriteEnabled {
		return runtimeError("RUNTIME_WRITE_PAUSED")
	}
	pending := seal["pending_runtime"].(platform.Object)
	raw, err := canonical.JSON(schemaWireObject(pending, pendingRuntimeSchema))
	if err != nil {
		return err
	}
	if len(raw) > 1024*1024 {
		return runtimeError("RUNTIME_BATCH_TOO_LARGE")
	}
	if !state.Entitled && !commentContract {
		return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if state.Entitled && state.Version != 1 {
		return runtimeError("RUNTIME_CAPABILITY_VERSION_UNSUPPORTED")
	}
	if state.Writer != seal["writer_instance_id"].(uuid.UUID) || seal.CompareInteger("writer_epoch", state.Epoch) != 0 {
		return state.conflict(true)
	}
	if len(pending["run_snapshots"].([]any)) == 0 && len(pending["crew_assignment_events"].([]any)) == 0 {
		return nil
	}
	if seal.CompareInteger("base_server_revision", state.Revision) > 0 {
		return runtimeError("RUNTIME_SYNC_REQUIRED")
	}
	var base uuid.UUID
	err = db.QueryRow(ctx, `SELECT public_id FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND server_revision=$2`, state.TrainingID, seal.Int("base_server_revision")).Scan(&base)
	if errors.Is(err, pgx.ErrNoRows) {
		return runtimeError("RUNTIME_SYNC_REQUIRED")
	}
	if err != nil {
		return err
	}
	if seal.Int("base_server_revision") < state.Revision && len(pending["crew_assignment_events"].([]any)) == 0 {
		return state.conflict(false)
	}
	o := platform.Object{"writer_instance_id": seal["writer_instance_id"], "writer_epoch": seal["writer_epoch"], "base_server_revision": seal["base_server_revision"], "base_server_event_id": base, "run_snapshots": pending["run_snapshots"], "crew_assignment_events": pending["crew_assignment_events"]}
	_, _, err = ingestRuntime(ctx, db, state, parseRuntimeBatch(o), user.InternalID)
	return err
}

func terminalizeSubmissionRuns(ctx context.Context, db runtimeDB, state runtimeState) ([]runtimeRun, error) {
	rows, err := db.Query(ctx, "SELECT "+runtimeRunColumns+" FROM training_session_exercise_run WHERE training_session_id=$1 ORDER BY exercise_session_key", state.TrainingID)
	if err != nil {
		return nil, err
	}
	runs := []runtimeRun{}
	for rows.Next() {
		r, err := scanRuntimeRun(rows)
		if err != nil {
			rows.Close()
			return nil, err
		}
		runs = append(runs, r)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, err
	}
	exercises, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise e WHERE training_session_id=$1`, state.TrainingID)
	if err != nil {
		return nil, err
	}
	byExercise := map[int64]record{}
	for _, e := range exercises {
		byExercise[e.number("id")] = e
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	for i := range runs {
		r := &runs[i]
		if r.Status == "ACTIVE" || r.Status == "PAUSED" {
			return nil, runtimeError("RUNTIME_SYNC_REQUIRED")
		}
		if r.Status == "READY" {
			r.Status = "ABANDONED"
			r.EndedAt = &now
			r.ClientRevision++
			r.Writer = state.Writer
			r.Epoch = state.Epoch
			r.Hash, err = canonical.SHA256(canonical.RunPayload(state.TrainingID, state.Writer, state.Epoch, r.ExerciseRun))
			if err != nil {
				return nil, err
			}
			_, err = db.Exec(ctx, `UPDATE training_session_exercise_run SET status='ABANDONED',ended_at=$2,client_revision=$3,writer_instance_id=$4,writer_epoch=$5,payload_hash=$6,updated_at=now() WHERE exercise_session_key=$1`, r.ExerciseSessionKey, now, r.ClientRevision, r.Writer, r.Epoch, r.Hash)
			if err != nil {
				return nil, err
			}
		}
	}
	events, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 ORDER BY server_revision`, state.TrainingID)
	if err != nil {
		return nil, err
	}
	byEvent := map[string]record{}
	byRun := map[string][]record{}
	for _, e := range events {
		byEvent[e.text("public_id")] = e
		if e["exercise_session_key"] != nil {
			byRun[e.text("exercise_session_key")] = append(byRun[e.text("exercise_session_key")], e)
		}
	}
	if _, err = db.Exec(ctx, `DELETE FROM training_session_exercise_crew_segment WHERE training_session_id=$1`, state.TrainingID); err != nil {
		return nil, err
	}
	for _, r := range runs {
		exercise, initial := byExercise[r.ExerciseID], byEvent[r.InitialAssignmentEventID.String()]
		if exercise == nil || initial == nil {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		var pf *int
		if slot := exercise.number("crew_member_number"); slot == 1 || slot == 2 {
			value := int(slot)
			pf = &value
		}
		projection := []canonical.CrewEventProjection{}
		for _, e := range byRun[r.ExerciseSessionKey.String()] {
			if e["exercise_offset_ms"] == nil {
				continue
			}
			id, err := uuid.Parse(e.text("public_id"))
			if err != nil {
				return nil, err
			}
			projection = append(projection, canonical.CrewEventProjection{EventID: id, ServerRevision: e.number("server_revision"), ExerciseOffsetMS: e.number("exercise_offset_ms"), MappingAfter: canonical.CrewMapping{CM1AssessmentID: e.number("cm1_assessment_id_after"), CM2AssessmentID: e.number("cm2_assessment_id_after")}})
		}
		segments, err := canonical.BuildCrewSegments(r.ActiveDurationMS, pf, r.InitialAssignmentEventID, canonical.CrewMapping{CM1AssessmentID: initial.number("cm1_assessment_id_after"), CM2AssessmentID: initial.number("cm2_assessment_id_after")}, projection)
		if err != nil {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		for _, segment := range segments {
			_, err = db.Exec(ctx, `INSERT INTO training_session_exercise_crew_segment(training_session_id,exercise_session_key,training_session_exercise_id,segment_index,from_offset_ms,to_offset_ms,cm1_assessment_id,cm2_assessment_id,pf_assessment_id,pm_assessment_id,starts_after_event_public_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, state.TrainingID, r.ExerciseSessionKey, r.ExerciseID, segment.SegmentIndex, segment.FromOffsetMS, segment.ToOffsetMS, segment.Mapping.CM1AssessmentID, segment.Mapping.CM2AssessmentID, segment.PFAssessmentID, segment.PMAssessmentID, segment.StartsAfterEventID)
			if err != nil {
				return nil, err
			}
		}
	}
	return runs, nil
}

func verifySubmissionManifest(ctx context.Context, db runtimeDB, state runtimeState, o platform.Object, runs []runtimeRun) (string, error) {
	seal := o["runtime_seal"].(platform.Object)
	if state.CurrentEvent != seal["expected_current_event_id"].(uuid.UUID) || seal.CompareInteger("expected_client_sequence", state.Sequence) != 0 {
		return "", runtimeError("RUNTIME_SYNC_REQUIRED")
	}
	events, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 ORDER BY server_revision`, state.TrainingID)
	if err != nil {
		return "", err
	}
	if int64(len(events)) != state.Revision+1 {
		return "", runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	for i, e := range events {
		if e.number("server_revision") != int64(i) {
			return "", runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
	}
	if len(events) == 0 || events[len(events)-1].text("public_id") != state.CurrentEvent.String() {
		return "", runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	input := canonical.SubmissionManifest{TrainingID: state.TrainingID, WriterEpoch: state.Epoch, ExpectedClientSequence: state.Sequence, WriterInstanceID: state.Writer, ExpectedCurrentEventID: state.CurrentEvent, SpeechSessionID: runtimePtr[uuid.UUID](o, "speech_session_id"), SpeechLastChunkIndex: runtimePtr[int64](o, "speech_last_chunk_index"), CommentContractVersion: runtimePtr[int64](o, "comment_contract_version")}
	for _, e := range events {
		input.CrewEventPayloadHashes = append(input.CrewEventPayloadHashes, e.text("payload_hash"))
	}
	for _, r := range runs {
		if r.Status == "COMPLETED" || r.Status == "ABANDONED" {
			input.TerminalRunHashes = append(input.TerminalRunHashes, canonical.TerminalRunHash{ExerciseSessionKey: r.ExerciseSessionKey, PayloadHash: r.Hash})
		}
	}
	for _, b := range o["assessments"].([]any) {
		input.AssessmentBlocks = append(input.AssessmentBlocks, canonicalAssessment(b.(platform.Object)))
	}
	manifest, err := canonical.ManifestPayload(input)
	if err != nil {
		return "", err
	}
	hash, err := canonical.SHA256(manifest)
	if err != nil {
		return "", err
	}
	if !canonical.EqualHash(hash, o.String("submission_manifest_hash")) {
		return "", runtimeError("RUNTIME_MANIFEST_MISMATCH")
	}
	return hash, nil
}
