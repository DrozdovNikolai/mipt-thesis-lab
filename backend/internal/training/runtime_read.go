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
