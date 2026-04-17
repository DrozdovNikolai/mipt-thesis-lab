package auth

import (
	"context"

	"github.com/google/uuid"
)

// Administrative responses use the source selectin relationship order and
// validate nested role DTOs after commit. Authentication keeps its own reader.
func (s *Service) userAdminReads(ctx context.Context, publicIDs []uuid.UUID) ([]*User, error) {
	loaded, err := s.LoadUsers(ctx, publicIDs)
	if err != nil {
		return nil, err
	}
	out, ids := []*User{}, []int64{}
	for _, publicID := range publicIDs {
		if user := loaded[publicID]; user != nil {
			out, ids = append(out, user), append(ids, user.InternalID)
			user.Roles = []Role{}
		}
	}
	if len(ids) == 0 {
		return out, nil
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	roles, byRole, byUser := []*rbacEntry{}, map[int64]*rbacEntry{}, map[int64][]*rbacEntry{}
	for start := 0; start < len(ids); start += 500 {
		rows, err := tx.Query(ctx, `SELECT u.id,r.id,r.public_id,r.name,r.description,r.created_at FROM users u JOIN user_roles l ON l.user_id=u.id JOIN roles r ON r.id=l.role_id WHERE u.id=ANY($1::bigint[])`, ids[start:min(start+500, len(ids))])
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var owner int64
			entry := &rbacEntry{Role: Role{Privileges: []Privilege{}}}
			if err := rows.Scan(&owner, &entry.internalID, &entry.ID, &entry.Name, &entry.Description, &entry.CreatedAt); err != nil {
				rows.Close()
				return nil, err
			}
			if existing := byRole[entry.internalID]; existing != nil {
				entry = existing
			} else {
				byRole[entry.internalID] = entry
				roles = append(roles, entry)
			}
			byUser[owner] = append(byUser[owner], entry)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	if err := rbacListPrivileges(ctx, tx, roles); err != nil {
		return nil, err
	}
	for _, user := range out {
		privileges := map[string]bool{}
		for _, entry := range byUser[user.InternalID] {
			value, err := rbacDTO(entry, true)
			if err != nil {
				return nil, err
			}
			user.Roles = append(user.Roles, value.(Role))
			for _, privilege := range entry.Privileges {
				privileges[privilege.Name] = true
			}
		}
		user.Privileges = []string{}
		for name := range privileges {
			user.Privileges = append(user.Privileges, name)
		}
		sortStrings(user.Privileges)
	}
	return out, nil
}
