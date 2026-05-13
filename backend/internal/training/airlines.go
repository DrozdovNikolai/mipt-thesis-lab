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
