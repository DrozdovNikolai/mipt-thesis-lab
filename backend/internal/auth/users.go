package auth

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"north55/backend/internal/platform"
)

type Privilege struct {
	ID          uuid.UUID `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description"`
	CreatedAt   time.Time `json:"createdAt"`
}
type Role struct {
	ID          uuid.UUID   `json:"id"`
	Name        string      `json:"name"`
	Description *string     `json:"description"`
	CreatedAt   time.Time   `json:"createdAt"`
	Privileges  []Privilege `json:"privileges"`
}
type User struct {
	InternalID         int64     `json:"-"`
	ID                 uuid.UUID `json:"id"`
	Login              string    `json:"login"`
	Email              string    `json:"email"`
	HashedPassword     string    `json:"-"`
	IsActive           bool      `json:"isActive"`
	MustChangePassword bool      `json:"mustChangePassword"`
	CreatedAt          time.Time `json:"createdAt"`
	AirlineID          *int64    `json:"airlineId"`
	FirstName          *string   `json:"firstName"`
	LastName           *string   `json:"lastName"`
	DateOfBirth        *string   `json:"dateOfBirth"`
	PositionID         *int64    `json:"positionId"`
	Position           *string   `json:"position"`
	LicenseNumber      *string   `json:"licenseNumber"`
	Phone              *string   `json:"phone"`
	PhotoURL           *string   `json:"photoUrl"`
	SignatureURL       *string   `json:"signatureUrl"`
	Roles              []Role    `json:"roles"`
	Privileges         []string  `json:"privileges"`
	AircraftIDs        []int64   `json:"aircraftIds"`
	AircraftCodes      []string  `json:"aircraftCodes"`
	SessionID          uuid.UUID `json:"-"`
}
type Service struct {
	DB     *pgxpool.Pool
	Config platform.Config
}

func (s *Service) LoadUser(ctx context.Context, publicID uuid.UUID) (*User, error) {
	users, err := s.LoadUsers(ctx, []uuid.UUID{publicID})
	if err != nil {
		return nil, err
	}
	if user := users[publicID]; user != nil {
		return user, nil
	}
	return nil, pgx.ErrNoRows
}

func credentialError() *platform.APIError {
	e := platform.Error(401, "Could not validate credentials")
	e.Headers = http.Header{"WWW-Authenticate": []string{"Bearer"}}
	return e
}
func (s *Service) Authenticate(r *http.Request, privileges ...string) (*User, error) {
	scheme, token, ok := strings.Cut(r.Header.Get("Authorization"), " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || token == "" {
		return nil, credentialError()
	}
	data, err := DecodeToken(s.Config, token, "access")
	if err != nil {
		return nil, credentialError()
	}
	var exists bool
	err = s.DB.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM auth_sessions a JOIN users u ON u.id=a.user_id WHERE a.id=$1 AND u.public_id=$2 AND a.revoked_at IS NULL)`, data.SessionID, data.Subject).Scan(&exists)
	if err != nil {
		return nil, err
	}
	if !exists {
		return nil, credentialError()
	}
	u, err := s.LoadUser(r.Context(), data.Subject)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, credentialError()
	}
	if err != nil {
		return nil, err
	}
	platform.SetRequestUser(r, u.ID.String())
	if !u.IsActive {
		return nil, platform.Error(403, "Inactive user")
	}
	u.SessionID = data.SessionID
	if u.MustChangePassword {
		allow := map[string]bool{s.Config.APIPrefix + "/auth/me": true, s.Config.APIPrefix + "/auth/change-password": true, s.Config.APIPrefix + "/auth/logout": true, s.Config.APIPrefix + "/auth/logout-all": true, s.Config.APIPrefix + "/users/me": true}
		if !allow[r.URL.Path] && !strings.HasPrefix(r.URL.Path, s.Config.APIPrefix+"/auth/logout") {
			return nil, &platform.APIError{Status: 403, Code: "PASSWORD_CHANGE_REQUIRED", Message: "Password change required"}
		}
	}
	owned := map[string]bool{}
	for _, p := range u.Privileges {
		owned[p] = true
	}
	for _, required := range privileges {
		if !owned[required] {
			return nil, platform.Error(403, "Insufficient privileges")
		}
	}
	return u, nil
}

func (s *Service) Bootstrap(ctx context.Context) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	// Serialize repeated startup, including role and user creation in the shared schema.
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(5500152026)`); err != nil {
		return err
	}
	names := []string{"users:read", "users:write", "pilots:read", "pilots:write", "roles:read", "roles:write", "privileges:read", "privileges:write", "training:read", "training:write"}
	for _, name := range names {
		if _, err = tx.Exec(ctx, `INSERT INTO privileges(public_id,name,description) VALUES($1,$2,$3) ON CONFLICT(name) DO NOTHING`, uuid.New(), name, "Default privilege "+name); err != nil {
			return err
		}
	}
	var roleID int64
	err = tx.QueryRow(ctx, `INSERT INTO roles(public_id,name,description) VALUES($1,'admin','Administrator') ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id`, uuid.New()).Scan(&roleID)
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM role_privileges WHERE role_id=$1 AND privilege_id NOT IN (SELECT id FROM privileges WHERE name=ANY($2))`, roleID, names); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO role_privileges(role_id,privilege_id) SELECT $1,id FROM privileges WHERE name=ANY($2) ON CONFLICT DO NOTHING`, roleID, names); err != nil {
		return err
	}
	var userID int64
	var airlineID *int64
	err = tx.QueryRow(ctx, `SELECT id,airline_id FROM users WHERE login=$1`, s.Config.AdminLogin).Scan(&userID, &airlineID)
	if errors.Is(err, pgx.ErrNoRows) {
		hash, e := HashPassword(s.Config.AdminPassword)
		if e != nil {
			return e
		}
		err = tx.QueryRow(ctx, `INSERT INTO users(public_id,login,email,hashed_password,is_active) VALUES($1,$2,$3,$4,true) RETURNING id`, uuid.New(), s.Config.AdminLogin, s.Config.AdminEmail, hash).Scan(&userID)
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, `INSERT INTO user_info(id) VALUES($1)`, userID); err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO user_roles(user_id,role_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, userID, roleID); err != nil {
		return err
	}
	if airlineID == nil {
		var first *int64
		if err = tx.QueryRow(ctx, `SELECT min(id) FROM airline`).Scan(&first); err != nil {
			return err
		}
		if first != nil {
			airlineID = first
			if _, err = tx.Exec(ctx, `UPDATE users SET airline_id=$1,updated_at=now() WHERE id=$2`, airlineID, userID); err != nil {
				return err
			}
		}
	}
	if airlineID != nil {
		var aircraftID int64
		err = tx.QueryRow(ctx, `SELECT id FROM aircraft_airline WHERE airline_id=$1 AND code='DEFAULT' LIMIT 1`, airlineID).Scan(&aircraftID)
		if errors.Is(err, pgx.ErrNoRows) {
			err = tx.QueryRow(ctx, `INSERT INTO aircraft_airline(airline_id,code,name,active,color_hex) VALUES($1,'DEFAULT','Default',true,'#284692') RETURNING id`, airlineID).Scan(&aircraftID)
		}
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, `INSERT INTO user_aircraft(user_id,aircraft_id) VALUES($1,$2) ON CONFLICT(user_id,aircraft_id) DO NOTHING`, userID, aircraftID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}
