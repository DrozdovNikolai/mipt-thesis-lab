package training

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func (s *Service) registerRuntime(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/trainings/{training_id}/runtime"
	mux.HandleFunc("GET "+p, platform.Wrap(s.readRuntime))
	mux.HandleFunc("GET "+p+"/events", platform.Wrap(s.readRuntime))
	mux.HandleFunc("POST "+p+"/sync", platform.Wrap(s.syncRuntime))
	mux.HandleFunc("POST "+p+"/writer/bootstrap", platform.Wrap(s.bootstrapRuntime))
	mux.HandleFunc("POST "+p+"/writer/takeover", platform.Wrap(s.takeoverRuntime))
}
func (s *Service) readRuntime(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	fields := []platform.Field{{Name: "after_server_revision", Alias: "afterServerRevision", Kind: "integer", NonNegative: true}, {Name: "include_runs", Alias: "includeRuns", Kind: "boolean", Default: true}, {Name: "event_limit", Alias: "eventLimit", Kind: "integer", Min: 1, Max: 1000, Default: int64(200)}, {Name: "cursor", Kind: "integer", NonNegative: true}}
	eventsOnly := strings.HasSuffix(r.URL.Path, "/events")
	if eventsOnly {
		fields = append(fields[:1], fields[2:]...)
	}
	query, err := platform.QueryObject(r.URL.Query(), fields...)
	if err != nil {
		return err
	}
	ctx, db := r.Context(), s.Auth.DB
	if _, err = getRuntimeTraining(ctx, db, id, user); err != nil {
		return err
	}
	state, err := loadRuntimeState(ctx, db, id, false)
	if errors.Is(err, pgx.ErrNoRows) {
		return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if err != nil {
		return err
	}
	after := int64(-1)
	for _, key := range []string{"after_server_revision", "cursor"} {
		if query.Has(key) && query.Int(key) > after {
			after = query.Int(key)
		}
	}
	limit := query.Int("event_limit")
	rows, err := db.Query(ctx, "SELECT "+runtimeEventColumns+runtimeEventFrom+" WHERE e.training_session_id=$1 AND e.server_revision>$2 AND e.server_revision<=$3 ORDER BY e.server_revision LIMIT $4", id, after, state.Revision, limit+1)
	if err != nil {
		return err
	}
	events := []map[string]any{}
	var cursor *string
	for rows.Next() {
		e, err := scanRuntimeEvent(rows)
		if err != nil {
			rows.Close()
			return err
		}
		if int64(len(events)) == limit {
			value := strconv.FormatInt(events[len(events)-1]["serverRevision"].(int64), 10)
			cursor = &value
			break
		}
		events = append(events, e.response())
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	runs := []map[string]any{}
	if !eventsOnly && query.Bool("include_runs") {
		rows, err = db.Query(ctx, "SELECT "+runtimeRunColumns+" FROM training_session_exercise_run WHERE training_session_id=$1 ORDER BY training_session_exercise_id,run_index", id)
		if err != nil {
			return err
		}
		for rows.Next() {
			run, err := scanRuntimeRun(rows)
			if err != nil {
				rows.Close()
				return err
			}
			runs = append(runs, run.response())
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return err
		}
	}
	platform.WriteJSON(w, 200, map[string]any{"trainingId": id, "state": state.response(), "events": events, "runs": runs, "nextCursor": cursor})
	return nil
}
func (s *Service) runtimeEntitled(airlineID int64, c canonical.Capabilities, contexts ...context.Context) bool {
	cfg := s.Auth.Config
	if !cfg.LiveCrewSwapEnabled || !c.OfflineDurabilityReady || c.TransactionalStore == "NONE" {
		return false
	}
	raw := strings.TrimSpace(cfg.LiveCrewSwapAirlineIDs)
	if raw != "" {
		allowed := false
		for _, entry := range strings.Split(raw, ",") {
			entry = strings.TrimSpace(entry)
			if entry == "" {
				continue
			}
			id, err := strconv.ParseInt(entry, 10, 64)
			if err != nil {
				platform.LogModule("app.audit", contexts...).Error("Invalid live crew swap airline allowlist", "action", "assessment.runtime.config_invalid")
				return false
			}
			if id == airlineID {
				allowed = true
			}
		}
		if !allowed {
			return false
		}
	}
	for _, v := range c.LiveCrewSwapVersions {
		if v == 1 {
			return true
		}
	}
	return false
}
func createInitialRuntime(ctx context.Context, db runtimeDB, id, cm1, cm2, userID int64, writer uuid.UUID, entitled bool) (runtimeState, error) {
	eventID, err := uuid.NewV7()
	if err != nil {
		return runtimeState{}, err
	}
	hash, err := canonical.SHA256(canonical.InitialPayload(id, eventID, canonical.CrewMapping{CM1AssessmentID: cm1, CM2AssessmentID: cm2}))
	if err != nil {
		return runtimeState{}, err
	}
	s := runtimeState{TrainingID: id, CurrentEvent: eventID, Writer: writer, Epoch: 1, CM1: cm1, CM2: cm2, Entitled: entitled, InitialID: eventID, InitialHash: hash}
	if entitled {
		s.Version = 1
	}
	_, err = db.Exec(ctx, `INSERT INTO training_session_crew_assignment_event(public_id,training_session_id,server_revision,event_kind,event_scope,writer_epoch,client_sequence,occurred_at,created_by,timer_state,cm1_assessment_id_after,cm2_assessment_id_after,payload_hash) VALUES($1,$2,0,'INITIAL','SESSION',0,0,$3,$4,'NONE',$5,$6,$7)`, eventID, id, time.Now().UTC(), userID, cm1, cm2, hash)
	if err != nil {
		return s, err
	}
	_, err = db.Exec(ctx, `INSERT INTO training_session_crew_state(training_session_id,current_event_public_id,current_cm1_assessment_id,current_cm2_assessment_id,writer_instance_id,capability_version,live_swap_entitled) VALUES($1,$2,$3,$4,$5,$6,$7)`, id, eventID, cm1, cm2, writer, s.Version, entitled)
	return s, err
}
func (s *Service) bootstrapRuntime(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	o, err := platform.ReadSchema(r, runtimeBootstrapSchema)
	if err != nil {
		return err
	}
	if !s.Auth.Config.RuntimeWriteEnabled {
		return runtimeError("RUNTIME_WRITE_PAUSED")
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	training, err := getRuntimeTraining(ctx, tx, id, user)
	if err != nil {
		return err
	}
	if training.Status != "IN_PROGRESS" {
		return runtimeError("TRAINING_NOT_IN_PROGRESS")
	}
	if _, err = tx.Exec(ctx, `SELECT id FROM training_session WHERE id=$1 FOR UPDATE`, id); err != nil {
		return err
	}
	state, err := loadRuntimeState(ctx, tx, id, true)
	missing := errors.Is(err, pgx.ErrNoRows)
	if err != nil && !missing {
		return err
	}
	writer := o["writer_instance_id"].(uuid.UUID)
	capabilities := parseCapabilities(o["runtime_client_capabilities"].(platform.Object))
	airline := int64(0)
	if user.AirlineID != nil {
		airline = *user.AirlineID
	}
	if missing {
		rows, err := tx.Query(ctx, `SELECT id,training_role FROM crew_member_assessment WHERE training_session_id=$1`, id)
		if err != nil {
			return err
		}
		roles := map[string]int64{}
		for rows.Next() {
			var assessment int64
			var role string
			if err = rows.Scan(&assessment, &role); err != nil {
				rows.Close()
				return err
			}
			roles[role] = assessment
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return err
		}
		if len(roles) != 2 || roles["cm1"] == 0 || roles["cm2"] == 0 {
			return runtimeError("CREW_ASSIGNMENT_INVALID")
		}
		if !s.runtimeEntitled(airline, capabilities, r.Context()) {
			return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
		}
		state, err = createInitialRuntime(ctx, tx, id, roles["cm1"], roles["cm2"], user.InternalID, writer, true)
		if err != nil {
			return err
		}
	} else {
		if state.SealedAt != nil {
			return runtimeError("TRAINING_RUNTIME_SEALED")
		}
		if state.Revision != 0 {
			return runtimeError("RUNTIME_WRITER_TAKEOVER_INVALID")
		}
		if !s.runtimeEntitled(airline, capabilities, r.Context()) {
			return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
		}
		original := state
		if state.Writer != writer {
			state.Epoch++
			state.Sequence = 0
		}
		state.Writer = writer
		state.Entitled = true
		state.Version = 1
		if state != original {
			if err = saveRuntimeState(ctx, tx, state); err != nil {
				return err
			}
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, state.response())
	return nil
}
func (s *Service) takeoverRuntime(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	o, err := platform.ReadSchema(r, runtimeTakeoverSchema)
	if err != nil {
		return err
	}
	if !s.Auth.Config.RuntimeWriteEnabled {
		return runtimeError("RUNTIME_WRITE_PAUSED")
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	training, err := getRuntimeTraining(ctx, tx, id, user)
	if err != nil {
		return err
	}
	// Match sync/draft/submit's parent-first lock order and refresh status after
	// waiting, so a training submitted by another request cannot be taken over.
	if err = tx.QueryRow(ctx, `SELECT status FROM training_session WHERE id=$1 FOR UPDATE`, id).Scan(&training.Status); err != nil {
		return err
	}
	if training.Status != "IN_PROGRESS" {
		return runtimeError("TRAINING_NOT_IN_PROGRESS")
	}
	state, err := loadRuntimeState(ctx, tx, id, true)
	if errors.Is(err, pgx.ErrNoRows) {
		return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if err != nil {
		return err
	}
	if state.SealedAt != nil {
		return runtimeError("TRAINING_RUNTIME_SEALED")
	}
	if !state.Entitled {
		return runtimeError("RUNTIME_CAPABILITY_NOT_GRANTED")
	}
	if o.CompareInteger("expected_writer_epoch", state.Epoch) != 0 {
		return state.conflict(true)
	}
	writer := o["new_writer_instance_id"].(uuid.UUID)
	if state.Writer == writer {
		return runtimeError("RUNTIME_WRITER_TAKEOVER_INVALID")
	}
	state.Writer = writer
	state.Epoch++
	state.Sequence = 0
	if err = saveRuntimeState(ctx, tx, state); err != nil {
		return err
	}
	// Ownership changes without changing content, revision or its canonical hash.
	if _, err = tx.Exec(ctx, `UPDATE training_session_draft SET writer_instance_id=$3,updated_at=now() WHERE training_session_id=$1 AND user_id=$2 AND writer_instance_id IS NOT NULL AND writer_instance_id<>$3`, id, user.InternalID, writer); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Warn("Training crew runtime writer taken over", "action", "assessment.runtime.writer_takeover", "training_id", id, "writer_instance_id", writer, "writer_epoch", state.Epoch, "user_id", user.ID)
	platform.WriteJSON(w, 200, state.response())
	return nil
}
