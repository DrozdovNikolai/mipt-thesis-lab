package auth

import (
	"context"
	"net/http"
	"reflect"

	"github.com/google/uuid"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

var userAdminProfileFields = []string{"first_name", "last_name", "date_of_birth", "license_number", "phone"}

func (s *Service) registerUserAdmin(mux *platform.Router) {
	p := s.Config.APIPrefix + "/users"
	mux.HandleFunc("GET "+p+"/{$}", platform.Wrap(s.listUserAdmin))
	mux.HandleFunc("POST "+p+"/{$}", platform.Wrap(s.createUserAdmin))
	mux.HandleFunc("PUT "+p+"/{user_id}", platform.Wrap(s.updateUserAdmin))
	mux.HandleFunc("PUT "+p+"/{user_id}/roles", platform.Wrap(s.rolesUserAdmin))
	mux.HandleFunc("DELETE "+p+"/{user_id}", platform.Wrap(s.deleteUserAdmin))
}

func (s *Service) listUserAdmin(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Authenticate(r, "users:read"); err != nil {
		return err
	}
	rows, err := s.DB.Query(r.Context(), `SELECT u.public_id FROM users u LEFT JOIN user_info i ON i.id=u.id LEFT JOIN airline_position p ON p.id=i.position_id`)
	if err != nil {
		return err
	}
	ids := []uuid.UUID{}
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	users, err := s.userAdminReads(r.Context(), ids)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, users)
	return nil
}

func (s *Service) writeUserAdmin(w http.ResponseWriter, ctx context.Context, publicID string, status int) error {
	id, err := uuid.Parse(publicID)
	if err != nil {
		return err
	}
	users, err := s.userAdminReads(ctx, []uuid.UUID{id})
	if err != nil {
		return err
	}
	if len(users) == 0 {
		return platform.Error(500, "User not found")
	}
	platform.WriteJSON(w, status, users[0])
	return nil
}

func (s *Service) createUserAdmin(w http.ResponseWriter, r *http.Request) error {
	body, err := s.rbacBody(r, "users", userAdminSchema(true))
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	for _, field := range []string{"login", "email"} {
		if err := userAdminUnique(ctx, tx, field, body[field]); err != nil {
			return err
		}
	}
	roles, err := userAdminResolveRoles(ctx, tx, body["roles"].([]any))
	if err != nil {
		return err
	}
	if err := userAdminAirline(ctx, tx, body["airline_id"]); err != nil {
		return err
	}
	position, err := userAdminPosition(ctx, tx, body["airline_id"], body["position_id"], "")
	if err != nil {
		return err
	}
	hash, err := HashPassword(body.String("password"))
	if err != nil {
		return platform.Error(400, "Failed to hash password")
	}
	publicID := uuid.New()
	id, err := userAdminWriteRow(ctx, tx, "users", userAdminRow{"public_id": publicID, "login": body["login"], "email": body["email"], "hashed_password": hash, "airline_id": body["airline_id"]}, nil)
	if err != nil {
		return err
	}
	info := userAdminRow{"id": id, "position_id": position}
	for _, field := range userAdminProfileFields {
		info[field] = body[field]
	}
	if _, err := userAdminWriteRow(ctx, tx, "user_info", info, nil); err != nil {
		return err
	}
	if err := userAdminReplaceRoles(ctx, tx, id, roles); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	// Source commits the account/profile/roles before resolving aircraft. A
	// failure in this second transaction deliberately leaves the account intact.
	assign, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer assign.Rollback(ctx)
	aircraft, err := userAdminAircraft(ctx, assign, body["airline_id"], body["aircraft_ids"].([]any), func() error { return nil })
	if err != nil {
		return err
	}
	if len(aircraft) > 0 {
		if err := userAdminAssignAircraft(ctx, assign, id, aircraft); err != nil {
			return err
		}
		if err := assign.Commit(ctx); err != nil {
			return err
		}
	}
	return s.writeUserAdmin(w, ctx, publicID.String(), 201)
}

func (s *Service) updateUserAdmin(w http.ResponseWriter, r *http.Request) error {
	body, err := s.rbacBody(r, "users", userAdminSchema(false))
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	user, err := userAdminFind(ctx, tx, r.PathValue("user_id"))
	if err != nil {
		return err
	}
	id := user["id"].(int64)
	info, err := readUserAdminRow(tx.QueryRow(ctx, `SELECT to_jsonb(i) FROM user_info i WHERE id=$1`, id))
	if err != nil {
		return err
	}
	profileExists := info != nil
	if info == nil {
		info = userAdminRow{}
	}
	var oldPosition string
	if info["position_id"] != nil {
		position, err := readUserAdminRow(tx.QueryRow(ctx, `SELECT to_jsonb(p) FROM airline_position p WHERE id=$1`, info["position_id"]))
		if err != nil {
			return err
		}
		if position != nil {
			oldPosition, _ = position["name"].(string)
		}
	}
	changes, profile := userAdminRow{}, userAdminRow{}
	needProfile := false
	flush := func() error {
		if _, err := userAdminWriteRow(ctx, tx, "users", changes, id); err != nil {
			return err
		}
		changes = userAdminRow{}
		if !profileExists && needProfile {
			profile["id"] = id
			if _, err := userAdminWriteRow(ctx, tx, "user_info", profile, nil); err != nil {
				return err
			}
			profileExists = true
		} else if profileExists {
			if _, err := userAdminWriteRow(ctx, tx, "user_info", profile, id); err != nil {
				return err
			}
		}
		profile = userAdminRow{}
		return nil
	}
	for _, field := range []string{"login", "email"} {
		if next := body.String(field); next != "" && next != user[field] {
			if err := flush(); err != nil {
				return err
			}
			if err := userAdminUnique(ctx, tx, field, next); err != nil {
				return err
			}
			changes[field] = next
		}
	}
	airline := user["airline_id"]
	airlineChanged := body.Has("airline_id") && !reflect.DeepEqual(body["airline_id"], airline)
	if airlineChanged {
		if body["airline_id"] != nil {
			if err := flush(); err != nil {
				return err
			}
			if err := userAdminAirline(ctx, tx, body["airline_id"]); err != nil {
				return err
			}
		}
		airline = body["airline_id"]
		changes["airline_id"] = airline
	}
	if password := body.String("password"); password != "" {
		hash, err := HashPassword(password)
		if err != nil {
			return err
		}
		changes["hashed_password"], changes["must_change_password"] = hash, false
	}
	for _, field := range userAdminProfileFields {
		if body.Has(field) {
			profile[field], needProfile = body[field], true
		}
	}
	if body.Has("position_id") {
		needProfile = true
		if body["position_id"] != nil {
			if err := flush(); err != nil {
				return err
			}
		}
		position, err := userAdminPosition(ctx, tx, airline, body["position_id"], "")
		if err != nil {
			return err
		}
		profile["position_id"] = position
	} else if airlineChanged && profileExists {
		if userPythonTrim(oldPosition) != "" {
			if err := flush(); err != nil {
				return err
			}
		}
		position, err := userAdminPosition(ctx, tx, airline, nil, oldPosition)
		if err != nil {
			return err
		}
		profile["position_id"] = position
	}
	if body["aircraft_ids"] != nil {
		aircraft, err := userAdminAircraft(ctx, tx, airline, body["aircraft_ids"].([]any), flush)
		if err != nil {
			return err
		}
		if err := flush(); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `DELETE FROM user_aircraft WHERE user_id=$1`, id); err != nil {
			return err
		}
		if err := userAdminAssignAircraft(ctx, tx, id, aircraft); err != nil {
			return err
		}
	} else if airlineChanged {
		if err := flush(); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `DELETE FROM user_aircraft WHERE user_id=$1`, id); err != nil {
			return err
		}
	}
	if err := flush(); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	return s.writeUserAdmin(w, ctx, user["public_id"].(string), 200)
}
