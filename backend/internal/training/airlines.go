package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func (s *Service) registerAirlines(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/airlines"
	mux.HandleFunc("GET "+p, platform.Wrap(s.listAirlines))
	mux.HandleFunc("POST "+p, platform.Wrap(s.createAirline))
	mux.HandleFunc("PUT "+p+"/{airline_id}", platform.Wrap(s.updateAirline))
	mux.HandleFunc("DELETE "+p+"/{airline_id}", platform.Wrap(s.deleteAirline))
	mux.HandleFunc("POST "+p+"/{target_airline_id}/clone-training", platform.Wrap(s.cloneAirline))
}

func airlineSchema(create bool) platform.Schema {
	fields := []platform.Field{{Name: "code", Kind: "string", Max: 10, Nullable: true}, {Name: "name", Kind: "string", Min: 1, Max: 255, Required: create, Nullable: !create}, {Name: "active", Kind: "boolean", Nullable: !create}, {Name: "users_stored_in_local_db", Alias: "usersStoredInLocalDb", Kind: "boolean", Nullable: !create}}
	if create {
		fields[2].Default = true
		fields[3].Default = true
		fields = append(fields, platform.Field{Name: "copy_from", Alias: "copyFrom", Kind: "integer", Min: 1, Nullable: true})
	}
	return platform.Schema{Fields: fields}
}
func airlineDTO(row record) any {
	return commanderWire(row.project("id code name active users_stored_in_local_db created_at updated_at"))
}
func findAirline(ctx context.Context, db runtimeDB, id int64, message string) (record, error) {
	row, err := queryRecord(ctx, db, "SELECT to_jsonb(a) FROM airline a WHERE id=$1", id)
	if errors.Is(err, pgx.ErrNoRows) {
		err = platform.Error(404, message)
	}
	return row, err
}
func airlineCode(ctx context.Context, db runtimeDB, raw any, exclude any) (any, error) {
	if raw == nil {
		return nil, nil
	}
	code := pythonTrim(raw.(string))
	if code == "" {
		return nil, nil
	}
	var exists bool
	err := db.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM airline WHERE code=$1 AND ($2::bigint IS NULL OR id<>$2))", code, exclude).Scan(&exists)
	if err != nil {
		return nil, err
	}
	if exists {
		return nil, platform.Error(400, "Airline code already exists")
	}
	return code, nil
}

func (s *Service) listAirlines(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:read"); err != nil {
		return err
	}
	rows, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(a) FROM airline a ORDER BY id")
	if err != nil {
		return err
	}
	items := []any{}
	for _, row := range rows {
		items = append(items, airlineDTO(row))
	}
	platform.WriteJSON(w, 200, items)
	return nil
}

// Only server-defined fields enter this helper. JSONB record conversion keeps
// SQL decimals, timestamps, dates and structured guidance exact without a
// second set of Go representations for every legacy column type.
func insertTrainingRow(ctx context.Context, db runtimeDB, table string, row record) (record, error) {
	keys := []string{}
	for key := range row {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	columns := make([]string, len(keys))
	for i, key := range keys {
		columns[i] = pgx.Identifier{key}.Sanitize()
	}
	name := pgx.Identifier{table}.Sanitize()
	list := strings.Join(columns, ",")
	return queryRecord(ctx, db, "INSERT INTO "+name+" ("+list+") SELECT "+list+" FROM jsonb_populate_record(NULL::"+name+",$1::jsonb) RETURNING to_jsonb("+name+")", row)
}

func defaultAirlineGrading(ctx context.Context, tx pgx.Tx, airline int64) error {
	scheme, err := insertTrainingRow(ctx, tx, "grading_scheme", record{"airline_id": airline, "name": "Default Numeric Scale", "version": 1, "is_active": true})
	if err != nil {
		return err
	}
	colors := []string{"#284692", "#7294D8", "#A9A8AB", "#F7D046", "#FF453A"}
	for order, color := range colors {
		code := fmt.Sprint(5 - order)
		if _, err = insertTrainingRow(ctx, tx, "grading_scale_value", record{"grading_scheme_id": scheme["id"], "code": code, "label": code, "score_numeric": code + ".0000", "grade_weight": "1.0000", "order_index": order, "color_hex": color, "is_pass": true}); err != nil {
			return err
		}
	}
	return nil
}
func (s *Service) createAirline(w http.ResponseWriter, r *http.Request) error {
	author, err := s.Auth.Authenticate(r, "users:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, airlineSchema(true))
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	code, err := airlineCode(ctx, tx, body["code"], nil)
	if err != nil {
		return err
	}
	if body["copy_from"] != nil {
		if _, err = findAirline(ctx, tx, body.Int("copy_from"), "Source airline not found"); err != nil {
			return err
		}
	}
	airline, err := insertTrainingRow(ctx, tx, "airline", record{"code": code, "name": body["name"], "active": body["active"], "users_stored_in_local_db": body["users_stored_in_local_db"]})
	if err != nil {
		return err
	}
	if err = defaultAirlineGrading(ctx, tx, airline.number("id")); err != nil {
		return err
	}
	if body["copy_from"] != nil {
		if _, err = cloneAirlineStructure(ctx, tx, body.Int("copy_from"), airline.number("id"), author.InternalID); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	airline, err = findAirline(ctx, s.Auth.DB, airline.number("id"), "Airline not found")
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, airlineDTO(airline))
	return nil
}
func (s *Service) updateAirline(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	schema := airlineSchema(false)
	path, body, err := catalogInput(r, &schema, "airline_id")
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	id := path.Int("airline_id")
	row, err := findAirline(ctx, tx, id, "Airline not found")
	if err != nil {
		return err
	}
	if body.Has("code") {
		body["code"], err = airlineCode(ctx, tx, body["code"], id)
		if err != nil {
			return err
		}
	}
	sets, args := []string{}, []any{}
	for _, key := range []string{"code", "name", "active", "users_stored_in_local_db"} {
		if body.Has(key) && body[key] != row[key] {
			args = append(args, body[key])
			sets = append(sets, fmt.Sprintf("%s=$%d", key, len(args)))
		}
	}
	if len(sets) > 0 {
		sets = append(sets, "updated_at=now()")
		args = append(args, id)
		if _, err = tx.Exec(ctx, "UPDATE airline SET "+strings.Join(sets, ",")+fmt.Sprintf(" WHERE id=$%d", len(args)), args...); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = findAirline(ctx, s.Auth.DB, id, "Airline not found")
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, airlineDTO(row))
	return nil
}
func (s *Service) cloneAirline(w http.ResponseWriter, r *http.Request) error {
	author, err := s.Auth.Authenticate(r, "users:write")
	if err != nil {
		return err
	}
	schema := platform.Schema{Fields: []platform.Field{{Name: "source_airline_id", Alias: "sourceAirlineId", Kind: "integer", Min: 1, Required: true}}}
	path, body, err := catalogInput(r, &schema, "target_airline_id")
	if err != nil {
		return err
	}
	source, target := body.Int("source_airline_id"), path.Int("target_airline_id")
	if source == target {
		return commanderError(400, "SAME_AIRLINE", "source_airline_id and target_airline_id must be different")
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = findAirline(ctx, tx, source, "Source airline not found"); err != nil {
		return err
	}
	if _, err = findAirline(ctx, tx, target, "Target airline not found"); err != nil {
		return err
	}
	counts, err := cloneAirlineStructure(ctx, tx, source, target, author.InternalID)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.WriteJSON(w, 201, commanderWire(record{"source_airline_id": source, "target_airline_id": target, "counts": counts}))
	return nil
}

func (s *Service) deleteAirline(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	path, _, err := catalogInput(r, nil, "airline_id")
	if err != nil {
		return err
	}
	id := path.Int("airline_id")
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = findAirline(ctx, tx, id, "Airline not found"); err != nil {
		return err
	}
	// SQLAlchemy clears these non-cascading relationships before deleting the
	// parent. NOT NULL failures are intentional: a raw cascading DELETE would
	// silently remove libraries with dependent records.
	for _, table := range []string{"element", "element_block", "scenario", "scenario_content_set", "element_folder", "block_folder"} {
		if _, err = tx.Exec(ctx, "UPDATE "+table+" SET airline_id=NULL,updated_at=now() WHERE airline_id=$1", id); err != nil {
			return err
		}
	}
	for _, table := range []string{"element", "scenario", "scenario_content_set", "element_folder", "block_folder", "user_aircraft"} {
		stamp := ",updated_at=now()"
		if table == "user_aircraft" {
			stamp = ""
		}
		if _, err = tx.Exec(ctx, "UPDATE "+table+" SET aircraft_id=NULL"+stamp+" WHERE aircraft_id IN (SELECT id FROM aircraft_airline WHERE airline_id=$1)", id); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, "UPDATE users SET airline_id=NULL,updated_at=now() WHERE airline_id=$1", id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "DELETE FROM airline WHERE id=$1", id); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
