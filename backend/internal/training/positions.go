package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"unicode"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/platform"
)

func (s *Service) registerPositions(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix
	mux.HandleFunc("GET "+p+"/training/positions", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.listPositions(w, r, false) }))
	mux.HandleFunc("GET "+p+"/users/positions", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.listPositions(w, r, true) }))
	mux.HandleFunc("POST "+p+"/training/positions", platform.Wrap(s.createPosition))
	mux.HandleFunc("PUT "+p+"/training/positions/{position_id}", platform.Wrap(s.updatePosition))
	mux.HandleFunc("DELETE "+p+"/training/positions/{position_id}", platform.Wrap(s.deletePosition))
}

func (s *Service) listPositions(w http.ResponseWriter, r *http.Request, userView bool) error {
	privileges := []string{"training:read"}
	if userView {
		privileges = nil
	}
	u, err := s.Auth.Authenticate(r, privileges...)
	if err != nil {
		return err
	}
	var airline any = u.AirlineID
	columns := "id,airline_id,name,created_at,updated_at"
	if userView {
		airline, err = commanderAirline(u)
		columns = "id,airline_id,name,created_at"
	} else {
		var q platform.Object
		q, err = platform.QueryObject(r.URL.Query(), platform.Field{Name: "airline_id", Alias: "airlineId", Kind: "integer", Nullable: true})
		if q["airline_id"] != nil {
			airline = q["airline_id"]
		}
	}
	if err != nil {
		return err
	}
	items, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(p) FROM (SELECT "+columns+" FROM airline_position WHERE airline_id=$1 ORDER BY lower(name),id) p", airline)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(items))
	return nil
}

func positionSchema(create bool) platform.Schema {
	fields := []platform.Field{{Name: "name", Kind: "string", Min: 1, Max: 100, Required: create, Nullable: !create}}
	if create {
		fields = append(fields, platform.Field{Name: "airline_id", Alias: "airlineId", Kind: "integer", Required: true})
	}
	return platform.Schema{Fields: fields}
}

func positionID(r *http.Request) (int64, error) {
	id, err := platform.ValidateObject(map[string]any{"position_id": r.PathValue("position_id")}, []any{"path"}, platform.Schema{Fields: []platform.Field{{Name: "position_id", Kind: "integer", Required: true}}})
	return id.Int("position_id"), err
}

func positionInput(r *http.Request) (int64, platform.Object, error) {
	path, body, err := platform.ReadPathAndBody(r, platform.Schema{Fields: []platform.Field{{Name: "position_id", Kind: "integer", Required: true}}}, positionSchema(false))
	return path.Int("position_id"), body, err
}

func positionName(ctx context.Context, db runtimeDB, airline, exclude any, raw string) (string, string, error) {
	name := strings.Join(strings.FieldsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }), " ")
	if name == "" {
		return "", "", platform.Error(400, "Position name is required")
	}
	normalized := cases.Lower(language.Und).String(name)
	var exists bool
	if err := db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM airline_position WHERE airline_id IS NOT DISTINCT FROM $1::bigint AND normalized_name=$2 AND ($3::bigint IS NULL OR id<>$3))`, airline, normalized, exclude).Scan(&exists); err != nil {
		return "", "", err
	}
	if exists {
		return "", "", platform.Error(400, "Position already exists")
	}
	return name, normalized, nil
}

func writePosition(w http.ResponseWriter, status int, row record) error {
	// The training DTO rejects legacy unassigned positions after the source has
	// committed. The users DTO has a separate nullable airline field.
	if row["airline_id"] == nil {
		return fmt.Errorf("position response requires an airline")
	}
	platform.WriteJSON(w, status, commanderWire(row.project("id airline_id name created_at updated_at")))
	return nil
}

func (s *Service) createPosition(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, positionSchema(true))
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	var exists bool
	if err = tx.QueryRow(r.Context(), "SELECT EXISTS(SELECT 1 FROM airline WHERE id=$1)", body.Int("airline_id")).Scan(&exists); err != nil {
		return err
	}
	if !exists {
		return platform.Error(404, "Airline not found")
	}
	name, normalized, err := positionName(r.Context(), tx, body["airline_id"], nil, body.String("name"))
	if err != nil {
		return err
	}
	row, err := queryRecord(r.Context(), tx, `INSERT INTO airline_position(airline_id,name,normalized_name) VALUES($1,$2,$3) RETURNING to_jsonb(airline_position)`, body["airline_id"], name, normalized)
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	return writePosition(w, 201, row)
}

func lockPosition(ctx context.Context, tx pgx.Tx, id int64) (record, error) {
	row, err := queryRecord(ctx, tx, "SELECT to_jsonb(p) FROM airline_position p WHERE id=$1 FOR UPDATE", id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, platform.Error(404, "Position not found")
	}
	return row, err
}

func (s *Service) updatePosition(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	id, body, err := positionInput(r)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	row, err := lockPosition(r.Context(), tx, id)
	if err != nil {
		return err
	}
	if body["name"] != nil {
		var airline any
		if row["airline_id"] != nil {
			airline = row.number("airline_id")
		}
		name, normalized, err := positionName(r.Context(), tx, airline, id, body.String("name"))
		if err != nil {
			return err
		}
		if row.text("name") != name || row.text("normalized_name") != normalized {
			row, err = queryRecord(r.Context(), tx, `UPDATE airline_position SET name=$1,normalized_name=$2,updated_at=now() WHERE id=$3 RETURNING to_jsonb(airline_position)`, name, normalized, id)
			if err != nil {
				return err
			}
		}
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	return writePosition(w, 200, row)
}

func (s *Service) deletePosition(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	id, err := positionID(r)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	if _, err = lockPosition(r.Context(), tx, id); err != nil {
		return err
	}
	var assigned bool
	if err = tx.QueryRow(r.Context(), "SELECT EXISTS(SELECT 1 FROM user_info WHERE position_id=$1)", id).Scan(&assigned); err != nil {
		return err
	}
	if assigned {
		return platform.Error(400, "Position is assigned to users")
	}
	if _, err = tx.Exec(r.Context(), "DELETE FROM airline_position WHERE id=$1", id); err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
