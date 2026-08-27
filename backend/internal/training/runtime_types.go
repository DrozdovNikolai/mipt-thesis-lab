package training

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

type runtimeDB interface {
	QueryRow(context.Context, string, ...any) pgx.Row
	Query(context.Context, string, ...any) (pgx.Rows, error)
	Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
}
type runtimeTraining struct {
	ID                     int64
	Status                 string
	CommentContractVersion int64
}
type runtimeState struct {
	TrainingID, Revision, Sequence, CM1, CM2, Epoch, Version int64
	CurrentEvent, Writer                                     uuid.UUID
	Entitled                                                 bool
	SealedAt                                                 *time.Time
	InitialID                                                uuid.UUID
	InitialHash                                              string
}
type runtimeEvent struct {
	ID                            uuid.UUID
	ClientID                      *uuid.UUID
	TrainingID, Revision          int64
	Kind, Scope                   string
	Writer                        *uuid.UUID
	Epoch, Sequence               int64
	Previous                      *uuid.UUID
	Occurred                      time.Time
	ExerciseID, RuntimeExerciseID *int64
	RunKey                        *uuid.UUID
	Offset                        *int64
	Timer                         string
	CM1, CM2                      int64
	Hash                          string
}
type runtimeRun struct {
	canonical.ExerciseRun
	TrainingID, ExerciseID, Epoch int64
	Writer                        uuid.UUID
	Hash                          string
}
type runtimeEventInput struct {
	canonical.CrewEvent
	Hash                 string
	AppVersion, Platform *string
}
type runtimeRunInput struct {
	canonical.ExerciseRun
	Hash string
}
type runtimeBatch struct {
	Writer              uuid.UUID
	Epoch, BaseRevision int64
	BaseEvent           uuid.UUID
	Events              []runtimeEventInput
	Runs                []runtimeRunInput
}
type eventAck struct {
	ClientEventID  uuid.UUID `json:"clientEventId"`
	Status         string    `json:"status"`
	ServerRevision int64     `json:"serverRevision"`
	ServerEventID  uuid.UUID `json:"serverEventId"`
}
type runAck struct {
	ExerciseSessionKey uuid.UUID `json:"exerciseSessionKey"`
	ClientRevision     int64     `json:"clientRevision"`
	Status             string    `json:"status"`
}

func runtimeError(code string) *platform.APIError {
	status, message := 409, ""
	switch code {
	case "RUNTIME_SYNC_REQUIRED":
		message = "Runtime server watermark does not match the submit boundary"
	case "RUNTIME_MANIFEST_MISMATCH":
		message = "Frozen submit manifest differs from the accepted runtime boundary"
	case "RUNTIME_SEAL_REQUIRED":
		message = "Runtime seal is required for an entitled or timeline-enabled training"
	case "TRAINING_CREATE_IDEMPOTENCY_CONFLICT":
		message = "clientCreationId was already used with a different payload"
	case "RUNTIME_CHAIN_CORRUPT":
		message = "Crew runtime chain failed an integrity invariant"
	case "TRAINING_NOT_IN_PROGRESS":
		message = "Training runtime can only be changed while training is in progress"
	case "TRAINING_RUNTIME_SEALED":
		message = "Training runtime is already sealed"
	case "CREW_WRITER_EPOCH_CONFLICT":
		message = "Crew runtime writer instance or epoch does not match"
	case "CREW_EVENT_CHAIN_CONFLICT":
		message = "Crew event chain does not continue from the accepted server state"
	case "CREW_EVENT_IDEMPOTENCY_CONFLICT":
		message = "Crew event ID already exists with a different canonical payload"
	case "RUN_REVISION_CONFLICT":
		message = "Exercise run revision already exists with a different payload"
	case "CREW_ASSIGNMENT_INVALID":
		status = 422
		message = "Crew assignment must be an exact swap of the current two assessments"
	case "CREW_EVENT_CONTEXT_INVALID":
		status = 422
		message = "Crew event run or exercise context is invalid"
	case "CREW_EVENT_OFFSET_INVALID":
		status = 422
		message = "Crew event offset is invalid for the exercise run"
	case "RUNTIME_BATCH_TOO_LARGE":
		status = 413
		message = "Runtime sync batch exceeds configured limits"
	case "RUNTIME_CAPABILITY_NOT_GRANTED":
		status = 403
		message = "Training session was not granted live crew runtime capability"
	case "RUNTIME_CAPABILITY_VERSION_UNSUPPORTED":
		message = "Crew runtime capability version is not supported"
	case "RUNTIME_WRITE_PAUSED":
		status = 503
		message = "Crew runtime ingestion is temporarily paused"
	case "RUNTIME_PAYLOAD_HASH_INVALID":
		status = 422
		message = "Runtime payload hash does not match server canonicalization"
	case "RUNTIME_WRITER_TAKEOVER_INVALID":
		message = "Runtime writer takeover precondition failed"
	}
	e := &platform.APIError{Status: status, Code: code, Message: message}
	e.SupportCorrelation = code != "RUN_REVISION_CONFLICT"
	if code == "RUNTIME_WRITE_PAUSED" {
		e.Extra = map[string]any{"retryable": true}
	}
	return e
}
func (state runtimeState) conflict(writer bool) error {
	code := "CREW_EVENT_CHAIN_CONFLICT"
	if writer {
		code = "CREW_WRITER_EPOCH_CONFLICT"
	}
	e := runtimeError(code)
	e.Extra = map[string]any{"currentServerRevision": state.Revision, "currentEventId": state.CurrentEvent, "acceptedThroughClientSequence": state.Sequence, "retryable": false}
	if writer {
		e.Extra["currentWriterInstanceId"] = state.Writer
		e.Extra["currentWriterEpoch"] = state.Epoch
	}
	return e
}
func apiTime(t *time.Time) any {
	if t == nil {
		return nil
	}
	value := t.UTC()
	layout := "2006-01-02T15:04:05Z"
	if value.Nanosecond()/1000 != 0 {
		layout = "2006-01-02T15:04:05.000000Z"
	}
	return value.Format(layout)
}
func (s runtimeState) response() map[string]any {
	return map[string]any{"capabilityVersion": s.Version, "liveSwapEntitled": s.Entitled, "writerInstanceId": s.Writer, "writerEpoch": s.Epoch, "serverRevision": s.Revision, "acceptedThroughClientSequence": s.Sequence, "initialEventId": s.InitialID, "initialEventHash": s.InitialHash, "currentEventId": s.CurrentEvent, "currentCm1AssessmentId": s.CM1, "currentCm2AssessmentId": s.CM2, "sealed": s.SealedAt != nil, "sealedAt": apiTime(s.SealedAt)}
}
func (e runtimeEvent) response() map[string]any {
	return map[string]any{"eventId": e.ID, "serverRevision": e.Revision, "eventKind": e.Kind, "scope": e.Scope, "writerInstanceId": e.Writer, "writerEpoch": e.Epoch, "clientSequence": e.Sequence, "previousEventId": e.Previous, "occurredAt": apiTime(&e.Occurred), "runtimeExerciseId": e.RuntimeExerciseID, "exerciseSessionKey": e.RunKey, "exerciseOffsetMs": e.Offset, "timerState": e.Timer, "cm1AssessmentIdAfter": e.CM1, "cm2AssessmentIdAfter": e.CM2, "payloadHash": e.Hash}
}
func (r runtimeRun) response() map[string]any {
	return map[string]any{"exerciseSessionKey": r.ExerciseSessionKey, "runtimeExerciseId": r.RuntimeExerciseID, "runIndex": r.RunIndex, "status": r.Status, "initialAssignmentEventId": r.InitialAssignmentEventID, "plannedDurationMs": r.PlannedDurationMS, "activeDurationMs": r.ActiveDurationMS, "startedAt": apiTime(r.StartedAt), "endedAt": apiTime(r.EndedAt), "clientRevision": r.ClientRevision, "writerInstanceId": r.Writer, "writerEpoch": r.Epoch, "payloadHash": r.Hash}
}
func getRuntimeTraining(ctx context.Context, db runtimeDB, id int64, user *auth.User) (runtimeTraining, error) {
	t := runtimeTraining{ID: id}
	var instructor *int64
	err := db.QueryRow(ctx, `SELECT instructor_id,status,comment_contract_version FROM training_session WHERE id=$1`, id).Scan(&instructor, &t.Status, &t.CommentContractVersion)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && t.Status == "DELETED" {
		return t, platform.Error(404, "Training not found")
	}
	if err != nil {
		return t, err
	}
	if instructor != nil && *instructor != user.InternalID {
		return t, platform.Error(403, "Training belongs to another instructor")
	}
	return t, nil
}
func loadRuntimeState(ctx context.Context, db runtimeDB, id int64, lock bool) (runtimeState, error) {
	s := runtimeState{TrainingID: id}
	query := `SELECT current_revision,current_event_public_id,current_writer_sequence,current_cm1_assessment_id,current_cm2_assessment_id,writer_instance_id,writer_epoch,capability_version,live_swap_entitled,sealed_at FROM training_session_crew_state WHERE training_session_id=$1`
	if lock {
		query += " FOR UPDATE"
	}
	err := db.QueryRow(ctx, query, id).Scan(&s.Revision, &s.CurrentEvent, &s.Sequence, &s.CM1, &s.CM2, &s.Writer, &s.Epoch, &s.Version, &s.Entitled, &s.SealedAt)
	if err != nil {
		return s, err
	}
	err = db.QueryRow(ctx, `SELECT public_id,payload_hash FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND server_revision=0`, id).Scan(&s.InitialID, &s.InitialHash)
	if errors.Is(err, pgx.ErrNoRows) {
		return s, errors.New("runtime initial event missing")
	}
	return s, err
}

const runtimeEventColumns = `e.public_id,e.client_event_id,e.training_session_id,e.server_revision,e.event_kind,e.event_scope,e.writer_instance_id,e.writer_epoch,e.client_sequence,e.previous_event_public_id,e.occurred_at,e.training_session_exercise_id,x.runtime_exercise_id,e.exercise_session_key,e.exercise_offset_ms,e.timer_state,e.cm1_assessment_id_after,e.cm2_assessment_id_after,e.payload_hash`
const runtimeEventFrom = ` FROM training_session_crew_assignment_event e LEFT JOIN training_session_exercise x ON x.id=e.training_session_exercise_id`

func scanRuntimeEvent(row pgx.Row) (runtimeEvent, error) {
	var e runtimeEvent
	err := row.Scan(&e.ID, &e.ClientID, &e.TrainingID, &e.Revision, &e.Kind, &e.Scope, &e.Writer, &e.Epoch, &e.Sequence, &e.Previous, &e.Occurred, &e.ExerciseID, &e.RuntimeExerciseID, &e.RunKey, &e.Offset, &e.Timer, &e.CM1, &e.CM2, &e.Hash)
	return e, err
}

const runtimeRunColumns = `exercise_session_key,training_session_id,training_session_exercise_id,runtime_exercise_id,run_index,status,initial_assignment_event_public_id,planned_duration_ms,active_duration_ms,started_at,ended_at,client_revision,writer_instance_id,writer_epoch,payload_hash`

func scanRuntimeRun(row pgx.Row) (runtimeRun, error) {
	var r runtimeRun
	err := row.Scan(&r.ExerciseSessionKey, &r.TrainingID, &r.ExerciseID, &r.RuntimeExerciseID, &r.RunIndex, &r.Status, &r.InitialAssignmentEventID, &r.PlannedDurationMS, &r.ActiveDurationMS, &r.StartedAt, &r.EndedAt, &r.ClientRevision, &r.Writer, &r.Epoch, &r.Hash)
	return r, err
}
func saveRuntimeState(ctx context.Context, db runtimeDB, s runtimeState) error {
	_, err := db.Exec(ctx, `UPDATE training_session_crew_state SET current_revision=$2,current_event_public_id=$3,current_writer_sequence=$4,current_cm1_assessment_id=$5,current_cm2_assessment_id=$6,writer_instance_id=$7,writer_epoch=$8,capability_version=$9,live_swap_entitled=$10,updated_at=now() WHERE training_session_id=$1`, s.TrainingID, s.Revision, s.CurrentEvent, s.Sequence, s.CM1, s.CM2, s.Writer, s.Epoch, s.Version, s.Entitled)
	return err
}
