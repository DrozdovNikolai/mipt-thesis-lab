package training

import (
	"context"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func competenceSchema(create bool) platform.Schema {
	return platform.Schema{Fields: []platform.Field{
		{Name: "code", Kind: "string", Required: create, Nullable: !create, Max: 50},
		{Name: "name", Kind: "string", Required: create, Nullable: !create, Max: 255},
		{Name: "description", Kind: "string", Nullable: true},
	}}
}

func catalogPathSchema(names ...string) platform.Schema {
	fields := make([]platform.Field, 0, len(names))
	for _, name := range names {
		fields = append(fields, platform.Field{Name: name, Kind: "integer", Required: true})
	}
	return platform.Schema{Fields: fields}
}

func catalogInput(r *http.Request, bodySchema *platform.Schema, names ...string) (platform.Object, platform.Object, error) {
	pathSchema := catalogPathSchema(names...)
	if bodySchema != nil {
		return platform.ReadPathAndBody(r, pathSchema, *bodySchema)
	}
	raw := map[string]any{}
	for _, name := range names {
		raw[name] = r.PathValue(name)
	}
	path, err := platform.ValidateObject(raw, []any{"path"}, pathSchema)
	return path, nil, err
}

func catalogUniqueCode(ctx context.Context, db runtimeDB, indicator bool, owner int64, exclude any, code string) error {
	table, ownerColumn := "competence", "airline_id"
	if indicator {
		table, ownerColumn = "behavioural_indicator", "competence_id"
	}
	var exists bool
	if err := db.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM "+table+" WHERE "+ownerColumn+"=$1 AND code=$2 AND ($3::bigint IS NULL OR id<>$3))", owner, code, exclude).Scan(&exists); err != nil {
		return err
	}
	if exists {
		if indicator {
			return commanderError(400, "BEHAVIOURAL_INDICATOR_CODE_EXISTS", "Behavioural indicator code already exists")
		}
		return commanderError(400, "COMPETENCE_CODE_EXISTS", "Competence code already exists")
	}
	return nil
}

// Only explicit server-side column lists enter SQL; omitted values do not write.
// A supplied null is preserved, including a resulting NOT NULL failure.
func updateCatalogRow(ctx context.Context, tx pgx.Tx, table string, row record, body platform.Object, fields []string) (record, error) {
	if table != "competence" && table != "behavioural_indicator" {
		return nil, fmt.Errorf("unsupported catalog table")
	}
	sets, args := []string{}, []any{}
	for _, field := range fields {
		if !body.Has(field) {
			continue
		}
		unchanged := body[field] == row[field]
		if field == "order_index" && body[field] != nil {
			unchanged = body.Int(field) == row.number(field)
		}
		if unchanged {
			continue
		}
		args = append(args, body[field])
		sets = append(sets, fmt.Sprintf("%s=$%d", field, len(args)))
	}
	if len(sets) == 0 {
		return row, nil
	}
	sets = append(sets, "updated_at=now()")
	args = append(args, row.number("id"))
	return queryRecord(ctx, tx, "UPDATE "+table+" SET "+strings.Join(sets, ",")+fmt.Sprintf(" WHERE id=$%d RETURNING to_jsonb(%s)", len(args), table), args...)
}

func (s *Service) writeCompetence(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	create := r.Method == "POST"
	schema, names := competenceSchema(create), []string{}
	if !create {
		names = append(names, "competence_id")
	}
	path, body, err := catalogInput(r, &schema, names...)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	var row record
	status := 201
	if create {
		if err = catalogUniqueCode(r.Context(), tx, false, airline, nil, body.String("code")); err != nil {
			return err
		}
		var order int64
		if err = tx.QueryRow(r.Context(), "SELECT coalesce(max(order_index),-1)::bigint+1 FROM competence WHERE airline_id=$1", airline).Scan(&order); err != nil {
			return err
		}
		row, err = queryRecord(r.Context(), tx, `INSERT INTO competence(airline_id,code,name,description,order_index) VALUES($1,$2,$3,$4,$5) RETURNING to_jsonb(competence)`, airline, body["code"], body["name"], body["description"], order)
	} else {
		status = 200
		row, err = activeCompetence(r.Context(), tx, airline, path.Int("competence_id"))
		if err != nil {
			return err
		}
		if body["code"] != nil && body["code"] != row["code"] {
			if err = catalogUniqueCode(r.Context(), tx, false, airline, row.number("id"), body.String("code")); err != nil {
				return err
			}
		}
		row, err = updateCatalogRow(r.Context(), tx, "competence", row, body, []string{"code", "name", "description"})
	}
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	platform.WriteJSON(w, status, commanderWire(row.project("id code name description created_at updated_at")))
	return nil
}

func (s *Service) reorderCompetences(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadObject(r, platform.Field{Name: "competence_ids", Alias: "competenceIds", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "integer"}})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	rows, err := activeCompetences(r.Context(), tx, airline)
	if err != nil {
		return err
	}
	byID, seen := map[int64]record{}, map[int64]bool{}
	for _, row := range rows {
		byID[row.number("id")] = row
	}
	ordered, invalid := []record{}, []int64{}
	for _, value := range body["competence_ids"].([]any) {
		id := value.(int64)
		if seen[id] {
			continue
		}
		seen[id] = true
		if byID[id] == nil {
			invalid = append(invalid, id)
		} else {
			ordered = append(ordered, byID[id])
		}
	}
	if len(invalid) > 0 {
		return &platform.APIError{Status: 400, Code: "INVALID_COMPETENCE_IDS", Message: "Invalid competence_ids", Extra: map[string]any{"ids": invalid}}
	}
	for _, row := range rows {
		if !seen[row.number("id")] {
			ordered = append(ordered, row)
		}
	}
	changes := []record{}
	for i, row := range ordered {
		if row.number("order_index") != int64(i) {
			changes = append(changes, record{"id": row["id"], "order_index": i})
		}
	}
	// SQLAlchemy flushes dirty instances by primary key, regardless of the new
	// display order. This also gives overlapping reorder writes a stable order.
	sort.Slice(changes, func(i, j int) bool { return changes[i].number("id") < changes[j].number("id") })
	for _, row := range changes {
		if _, err = tx.Exec(r.Context(), "UPDATE competence SET order_index=$1,updated_at=now() WHERE id=$2", row.number("order_index"), row.number("id")); err != nil {
			return err
		}
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}

func (s *Service) retireCompetence(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, err := catalogInput(r, nil, "competence_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	id := path.Int("competence_id")
	if _, err = activeCompetence(r.Context(), tx, airline, id); err != nil {
		return err
	}
	stamp := time.Now().UTC()
	if _, err = tx.Exec(r.Context(), "UPDATE competence SET retired_at=$1,updated_at=now() WHERE id=$2", stamp, id); err != nil {
		return err
	}
	for _, table := range []string{"exercise_competence", "element_block_competence", "flight_type_competence_threshold"} {
		if _, err = tx.Exec(r.Context(), "DELETE FROM "+table+" WHERE competence_id=$1", id); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(r.Context(), "UPDATE behavioural_indicator SET retired_at=$1,updated_at=now() WHERE competence_id=$2 AND retired_at IS NULL", stamp, id); err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
