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
