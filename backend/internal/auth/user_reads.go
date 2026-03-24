package auth

import (
	"context"
	"encoding/json"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
)

// LoadUsers reads a whole page with three queries, including roles/privileges and
// aircraft. LoadUser uses the same projection for authentication and profiles.
func (s *Service) LoadUsers(ctx context.Context, publicIDs []uuid.UUID) (map[uuid.UUID]*User, error) {
	users := map[uuid.UUID]*User{}
	if len(publicIDs) == 0 {
		return users, nil
	}
	rows, err := s.DB.Query(ctx, `SELECT u.id,u.public_id,u.login,u.email,u.hashed_password,u.is_active,u.must_change_password,u.created_at,u.airline_id,
 i.first_name,i.last_name,i.date_of_birth::text,p.id,p.name,i.license_number,i.phone,i.photo_url,i.signature_url
 FROM users u LEFT JOIN user_info i ON i.id=u.id LEFT JOIN airline_position p ON p.id=i.position_id WHERE u.public_id=ANY($1::uuid[])`, publicIDs)
	if err != nil {
		return nil, err
	}
	internal := map[int64]*User{}
	ids := []int64{}
	for rows.Next() {
		u := &User{Roles: []Role{}, Privileges: []string{}, AircraftIDs: []int64{}, AircraftCodes: []string{}}
		if err = rows.Scan(&u.InternalID, &u.ID, &u.Login, &u.Email, &u.HashedPassword, &u.IsActive, &u.MustChangePassword, &u.CreatedAt, &u.AirlineID, &u.FirstName, &u.LastName, &u.DateOfBirth, &u.PositionID, &u.Position, &u.LicenseNumber, &u.Phone, &u.PhotoURL, &u.SignatureURL); err != nil {
			rows.Close()
			return nil, err
		}
		if u.Position != nil {
			name := strings.Join(strings.FieldsFunc(*u.Position, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }), " ")
			if name == "" {
				u.Position = nil
			} else {
				u.Position = &name
			}
		}
		users[u.ID], internal[u.InternalID] = u, u
		ids = append(ids, u.InternalID)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(ids) == 0 {
		return users, nil
	}
	rows, err = s.DB.Query(ctx, `SELECT ur.user_id,jsonb_agg(jsonb_build_object('id',r.public_id,'name',r.name,'description',r.description,'createdAt',r.created_at,
 'privileges',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',p.public_id,'name',p.name,'description',p.description,'createdAt',p.created_at) ORDER BY p.id),'[]'::jsonb)
 FROM role_privileges rp JOIN privileges p ON p.id=rp.privilege_id WHERE rp.role_id=r.id)) ORDER BY r.id)
 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=ANY($1::bigint[]) GROUP BY ur.user_id`, ids)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var id int64
		var raw []byte
		if err = rows.Scan(&id, &raw); err != nil {
			rows.Close()
			return nil, err
		}
		u := internal[id]
		if err = json.Unmarshal(raw, &u.Roles); err != nil {
			rows.Close()
			return nil, err
		}
		privileges := map[string]bool{}
		for _, role := range u.Roles {
			for _, p := range role.Privileges {
				privileges[p.Name] = true
			}
		}
		for name := range privileges {
			u.Privileges = append(u.Privileges, name)
		}
		sortStrings(u.Privileges)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	rows, err = s.DB.Query(ctx, `SELECT DISTINCT ua.user_id,a.id,a.code FROM user_aircraft ua JOIN aircraft_airline a ON a.id=ua.aircraft_id WHERE ua.user_id=ANY($1::bigint[]) ORDER BY ua.user_id,a.id`, ids)
	if err != nil {
		return nil, err
	}
	codes := map[int64]map[string]bool{}
	for rows.Next() {
		var userID, id int64
		var code string
		if err = rows.Scan(&userID, &id, &code); err != nil {
			rows.Close()
			return nil, err
		}
		u := internal[userID]
		u.AircraftIDs = append(u.AircraftIDs, id)
		if code != "" {
			if codes[userID] == nil {
				codes[userID] = map[string]bool{}
			}
			codes[userID][code] = true
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	for id, values := range codes {
		for code := range values {
			internal[id].AircraftCodes = append(internal[id].AircraftCodes, code)
		}
		sortStrings(internal[id].AircraftCodes)
	}
	return users, nil
}

// Pydantic emits six fractional digits for a non-integral UTC datetime.
func userTimestamp(value time.Time) string {
	if value.Nanosecond() == 0 {
		return value.Format(time.RFC3339)
	}
	return value.Format("2006-01-02T15:04:05.000000Z07:00")
}
func (u User) MarshalJSON() ([]byte, error) {
	type wire User
	return json.Marshal(struct {
		*wire
		CreatedAt string `json:"createdAt"`
	}{(*wire)(&u), userTimestamp(u.CreatedAt)})
}
func (r Role) MarshalJSON() ([]byte, error) {
	type wire Role
	return json.Marshal(struct {
		*wire
		CreatedAt string `json:"createdAt"`
	}{(*wire)(&r), userTimestamp(r.CreatedAt)})
}
func (p Privilege) MarshalJSON() ([]byte, error) {
	type wire Privilege
	return json.Marshal(struct {
		*wire
		CreatedAt string `json:"createdAt"`
	}{(*wire)(&p), userTimestamp(p.CreatedAt)})
}
