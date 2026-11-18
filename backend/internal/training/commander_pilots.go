package training

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func (s *Service) registerCommanderPilots(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/commander/pilots"
	mux.HandleFunc("GET "+p, platform.Wrap(s.commanderPilots))
	mux.HandleFunc("GET "+p+"/compatibility", platform.Wrap(s.commanderCompatibility))
	mux.HandleFunc("GET "+p+"/{pilot_id}", platform.Wrap(s.commanderPilotProfile))
	mux.HandleFunc("GET "+p+"/{pilot_id}/training-summary", platform.Wrap(s.commanderPilotSummary))
}

var commanderPilotSortAliases = map[string]string{
	"createdAtDesc": "created_at_desc", "createdAtAsc": "created_at_asc",
	"loginAsc": "login_asc", "loginDesc": "login_desc", "emailAsc": "email_asc", "emailDesc": "email_desc",
	"lastNameAsc": "last_name_asc", "lastNameDesc": "last_name_desc",
}
var commanderPilotSortSQL = map[string]string{
	"created_at_desc": "u.created_at DESC,u.id DESC", "created_at_asc": "u.created_at,u.id",
	"login_asc": "lower(u.login),u.id", "login_desc": "lower(u.login) DESC,u.id DESC",
	"email_asc": "lower(u.email),u.id", "email_desc": "lower(u.email) DESC,u.id DESC",
	"last_name_asc":  "lower(coalesce(i.last_name,'')),lower(coalesce(i.first_name,'')),lower(u.login),u.id",
	"last_name_desc": "lower(coalesce(i.last_name,'')) DESC,lower(coalesce(i.first_name,'')) DESC,lower(u.login),u.id DESC",
}

// The latest assessment can contain no reports. Rating/compatibility must not
// silently fall back to an older assessment with grades. Position averages use
// the separate reports-present selection in commander_pilot_summary.go.
func commanderLatestPilotCTE(requireReports bool) string {
	reportsFilter := ""
	if requireReports {
		reportsFilter = " AND EXISTS(SELECT 1 FROM final_report f WHERE f.assessment_id=a.id) "
	}
	return `WITH assessment_ranked AS (
 SELECT a.user_id AS pilot_id,a.id AS assessment_id,row_number() OVER(PARTITION BY a.user_id
 ORDER BY coalesce(t.completed_at,t.updated_at,t.created_at) DESC,a.created_at DESC,a.id DESC) AS rank
 FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id
 WHERE a.user_id=ANY($2::bigint[]) AND t.status='COMPLETED'` + reportsFilter + `
 AND ($3::timestamptz IS NULL OR coalesce(t.completed_at,t.updated_at,t.created_at)<$3)),
 latest_assessments AS (SELECT pilot_id,assessment_id FROM assessment_ranked WHERE rank=1),
 report_ranked AS (SELECT a.pilot_id,f.assessment_id,f.competence_id,
 f.grade_score_snapshot AS score,row_number() OVER(PARTITION BY f.assessment_id,f.competence_id
 ORDER BY f.updated_at DESC,f.created_at DESC,f.id DESC) AS rank
 FROM latest_assessments a JOIN final_report f ON f.assessment_id=a.assessment_id
 JOIN competence c ON c.id=f.competence_id WHERE c.airline_id=$1),
 latest_reports AS (SELECT * FROM report_ranked WHERE rank=1) `
}

func commanderPilotRatings(ctx context.Context, db runtimeDB, airline int64, ids []int64) (map[int64]any, error) {
	out := map[int64]any{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := queryRecords(ctx, db, commanderLatestPilotCTE(false)+`SELECT to_jsonb(r) FROM (
 SELECT pilot_id,CASE WHEN value<0 AND round(value,1)=0 THEN '-0.0' ELSE round(value,1)::text END AS rating
 FROM (SELECT pilot_id,avg(score)::numeric(10,4) AS value FROM latest_reports WHERE score IS NOT NULL GROUP BY pilot_id) a) r`, airline, ids, nil)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		out[row.number("pilot_id")] = row["rating"]
	}
	return out, nil
}

func (s *Service) commanderPilots(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(),
		platform.Field{Name: "q", Kind: "string", Max: 255, Nullable: true},
		platform.Field{Name: "is_active", Alias: "isActive", Kind: "boolean", Nullable: true},
		platform.Field{Name: "role_id", Alias: "roleId", Kind: "uuid", Nullable: true},
		platform.Field{Name: "aircraft_id", Alias: "aircraftId", Kind: "integer", Min: 1, Nullable: true},
		platform.Field{Name: "sort", Kind: "string", Default: "createdAtDesc"},
		platform.Field{Name: "limit", Kind: "integer", Min: 1, Max: 200, Default: int64(50)},
		platform.Field{Name: "offset", Kind: "integer", NonNegative: true, Default: int64(0)})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	normalized := pythonTrim(q.String("sort"))
	if normalized == "" {
		normalized = "created_at_desc"
	}
	if alias, ok := commanderPilotSortAliases[normalized]; ok {
		normalized = alias
	}
	order, ok := commanderPilotSortSQL[normalized]
	if !ok {
		allowed := []string{}
		for alias := range commanderPilotSortAliases {
			allowed = append(allowed, alias)
		}
		sort.Strings(allowed)
		return &platform.APIError{Status: 400, Code: "INVALID_SORT", Message: "Unsupported sort option", Extra: map[string]any{"sort": q.String("sort"), "allowed": allowed}}
	}
	args := []any{airline}
	filters := []string{"u.airline_id=$1"}
	if needle := strings.Join(strings.FieldsFunc(q.String("q"), func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }), " "); needle != "" {
		args = append(args, "%"+needle+"%")
		matches := []string{}
		for _, expr := range []string{"u.login", "u.email", "i.first_name", "i.last_name", "concat(coalesce(i.first_name,''),' ',coalesce(i.last_name,''))", "concat(coalesce(i.last_name,''),' ',coalesce(i.first_name,''))", "p.name", "i.license_number"} {
			matches = append(matches, fmt.Sprintf("%s ILIKE $%d", expr, len(args)))
		}
		filters = append(filters, "("+strings.Join(matches, " OR ")+")")
	}
	for _, f := range []struct{ name, clause string }{
		{"is_active", "u.is_active=$%d"},
		{"role_id", "EXISTS(SELECT 1 FROM user_roles ur JOIN roles rr ON rr.id=ur.role_id WHERE ur.user_id=u.id AND rr.public_id=$%d)"},
		{"aircraft_id", "EXISTS(SELECT 1 FROM user_aircraft ua WHERE ua.user_id=u.id AND ua.aircraft_id=$%d)"},
	} {
		if q[f.name] != nil {
			args = append(args, q[f.name])
			filters = append(filters, fmt.Sprintf(f.clause, len(args)))
		}
	}
	from := " FROM users u LEFT JOIN user_info i ON i.id=u.id LEFT JOIN airline_position p ON p.id=i.position_id WHERE " + strings.Join(filters, " AND ")
	var total int64
	if err = s.Auth.DB.QueryRow(r.Context(), "SELECT count(*)"+from, args...).Scan(&total); err != nil {
		return err
	}
	args = append(args, q.Int("limit"), q.Int("offset"))
	page, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(r) FROM (SELECT u.id,u.public_id"+from+" ORDER BY "+order+fmt.Sprintf(" LIMIT $%d OFFSET $%d) r", len(args)-1, len(args)), args...)
	if err != nil {
		return err
	}
	publicIDs := []uuid.UUID{}
	ids := []int64{}
	for _, row := range page {
		publicIDs = append(publicIDs, uuid.MustParse(row.text("public_id")))
		ids = append(ids, row.number("id"))
	}
	users, err := s.Auth.LoadUsers(r.Context(), publicIDs)
	if err != nil {
		return err
	}
	ratings, err := commanderPilotRatings(r.Context(), s.Auth.DB, airline, ids)
	if err != nil {
		return err
	}
	items := []record{}
	for _, id := range publicIDs {
		u := users[id]
		if u == nil {
			return fmt.Errorf("pilot disappeared while reading page")
		}
		raw, err := json.Marshal(u)
		if err != nil {
			return err
		}
		item, err := decodeRecord(raw)
		if err != nil {
			return err
		}
		item["rating"] = ratings[u.InternalID]
		items = append(items, item)
	}
	platform.WriteJSON(w, 200, record{"total": total, "limit": q["limit"], "offset": q["offset"], "items": items})
	return nil
}

func commanderProfile(user *auth.User, rating any) record {
	value := func(p *string) any {
		if p == nil || *p == "" {
			return nil
		}
		return *p
	}
	parts := []string{}
	for _, part := range []*string{user.LastName, user.FirstName} {
		if part != nil && pythonTrim(*part) != "" {
			parts = append(parts, pythonTrim(*part))
		}
	}
	var name any
	if len(parts) > 0 {
		name = strings.Join(parts, " ")
	}
	return record{"id": user.ID, "full_name": name, "first_name": value(user.FirstName), "last_name": value(user.LastName), "photo_url": value(user.PhotoURL), "position_id": user.PositionID, "position": user.Position, "aircraft_ids": user.AircraftIDs, "aircraft_codes": user.AircraftCodes, "phone": value(user.Phone), "email": user.Email, "rating": rating}
}

func (s *Service) commanderReadPilot(r *http.Request) (int64, *auth.User, error) {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return 0, nil, err
	}
	path, err := platform.ValidateObject(map[string]any{"pilot_id": r.PathValue("pilot_id")}, []any{"path"}, platform.Schema{Fields: []platform.Field{{Name: "pilot_id", Kind: "uuid", Required: true}}})
	if err != nil {
		return 0, nil, err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return 0, nil, err
	}
	pilot, err := s.Auth.LoadUser(r.Context(), path["pilot_id"].(uuid.UUID))
	if errors.Is(err, pgx.ErrNoRows) || err == nil && (pilot.AirlineID == nil || *pilot.AirlineID != airline) {
		return 0, nil, commanderError(404, "PILOT_NOT_FOUND", "Pilot not found")
	}
	return airline, pilot, err
}

func (s *Service) commanderPilotProfile(w http.ResponseWriter, r *http.Request) error {
	airline, pilot, err := s.commanderReadPilot(r)
	if err != nil {
		return err
	}
	ratings, err := commanderPilotRatings(r.Context(), s.Auth.DB, airline, []int64{pilot.InternalID})
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(commanderProfile(pilot, ratings[pilot.InternalID])))
	return nil
}

func (s *Service) commanderCompatibility(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(),
		platform.Field{Name: "first_pilot_id", Alias: "firstPilotId", Kind: "uuid", Required: true},
		platform.Field{Name: "second_pilot_id", Alias: "secondPilotId", Kind: "uuid", Required: true},
		platform.Field{Name: "flight_type_id", Alias: "flightTypeId", Kind: "integer", Min: 1, Required: true},
		platform.Field{Name: "as_of_date", Alias: "asOfDate", Kind: "date", Nullable: true})
	if err != nil {
		return err
	}
	first, second := q["first_pilot_id"].(uuid.UUID), q["second_pilot_id"].(uuid.UUID)
	if first == second {
		return commanderError(400, "SAME_PILOT_IDS", "firstPilotId and secondPilotId must be different")
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	users, err := s.Auth.LoadUsers(r.Context(), []uuid.UUID{first, second})
	if err != nil {
		return err
	}
	for i, id := range []uuid.UUID{first, second} {
		pilot := users[id]
		if pilot == nil || pilot.AirlineID == nil || *pilot.AirlineID != airline {
			return &platform.APIError{Status: 404, Code: "PILOT_NOT_FOUND", Message: "Pilot not found", Extra: map[string]any{"parameter": []string{"firstPilotId", "secondPilotId"}[i]}}
		}
	}
	flight, err := queryRecord(r.Context(), s.Auth.DB, `SELECT jsonb_build_object('id',id,'name',name) FROM flight_type WHERE airline_id=$1 AND id=$2`, airline, q.Int("flight_type_id"))
	if errors.Is(err, pgx.ErrNoRows) {
		return commanderError(404, "FLIGHT_TYPE_NOT_FOUND", "Flight type not found")
	}
	if err != nil {
		return err
	}
	a, b := users[first], users[second]
	var bound, date any
	if q["as_of_date"] != nil {
		day := q["as_of_date"].(time.Time)
		bound = day.AddDate(0, 0, 1)
		date = day.Format("2006-01-02")
	}
	args := []any{airline, []int64{a.InternalID, b.InternalID}, bound, a.InternalID, b.InternalID, q.Int("flight_type_id")}
	items, err := queryRecords(r.Context(), s.Auth.DB, commanderLatestPilotCTE(false)+`SELECT to_jsonb(r) FROM (
 SELECT c.id AS competence_id,c.code AS competence_code,c.name AS competence_name,c.order_index,
 (t.value IS NULL OR (x.score IS NOT NULL AND y.score IS NOT NULL AND x.score+y.score>=t.value)) AS compatible,
 t.value IS NOT NULL AS threshold_configured,t.value::text AS required_sum,(x.score+y.score)::text AS actual_sum,
 x.score::text AS first_pilot_value,y.score::text AS second_pilot_value
 FROM competence c LEFT JOIN latest_reports x ON x.pilot_id=$4 AND x.competence_id=c.id
 LEFT JOIN latest_reports y ON y.pilot_id=$5 AND y.competence_id=c.id
 LEFT JOIN flight_type_competence_threshold t ON t.flight_type_id=$6 AND t.competence_id=c.id
 WHERE c.airline_id=$1 ORDER BY c.order_index,c.id) r`, args...)
	if err != nil {
		return err
	}
	completed, err := queryRecords(r.Context(), s.Auth.DB, commanderLatestPilotCTE(false)+`SELECT jsonb_build_object('pilot_id',pilot_id) FROM latest_assessments`, args[:3]...)
	if err != nil {
		return err
	}
	known := map[int64]bool{}
	for _, row := range completed {
		known[row.number("pilot_id")] = true
	}
	pilotWire := func(u *auth.User) record {
		return record{"id": u.ID, "first_name": u.FirstName, "last_name": u.LastName, "has_completed_training": known[u.InternalID]}
	}
	platform.WriteJSON(w, 200, commanderWire(record{"first_pilot": pilotWire(a), "second_pilot": pilotWire(b), "flight_type": flight, "as_of_date": date, "items": items}))
	return nil
}
