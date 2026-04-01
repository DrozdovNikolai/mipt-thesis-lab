package auth

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

type rbacEntry struct {
	internalID int64
	Role
}

func (s *Service) registerRBAC(mux *platform.Router) {
	for _, role := range []bool{false, true} {
		table, parameter, _ := rbacNames(role)
		p := s.Config.APIPrefix + "/" + table
		mux.HandleFunc("GET "+p+"/{$}", platform.Wrap(s.listRBAC(role)))
		mux.HandleFunc("POST "+p+"/{$}", platform.Wrap(s.writeRBAC(role, true)))
		mux.HandleFunc("PUT "+p+"/{"+parameter+"}", platform.Wrap(s.writeRBAC(role, false)))
		mux.HandleFunc("DELETE "+p+"/{"+parameter+"}", platform.Wrap(s.deleteRBAC(role)))
	}
}

func rbacNames(role bool) (table, parameter, label string) {
	if role {
		return "roles", "role_id", "Role"
	}
	return "privileges", "privilege_id", "Privilege"
}

func rbacSchema(role, create bool) platform.Schema {
	fields := []platform.Field{
		{Name: "name", Kind: "string", Required: create, Nullable: !create, Min: 1, Max: 100},
		{Name: "description", Kind: "string", Nullable: true},
	}
	if role {
		field := platform.Field{Name: "privileges", Kind: "list", Nullable: !create, Item: &platform.Field{Kind: "string"}}
		if create {
			field.Default = []any{}
		}
		fields = append(fields, field)
	}
	return platform.Schema{Fields: fields}
}

func scanRBAC(row pgx.Row) (*rbacEntry, error) {
	entry := &rbacEntry{Role: Role{Privileges: []Privilege{}}}
	err := row.Scan(&entry.internalID, &entry.ID, &entry.Name, &entry.Description, &entry.CreatedAt)
	return entry, err
}

func findRBAC(ctx context.Context, tx pgx.Tx, table, column string, value any) (*rbacEntry, error) {
	entry, err := scanRBAC(tx.QueryRow(ctx, `SELECT id,public_id,name,description,created_at FROM `+table+` WHERE `+column+`=$1`, value))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return entry, err
}

func rbacPrivilege(entry *rbacEntry) Privilege {
	return Privilege{ID: entry.ID, Name: entry.Name, Description: entry.Description, CreatedAt: entry.CreatedAt}
}

func rbacReadPrivileges(ctx context.Context, tx pgx.Tx, entry *rbacEntry) error {
	rows, err := tx.Query(ctx, `SELECT p.id,p.public_id,p.name,p.description,p.created_at FROM privileges p JOIN role_privileges rp ON p.id=rp.privilege_id WHERE rp.role_id=$1`, entry.internalID)
	if err != nil {
		return err
	}
	defer rows.Close()
	entry.Privileges = []Privilege{}
	for rows.Next() {
		p, err := scanRBAC(rows)
		if err != nil {
			return err
		}
		entry.Privileges = append(entry.Privileges, rbacPrivilege(p))
	}
	return rows.Err()
}

func rbacDTO(entry *rbacEntry, role bool) (any, error) {
	valid := func(name string) bool { n := utf8.RuneCountInString(name); return n >= 1 && n <= 100 }
	if !valid(entry.Name) {
		return nil, fmt.Errorf("invalid RBAC response name")
	}
	if !role {
		return rbacPrivilege(entry), nil
	}
	for _, privilege := range entry.Privileges {
		if !valid(privilege.Name) {
			return nil, fmt.Errorf("invalid role privilege response name")
		}
	}
	return entry.Role, nil
}

func (s *Service) listRBAC(role bool) platform.Handler {
	return func(w http.ResponseWriter, r *http.Request) error {
		table, _, _ := rbacNames(role)
		if _, err := s.Authenticate(r, table+":read"); err != nil {
			return err
		}
		ctx := r.Context()
		tx, err := s.DB.Begin(ctx)
		if err != nil {
			return err
		}
		defer tx.Rollback(ctx)
		rows, err := tx.Query(ctx, `SELECT id,public_id,name,description,created_at FROM `+table)
		if err != nil {
			return err
		}
		entries := []*rbacEntry{}
		for rows.Next() {
			entry, err := scanRBAC(rows)
			if err != nil {
				rows.Close()
				return err
			}
			entries = append(entries, entry)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
		out := []any{}
		if role {
			if err := rbacListPrivileges(ctx, tx, entries); err != nil {
				return err
			}
		}
		for _, entry := range entries {
			value, err := rbacDTO(entry, role)
			if err != nil {
				return err
			}
			out = append(out, value)
		}
		platform.WriteJSON(w, 200, out)
		return nil
	}
}

// Match the source selectin loader's batches without issuing a query per role.
func rbacListPrivileges(ctx context.Context, tx pgx.Tx, entries []*rbacEntry) error {
	for start := 0; start < len(entries); start += 500 {
		end := min(start+500, len(entries))
		ids := []int64{}
		owners := map[int64]*rbacEntry{}
		for _, entry := range entries[start:end] {
			ids = append(ids, entry.internalID)
			owners[entry.internalID] = entry
		}
		rows, err := tx.Query(ctx, `SELECT r.id,p.public_id,p.name,p.description,p.created_at FROM roles r JOIN role_privileges rp ON r.id=rp.role_id JOIN privileges p ON p.id=rp.privilege_id WHERE r.id=ANY($1::bigint[])`, ids)
		if err != nil {
			return err
		}
		for rows.Next() {
			var id int64
			var privilege Privilege
			if err := rows.Scan(&id, &privilege.ID, &privilege.Name, &privilege.Description, &privilege.CreatedAt); err != nil {
				rows.Close()
				return err
			}
			owners[id].Privileges = append(owners[id].Privileges, privilege)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
	}
	return nil
}
