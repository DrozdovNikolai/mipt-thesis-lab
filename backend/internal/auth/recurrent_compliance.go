package auth

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func (s *Service) registerRecurrentCompliance(mux *platform.Router) {
	p := s.Config.APIPrefix + "/users/me/recurrent-compliance"
	mux.HandleFunc("GET "+p, platform.Wrap(s.getRecurrentCompliance))
	mux.HandleFunc("POST "+p, platform.Wrap(s.writeRecurrentCompliance(true)))
	mux.HandleFunc("PUT "+p, platform.Wrap(s.writeRecurrentCompliance(false)))
}

func recurrentAircraft(user *User) []int64 {
	ids := []int64{}
	for _, id := range user.AircraftIDs {
		if id > 0 {
			ids = append(ids, id)
		}
	}
	return ids
}

func recurrentLink(ctx context.Context, tx pgx.Tx, user int64) (*int64, error) {
	var id int64
	err := tx.QueryRow(ctx, `SELECT compliance_id FROM user_recurrent_compliance WHERE user_id=$1`, user).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return &id, err
}

func recurrentAccessible(ctx context.Context, tx pgx.Tx, user *User, id any) (bool, error) {
	aircraft := recurrentAircraft(user)
	if user.AirlineID == nil || *user.AirlineID <= 0 || len(aircraft) == 0 {
		return false, nil
	}
	var found bool
	err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM scenario_content_set WHERE id=$1 AND airline_id=$2 AND aircraft_id=ANY($3::bigint[]))`, id, *user.AirlineID, aircraft).Scan(&found)
	return found, err
}

func recurrentResponse(w http.ResponseWriter, status int, user *User, id any) {
	platform.WriteJSON(w, status, map[string]any{"userId": user.ID, "complianceId": id})
}

// The source GET repairs an inaccessible preference or creates the default.
// Keep that write in one transaction, without an upsert that would change races.
func (s *Service) getRecurrentCompliance(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	current, err := recurrentLink(ctx, tx, user.InternalID)
	if err != nil {
		return err
	}
	if current != nil {
		accessible, err := recurrentAccessible(ctx, tx, user, *current)
		if err != nil {
			return err
		}
		if accessible {
			recurrentResponse(w, http.StatusOK, user, current)
			return nil
		}
	}
	var next *int64
	aircraft := recurrentAircraft(user)
	if user.AirlineID != nil && *user.AirlineID > 0 && len(aircraft) != 0 {
		var id int64
		err := tx.QueryRow(ctx, `SELECT id FROM scenario_content_set WHERE airline_id=$1 AND aircraft_id=ANY($2::bigint[]) ORDER BY aircraft_id,name,id LIMIT 1`, *user.AirlineID, aircraft).Scan(&id)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if err == nil {
			next = &id
		}
	}
	switch {
	case current == nil && next == nil:
		recurrentResponse(w, http.StatusOK, user, nil)
		return nil
	case next == nil:
		_, err = tx.Exec(ctx, `DELETE FROM user_recurrent_compliance WHERE user_id=$1`, user.InternalID)
	case current == nil:
		_, err = tx.Exec(ctx, `INSERT INTO user_recurrent_compliance(user_id,compliance_id) VALUES($1,$2)`, user.InternalID, *next)
	default:
		_, err = tx.Exec(ctx, `UPDATE user_recurrent_compliance SET compliance_id=$1 WHERE user_id=$2`, *next, user.InternalID)
	}
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	recurrentResponse(w, http.StatusOK, user, next)
	return nil
}

func (s *Service) writeRecurrentCompliance(create bool) platform.Handler {
	return func(w http.ResponseWriter, r *http.Request) error {
		body, bodyErr := platform.ReadObject(r, platform.Field{Name: "compliance_id", Alias: "complianceId", Kind: "integer", Required: true, Min: 1, AllowBigInteger: true})
		// FastAPI decodes JSON before dependencies, then validates the model
		// after authentication. Preserve that order for malformed bodies.
		var validation *platform.APIError
		if errors.As(bodyErr, &validation) && validation.Code == "VALIDATION_ERROR" {
			if details, ok := validation.Extra["details"].([]any); ok && len(details) != 0 {
				if first, ok := details[0].(map[string]any); ok && first["type"] == "json_invalid" {
					return bodyErr
				}
			}
		}
		user, err := s.Authenticate(r)
		if err != nil {
			return err
		}
		if bodyErr != nil {
			return bodyErr
		}
		ctx := r.Context()
		tx, err := s.DB.Begin(ctx)
		if err != nil {
			return err
		}
		defer tx.Rollback(ctx)
		current, err := recurrentLink(ctx, tx, user.InternalID)
		if err != nil {
			return err
		}
		if create && current != nil {
			return platform.Error(409, "Recurrent compliance is already configured for this user")
		}
		if !create && current == nil {
			return platform.Error(404, "Recurrent compliance is not configured for this user")
		}
		if user.AirlineID == nil || *user.AirlineID <= 0 {
			return &platform.APIError{Status: 400, Code: "AIRLINE_REQUIRED", Message: "User is not assigned to an airline"}
		}
		if len(recurrentAircraft(user)) == 0 {
			return platform.Error(400, "User is not assigned to any aircraft")
		}
		id := body["compliance_id"]
		accessible, err := recurrentAccessible(ctx, tx, user, id)
		if err != nil {
			return err
		}
		if !accessible {
			return platform.Error(404, "Compliance table not found")
		}
		status := http.StatusOK
		if create {
			_, err = tx.Exec(ctx, `INSERT INTO user_recurrent_compliance(user_id,compliance_id) VALUES($1,$2)`, user.InternalID, id)
			status = http.StatusCreated
		} else if body.Int("compliance_id") != *current {
			_, err = tx.Exec(ctx, `UPDATE user_recurrent_compliance SET compliance_id=$1 WHERE user_id=$2`, id, user.InternalID)
		}
		if err != nil {
			return err
		}
		if err = tx.Commit(ctx); err != nil {
			return err
		}
		recurrentResponse(w, status, user, id)
		return nil
	}
}
