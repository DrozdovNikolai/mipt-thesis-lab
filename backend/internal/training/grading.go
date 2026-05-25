package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/platform"
)

func (s *Service) registerGrading(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	for _, admin := range []bool{false, true} {
		path := p + "/assessment/grading-scale"
		if admin {
			path = p + "/airlines/{airline_id}/grading-scale"
		}
		mux.HandleFunc("GET "+path, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.gradingScale(w, r, admin, false) }))
		mux.HandleFunc("PUT "+path, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.gradingScale(w, r, admin, true) }))
	}
}

var gradingPathSchema = platform.Schema{Fields: []platform.Field{{Name: "airline_id", Kind: "integer", Required: true}}}

var gradingValueSchema = platform.Schema{Fields: []platform.Field{
	{Name: "code", Kind: "string", Required: true, Min: 1, Max: 50},
	{Name: "label", Kind: "string", Required: true, Min: 1, Max: 100},
	{Name: "score_numeric", Alias: "scoreNumeric", Kind: "decimal", Required: true, Decimal: &platform.DecimalConstraints{Unbounded: true}},
	{Name: "grade_weight", Alias: "gradeWeight", Kind: "decimal", Default: "1.0000", GreaterThanZero: true, Decimal: &platform.DecimalConstraints{Unbounded: true}},
	{Name: "order_index", Alias: "orderIndex", Kind: "integer", NonNegative: true, Default: int64(0)},
	{Name: "color_hex", Alias: "colorHex", Kind: "string", Nullable: true, Pattern: "^#[0-9A-Fa-f]{6}$"},
	{Name: "is_pass", Alias: "isPass", Kind: "boolean", Default: false},
}}

var gradingReplaceSchema = platform.Schema{
	Fields: []platform.Field{
		{Name: "scheme_name", Alias: "schemeName", Kind: "string", Min: 1, Max: 255, Default: "Airline Scale"},
		{Name: "values", Kind: "list", Required: true, Min: 1, Item: &platform.Field{Kind: "object", Schema: &gradingValueSchema}},
	},
	Check: func(o platform.Object) string {
		codes, order := map[string]bool{}, map[int64]bool{}
		for _, item := range o["values"].([]any) {
			v := item.(platform.Object)
			code := assessmentUpper(pythonTrim(v.String("code")))
			if code == "" {
				return "Grade code must not be empty"
			}
			if codes[code] {
				return "Grade codes must be unique"
			}
			codes[code] = true
			if order[v.Int("order_index")] {
				return "order_index values must be unique"
			}
			order[v.Int("order_index")] = true
		}
		return ""
	},
}

func activeGrading(ctx context.Context, db runtimeDB, airline int64) (record, error) {
	return queryRecord(ctx, db, "SELECT to_jsonb(g) FROM grading_scheme g WHERE airline_id=$1 AND is_active ORDER BY version DESC,id DESC LIMIT 1", airline)
}

func readGradingResponse(ctx context.Context, db runtimeDB, row record, admin bool) (record, error) {
	values, err := queryRecords(ctx, db, `SELECT to_jsonb(v) FROM (SELECT id,code,label,score_numeric::text AS score_numeric,grade_weight::text AS grade_weight,order_index,color_hex,is_pass FROM grading_scale_value WHERE grading_scheme_id=$1 ORDER BY order_index,id) v`, row.number("id"))
	if err != nil {
		return nil, err
	}
	for _, value := range values {
		for _, name := range []string{"score_numeric", "grade_weight"} {
			if strings.EqualFold(value.text(name), "NaN") || strings.Contains(value.text(name), "Infinity") {
				return nil, fmt.Errorf("grading response requires finite decimals")
			}
		}
	}
	version := row.number("version")
	if version == 0 {
		version = 1
	}
	out := record{"scheme_id": row["id"], "scheme_name": row["name"], "scheme_version": version, "values": values}
	if admin {
		out["airline_id"] = row["airline_id"]
	}
	return out, nil
}

func (s *Service) gradingScale(w http.ResponseWriter, r *http.Request, admin, write bool) error {
	privilege := "training:read"
	if write {
		privilege = "training:write"
	}
	if admin {
		privilege = "users:read"
		if write {
			privilege = "users:write"
		}
	}
	user, err := s.Auth.Authenticate(r, privilege)
	if err != nil {
		return err
	}
	var airline int64
	var body platform.Object
	if admin && write {
		var path platform.Object
		path, body, err = platform.ReadPathAndBody(r, gradingPathSchema, gradingReplaceSchema)
		airline = path.Int("airline_id")
	} else if admin {
		var path platform.Object
		path, err = platform.ValidateObject(map[string]any{"airline_id": r.PathValue("airline_id")}, []any{"path"}, gradingPathSchema)
		airline = path.Int("airline_id")
	} else if write {
		body, err = platform.ReadSchema(r, gradingReplaceSchema)
	}
	if err != nil {
		return err
	}
	if !admin {
		if user.AirlineID == nil {
			return platform.Error(400, "User is not assigned to an airline")
		}
		airline = *user.AirlineID
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	if admin {
		var exists bool
		if err = tx.QueryRow(r.Context(), "SELECT EXISTS(SELECT 1 FROM airline WHERE id=$1)", airline).Scan(&exists); err != nil {
			return err
		}
		if !exists {
			return platform.Error(404, "Airline not found")
		}
		if write && pythonTrim(body.String("scheme_name")) == "" {
			return platform.Error(400, "scheme_name must not be empty")
		}
	}
	current, err := activeGrading(r.Context(), tx, airline)
	if errors.Is(err, pgx.ErrNoRows) {
		current, err = nil, nil
	}
	if err != nil {
		return err
	}
	if current == nil && (!admin || !write) {
		if admin {
			return platform.Error(404, "Active grading scheme not found")
		}
		return platform.Error(400, "Active grading scheme is not configured for airline")
	}
	if !write {
		out, err := readGradingResponse(r.Context(), tx, current, admin)
		if err != nil {
			return err
		}
		platform.WriteJSON(w, 200, commanderWire(out))
		return nil
	}
	newID, err := replaceGrading(r.Context(), tx, airline, current, body, admin)
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return gradingValueWriteError(err, admin)
	}
	// Admin reads whichever version is active after commit. The assessment API
	// returns the exact version it created, even if another replacement follows.
	var row record
	if admin {
		row, err = activeGrading(r.Context(), s.Auth.DB, airline)
	} else {
		row, err = queryRecord(r.Context(), s.Auth.DB, "SELECT to_jsonb(g) FROM grading_scheme g WHERE id=$1", newID)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		if admin {
			return platform.Error(500, "Failed to load grading scale")
		}
		return platform.Error(400, "Training grading scheme not found")
	}
	if err != nil {
		return err
	}
	out, err := readGradingResponse(r.Context(), s.Auth.DB, row, admin)
	if err != nil {
		return err
	}
	if !admin {
		platform.LogModule("app.audit", r.Context()).Info("Grading scale replaced", "user_id", user.ID.String(), "action", "assessment.grading_scale.replace", "scheme_id", row.number("id"), "scheme_version", row.number("version"))
	}
	platform.WriteJSON(w, 200, commanderWire(out))
	return nil
}

func gradingValueWriteError(err error, admin bool) error {
	var pg *pgconn.PgError
	if admin && errors.As(err, &pg) && strings.HasPrefix(pg.Code, "23") {
		return platform.Error(409, "Failed to replace grading scale due to concurrent update")
	}
	return err
}

func replaceGrading(ctx context.Context, tx pgx.Tx, airline int64, current record, body platform.Object, admin bool) (int64, error) {
	values := body["values"].([]any)
	for _, value := range values {
		v := value.(platform.Object)
		v["code"], v["label"] = assessmentUpper(pythonTrim(v.String("code"))), pythonTrim(v.String("label"))
		// The source builds a second Pydantic value model after normalization.
		// Those failures occur inside the service and are unhandled 500 responses.
		if v.String("label") == "" || utf8.RuneCountInString(v.String("code")) > 50 {
			return 0, fmt.Errorf("normalized grading value is invalid")
		}
		if v["color_hex"] != nil {
			v["color_hex"] = strings.ToUpper(v.String("color_hex"))
		}
	}
	version := int64(1)
	if admin {
		if err := tx.QueryRow(ctx, "SELECT coalesce(max(version),0)+1 FROM grading_scheme WHERE airline_id=$1", airline).Scan(&version); err != nil {
			return 0, err
		}
	} else {
		version = current.number("version")
		if version == 0 {
			version = 1
		}
		version++
	}
	if current != nil {
		if _, err := tx.Exec(ctx, "UPDATE grading_scheme SET is_active=false,updated_at=now() WHERE id=$1", current.number("id")); err != nil {
			return 0, err
		}
	}
	var id int64
	if err := tx.QueryRow(ctx, `INSERT INTO grading_scheme(airline_id,name,version,is_active) VALUES($1,$2,$3,true) RETURNING id`, airline, pythonTrim(body.String("scheme_name")), version).Scan(&id); err != nil {
		return 0, err // The source scheme flush is outside its IntegrityError catch.
	}
	sort.SliceStable(values, func(i, j int) bool {
		a, b := values[i].(platform.Object), values[j].(platform.Object)
		if a.Int("order_index") != b.Int("order_index") {
			return a.Int("order_index") < b.Int("order_index")
		}
		return a.String("code") < b.String("code")
	})
	// Match SQLAlchemy's batch size and stay below PostgreSQL's parameter limit
	// without imposing a new API limit on the number of grades.
	for start := 0; start < len(values); start += 1000 {
		args, groups := []any{}, []string{}
		for _, value := range values[start:min(start+1000, len(values))] {
			v := value.(platform.Object)
			n := len(args)
			groups = append(groups, fmt.Sprintf("($%d,$%d,$%d,$%d::text::numeric,$%d::text::numeric,$%d,$%d,$%d)", n+1, n+2, n+3, n+4, n+5, n+6, n+7, n+8))
			args = append(args, id, v["code"], v["label"], v["score_numeric"], v["grade_weight"], v["order_index"], v["color_hex"], v["is_pass"])
		}
		if _, err := tx.Exec(ctx, `INSERT INTO grading_scale_value(grading_scheme_id,code,label,score_numeric,grade_weight,order_index,color_hex,is_pass) VALUES `+strings.Join(groups, ","), args...); err != nil {
			return 0, gradingValueWriteError(err, admin)
		}
	}
	return id, nil
}
