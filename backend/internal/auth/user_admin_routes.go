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
