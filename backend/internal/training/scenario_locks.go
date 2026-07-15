package training

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func (s *Service) registerScenarioLocks(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/scenarios/{scenario_id}/lock"
	mux.HandleFunc("GET "+p, platform.Wrap(s.readScenarioLock))
	mux.HandleFunc("POST "+p, platform.Wrap(s.acquireScenarioLock))
	mux.HandleFunc("DELETE "+p, platform.Wrap(s.releaseScenarioLock))
}

func scenarioLockDTO(ctx context.Context, db runtimeDB, scenarioID any, lock record, now time.Time, client string, user *auth.User) (record, error) {
	value := record{"scenario_id": scenarioID, "is_locked": false, "expires_at": nil, "owner": nil, "is_owner": false}
	if lock == nil {
		return value, nil
	}
	expires, err := time.Parse(time.RFC3339Nano, lock.text("expires_at"))
	if err != nil {
		return nil, err
	}
	if !expires.After(now) {
		return value, nil
	}
	value["is_locked"], value["expires_at"], value["is_owner"] = true, apiTime(&expires), lock.number("user_id") == user.InternalID && client != "" && client == lock.text("client_session_id")
	if lock["user_id"] != nil {
		owner, err := queryRecord(ctx, db, `SELECT jsonb_build_object('id',u.id,'login',u.login,'first_name',i.first_name,'last_name',i.last_name) FROM users u LEFT JOIN user_info i ON i.id=u.id WHERE u.id=$1`, lock["user_id"])
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
		if owner != nil {
			value["owner"] = map[string]any(owner)
		}
	}
	return value, nil
}

func scenarioLockRow(ctx context.Context, db runtimeDB, id any, forUpdate bool) (record, error) {
	query := `SELECT to_jsonb(l) FROM scenario_edit_lock l WHERE scenario_id=$1`
	if forUpdate {
		query += ` FOR UPDATE`
	}
	row, err := queryRecord(ctx, db, query, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return row, err
}

func (s *Service) readScenarioLock(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "scenario_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(u)
	if err != nil {
		return err
	}
	ctx := r.Context()
	row, err := scenarioGet(ctx, s.Auth.DB, path["scenario_id"], airline, aircraft, true, false)
	if err != nil {
		return err
	}
	lock, err := scenarioLockRow(ctx, s.Auth.DB, row["id"], false)
	if err != nil {
		return err
	}
	value, err := scenarioLockDTO(ctx, s.Auth.DB, row["id"], lock, time.Now().UTC(), r.Header.Get("X-Client-Session-Id"), u)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(value))
	return nil
}

func (s *Service) acquireScenarioLock(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := platform.Schema{Fields: []platform.Field{{Name: "client_session_id", Alias: "clientSessionId", Kind: "string", Required: true, Max: 80}, {Name: "force", Kind: "boolean", Default: false}}}
	path, body, err := libraryInput(r, &schema, "scenario_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(u)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	row, err := scenarioGet(ctx, tx, path["scenario_id"], airline, aircraft, true, false)
	if err != nil {
		return err
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	expires := now.Add(s.Auth.Config.ScenarioLockTTL)
	var lockID int64
	err = tx.QueryRow(ctx, `INSERT INTO scenario_edit_lock(scenario_id,user_id,client_session_id,expires_at) VALUES($1,$2,$3,$4)
ON CONFLICT(scenario_id) DO UPDATE SET user_id=EXCLUDED.user_id,client_session_id=EXCLUDED.client_session_id,expires_at=EXCLUDED.expires_at,updated_at=now()
WHERE $5 OR scenario_edit_lock.expires_at<=$6 OR (scenario_edit_lock.user_id=$2 AND scenario_edit_lock.client_session_id=$3) RETURNING id`, row["id"], u.InternalID, body.String("client_session_id"), expires, body.Bool("force"), now).Scan(&lockID)
	conflict := errors.Is(err, pgx.ErrNoRows)
	if err != nil && !conflict {
		return err
	}
	lock, err := scenarioLockRow(ctx, tx, row["id"], false)
	if err != nil {
		return err
	}
	value, err := scenarioLockDTO(ctx, tx, row["id"], lock, now, body.String("client_session_id"), u)
	if err != nil {
		return err
	}
	if conflict {
		return &platform.APIError{Status: 423, Code: "SCENARIO_LOCKED", Message: "Scenario is currently being edited", Extra: map[string]any{"lock": map[string]any(value)}}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	// The source tests expiration again after commit, including TTL <= 0.
	if !expires.After(time.Now().UTC()) {
		value = record{"scenario_id": row["id"], "is_locked": false, "expires_at": nil, "owner": nil, "is_owner": false}
	}
	platform.WriteJSON(w, 200, commanderWire(value))
	return nil
}

func (s *Service) releaseScenarioLock(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, pathErr := libraryInput(r, nil, "scenario_id")
	_, present := r.Header[http.CanonicalHeaderKey("X-Client-Session-Id")]
	if !present {
		details := []any{}
		var prior *platform.APIError
		if errors.As(pathErr, &prior) && prior.Code == "VALIDATION_ERROR" {
			details = append(details, prior.Extra["details"].([]any)...)
		} else if pathErr != nil {
			return pathErr
		}
		details = append(details, platform.Detail("missing", "Field required", []any{"header", "X-Client-Session-Id"}, nil, nil))
		return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": details}}
	}
	if pathErr != nil {
		return pathErr
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(u)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	row, err := scenarioGet(ctx, tx, path["scenario_id"], airline, aircraft, true, false)
	if err != nil {
		return err
	}
	lock, err := scenarioLockRow(ctx, tx, row["id"], true)
	if err != nil {
		return err
	}
	if lock != nil {
		expires, err := time.Parse(time.RFC3339Nano, lock.text("expires_at"))
		if err != nil {
			return err
		}
		if expires.After(time.Now().UTC()) && (lock.number("user_id") != u.InternalID || lock.text("client_session_id") != r.Header.Get("X-Client-Session-Id")) {
			return commanderError(423, "SCENARIO_LOCKED", "Scenario lock is held by another user")
		}
		if _, err = tx.Exec(ctx, "DELETE FROM scenario_edit_lock WHERE id=$1", lock["id"]); err != nil {
			return err
		}
		if err = tx.Commit(ctx); err != nil {
			return err
		}
	}
	w.WriteHeader(204)
	return nil
}
