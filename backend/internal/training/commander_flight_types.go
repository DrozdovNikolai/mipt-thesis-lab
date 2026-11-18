package training

import (
	"context"
	"errors"
	"net/http"
	"sort"
	"strings"
	"unicode"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/platform"
)

const commanderFlightSelect = `SELECT f.id,f.airline_id,f.name,f.is_main,f.created_at,f.updated_at,
 COALESCE((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.competence_order_index,r.competence_id,r.id) FROM
 (SELECT t.id,t.competence_id,c.code AS competence_code,c.name AS competence_name,c.order_index AS competence_order_index,
 t.value::text AS value,t.created_at,t.updated_at FROM flight_type_competence_threshold t
 JOIN competence c ON c.id=t.competence_id WHERE t.flight_type_id=f.id) r),'[]'::jsonb) AS thresholds FROM flight_type f`

func (s *Service) commanderFlightTypes(w http.ResponseWriter, r *http.Request) error {
	return s.commanderCatalog(w, r, "SELECT to_jsonb(r) FROM ("+commanderFlightSelect+" WHERE f.airline_id=$1 ORDER BY f.is_main DESC,lower(f.name),f.id) r")
}

func commanderFlightSchema(create bool) platform.Schema {
	main := platform.Field{Name: "is_main", Alias: "isMain", Kind: "boolean", Nullable: !create}
	if create {
		main.Default = false
	}
	return platform.Schema{Fields: []platform.Field{{Name: "name", Kind: "string", Required: create, Nullable: !create, Min: 1, Max: 100}, main}}
}

var commanderThresholdSchema = platform.Schema{
	Fields: []platform.Field{{Name: "thresholds", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &platform.Schema{Fields: []platform.Field{
		{Name: "competence_id", Alias: "competenceId", Kind: "integer", Min: 1, Required: true},
		{Name: "value", Kind: "decimal", Required: true, Decimal: &platform.DecimalConstraints{MaxDigits: 10, Places: 4, Minimum: "0", Maximum: "999999.9999"}},
	}}}}},
	Check: func(o platform.Object) string {
		seen := map[int64]bool{}
		for _, value := range o["thresholds"].([]any) {
			id := value.(platform.Object).Int("competence_id")
			if seen[id] {
				return "competenceIds must be unique"
			}
			seen[id] = true
		}
		return ""
	},
}

func commanderFlightName(ctx context.Context, db runtimeDB, airline, exclude int64, raw string) (string, string, error) {
	name := strings.Join(strings.FieldsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }), " ")
	if name == "" {
		return "", "", commanderError(400, "INVALID_FLIGHT_TYPE_NAME", "Flight type name must not be empty")
	}
	normalized := cases.Lower(language.Und).String(name)
	var exists bool
	if err := db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM flight_type WHERE airline_id=$1 AND normalized_name=$2 AND id<>$3)`, airline, normalized, exclude).Scan(&exists); err != nil {
		return "", "", err
	}
	if exists {
		return "", "", commanderError(400, "FLIGHT_TYPE_NAME_EXISTS", "Flight type already exists")
	}
	return name, normalized, nil
}

func commanderFlightID(r *http.Request) (int64, error) {
	id, err := platform.ValidateObject(map[string]any{"flight_type_id": r.PathValue("flight_type_id")}, []any{"path"}, platform.Schema{Fields: []platform.Field{{Name: "flight_type_id", Kind: "integer", Min: 1, Required: true}}})
	if err != nil {
		return 0, err
	}
	return id.Int("flight_type_id"), nil
}

func commanderFlightInput(r *http.Request, schema platform.Schema) (int64, platform.Object, error) {
	path, body, err := platform.ReadPathAndBody(r, platform.Schema{Fields: []platform.Field{{Name: "flight_type_id", Kind: "integer", Min: 1, Required: true}}}, schema)
	return path.Int("flight_type_id"), body, err
}

func commanderLockFlight(ctx context.Context, tx pgx.Tx, airline, id int64) (record, error) {
	row, err := queryRecord(ctx, tx, `SELECT to_jsonb(f) FROM flight_type f WHERE airline_id=$1 AND id=$2 FOR UPDATE`, airline, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, commanderError(404, "FLIGHT_TYPE_NOT_FOUND", "Flight type not found")
	}
	return row, err
}

func (s *Service) commanderWriteFlight(w http.ResponseWriter, r *http.Request, airline, id int64, status int) error {
	value, err := queryRecord(r.Context(), s.Auth.DB, "SELECT to_jsonb(r) FROM ("+commanderFlightSelect+" WHERE f.airline_id=$1 AND f.id=$2) r", airline, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return commanderError(404, "FLIGHT_TYPE_NOT_FOUND", "Flight type not found")
	}
	if err != nil {
		return err
	}
	platform.WriteJSON(w, status, commanderWire(value))
	return nil
}

func (s *Service) commanderCreateFlightType(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, commanderFlightSchema(true))
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
	name, normalized, err := commanderFlightName(r.Context(), tx, airline, 0, body.String("name"))
	if err != nil {
		return err
	}
	if body.Bool("is_main") {
		if _, err = tx.Exec(r.Context(), `UPDATE flight_type SET is_main=false,updated_at=now() WHERE airline_id=$1 AND is_main`, airline); err != nil {
			return err
		}
	}
	var id int64
	if err = tx.QueryRow(r.Context(), `INSERT INTO flight_type(airline_id,name,normalized_name,is_main) VALUES($1,$2,$3,$4) RETURNING id`, airline, name, normalized, body.Bool("is_main")).Scan(&id); err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	return s.commanderWriteFlight(w, r, airline, id, 201)
}

func (s *Service) commanderUpdateFlightType(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:write")
	if err != nil {
		return err
	}
	id, body, err := commanderFlightInput(r, commanderFlightSchema(false))
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
	row, err := commanderLockFlight(r.Context(), tx, airline, id)
	if err != nil {
		return err
	}
	name, normalized, main := row.text("name"), row.text("normalized_name"), row["is_main"]
	if body["name"] != nil {
		name, normalized, err = commanderFlightName(r.Context(), tx, airline, id, body.String("name"))
		if err != nil {
			return err
		}
	}
	if body["is_main"] != nil {
		main = body.Bool("is_main")
		if main == true {
			if _, err = tx.Exec(r.Context(), `UPDATE flight_type SET is_main=false,updated_at=now() WHERE airline_id=$1 AND id<>$2 AND is_main`, airline, id); err != nil {
				return err
			}
		}
	}
	// SQLAlchemy does not issue an UPDATE for unchanged values or explicit nulls.
	if name != row.text("name") || normalized != row.text("normalized_name") || main != row["is_main"] {
		if _, err = tx.Exec(r.Context(), `UPDATE flight_type SET name=$2,normalized_name=$3,is_main=$4,updated_at=now() WHERE id=$1`, id, name, normalized, main); err != nil {
			return err
		}
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	return s.commanderWriteFlight(w, r, airline, id, 200)
}

func (s *Service) commanderReplaceThresholds(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:write")
	if err != nil {
		return err
	}
	id, body, err := commanderFlightInput(r, commanderThresholdSchema)
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
	if _, err = commanderLockFlight(r.Context(), tx, airline, id); err != nil {
		return err
	}
	items := body["thresholds"].([]any)
	ids := make([]int64, 0, len(items))
	for _, item := range items {
		ids = append(ids, item.(platform.Object).Int("competence_id"))
	}
	valid, err := queryRecords(r.Context(), tx, `SELECT jsonb_build_object('id',id) FROM competence WHERE airline_id=$1 AND id=ANY($2::bigint[])`, airline, ids)
	if err != nil {
		return err
	}
	known := map[int64]bool{}
	for _, item := range valid {
		known[item.number("id")] = true
	}
	invalid := []int64{}
	for _, id := range ids {
		if !known[id] {
			invalid = append(invalid, id)
		}
	}
	if len(invalid) > 0 {
		sort.Slice(invalid, func(i, j int) bool { return invalid[i] < invalid[j] })
		return &platform.APIError{Status: 400, Code: "INVALID_COMPETENCE_IDS", Message: "Invalid competence_ids", Extra: map[string]any{"ids": invalid}}
	}
	if _, err = tx.Exec(r.Context(), `DELETE FROM flight_type_competence_threshold WHERE flight_type_id=$1 AND NOT(competence_id=ANY($2::bigint[]))`, id, ids); err != nil {
		return err
	}
	for _, item := range items {
		value := item.(platform.Object)
		// An existing row must not consume a sequence ID or change updated_at when
		// its value is equal. Parent locking serializes whole-set replacements.
		var exists bool
		if err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM flight_type_competence_threshold WHERE flight_type_id=$1 AND competence_id=$2)`, id, value.Int("competence_id")).Scan(&exists); err != nil {
			return err
		}
		if exists {
			_, err = tx.Exec(r.Context(), `UPDATE flight_type_competence_threshold SET value=$3::text::numeric,updated_at=now() WHERE flight_type_id=$1 AND competence_id=$2 AND value<>$3::text::numeric`, id, value.Int("competence_id"), value.String("value"))
		} else {
			_, err = tx.Exec(r.Context(), `INSERT INTO flight_type_competence_threshold(flight_type_id,competence_id,value) VALUES($1,$2,$3::text::numeric)`, id, value.Int("competence_id"), value.String("value"))
		}
		if err != nil {
			return err
		}
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	return s.commanderWriteFlight(w, r, airline, id, 200)
}

func (s *Service) commanderDeleteFlightType(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:write")
	if err != nil {
		return err
	}
	id, err := commanderFlightID(r)
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
	if _, err = commanderLockFlight(r.Context(), tx, airline, id); err != nil {
		return err
	}
	if _, err = tx.Exec(r.Context(), `DELETE FROM flight_type WHERE id=$1`, id); err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
