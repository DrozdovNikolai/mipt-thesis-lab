package training

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"north55/backend/internal/platform"
)

type commanderAnalytics struct {
	kind    string
	airline int64
	query   platform.Object
	users   []record
	args    []any
	cte     string
}

func (s *Service) registerCommanderAnalytics(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/commander/analytics"
	for path, kind := range map[string]string{"/competencies/grade-distribution": "competencies", "/competencies/average-trend": "trend", "/pilots/grade-distribution": "pilots", "/instructors/grade-distribution": "instructors"} {
		mux.HandleFunc("GET "+p+path, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.commanderAnalyticsResponse(w, r, kind) }))
	}
}

// The source age helper falls back to February 28 when date.replace rejects
// subtracting years from a leap day.
func commanderSubtractYears(day time.Time, years int64) (time.Time, error) {
	if years < 0 || years >= int64(day.Year()) {
		return time.Time{}, fmt.Errorf("birth date year out of range")
	}
	year := day.Year() - int(years)
	date := time.Date(year, day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
	if date.Month() != day.Month() {
		date = time.Date(year, time.February, 28, 0, 0, 0, 0, time.UTC)
	}
	return date, nil
}

func (s *Service) commanderAnalyticsInput(r *http.Request, kind string) (commanderAnalytics, error) {
	out := commanderAnalytics{kind: kind}
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return out, err
	}
	q, err := platform.QueryObject(r.URL.Query(),
		platform.Field{Name: "aircraft_id", Alias: "aircraftId", Kind: "integer", Min: 1, Nullable: true},
		platform.Field{Name: "pilot_id", Alias: "pilotId", Kind: "uuid", Nullable: true},
		platform.Field{Name: "age_from_years", Alias: "ageFromYears", Kind: "integer", NonNegative: true, Nullable: true},
		platform.Field{Name: "age_to_years", Alias: "ageToYears", Kind: "integer", NonNegative: true, Nullable: true},
		platform.Field{Name: "position_id", Alias: "positionId", Kind: "integer", Min: 1, Nullable: true},
		platform.Field{Name: "as_of_date", Alias: "asOfDate", Kind: "date", Nullable: true})
	if err != nil {
		return out, err
	}
	for _, legacy := range []struct{ key, message string }{{"position", "Use positionId instead of position"}, {"ageYears", "Use ageFromYears/ageToYears instead of ageYears"}} {
		if r.URL.Query().Has(legacy.key) {
			return out, &platform.APIError{Status: 400, Code: "UNSUPPORTED_QUERY_PARAMETER", Message: legacy.message, Extra: map[string]any{"parameter": legacy.key}}
		}
	}
	if q["age_from_years"] != nil && q["age_to_years"] != nil && q.Int("age_from_years") > q.Int("age_to_years") {
		return out, commanderError(400, "INVALID_AGE_FILTER", "ageFromYears must be less than or equal to ageToYears")
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return out, err
	}
	args := []any{airline}
	filters := []string{"u.airline_id=$1"}
	add := func(clause string, value any) {
		args = append(args, value)
		filters = append(filters, fmt.Sprintf(clause, len(args)))
	}
	if kind == "instructors" {
		filters = append(filters, "EXISTS(SELECT 1 FROM training_session t WHERE t.instructor_id=u.id)")
	} else {
		filters = append(filters, "EXISTS(SELECT 1 FROM user_aircraft a WHERE a.user_id=u.id)")
	}
	if q["aircraft_id"] != nil {
		add("EXISTS(SELECT 1 FROM user_aircraft a WHERE a.user_id=u.id AND a.aircraft_id=$%d)", q["aircraft_id"])
	}
	if q["position_id"] != nil {
		add("i.position_id=$%d", q["position_id"])
	}
	if kind != "instructors" && q["pilot_id"] != nil {
		add("u.public_id=$%d", q["pilot_id"])
	}
	if q["age_from_years"] != nil || q["age_to_years"] != nil {
		filters = append(filters, "i.date_of_birth IS NOT NULL")
		// Use the server's local calendar date.
		today := time.Now()
		if q["age_to_years"] != nil {
			// The source computes both bounds for each specified age.
			if q.Int("age_to_years") >= int64(today.Year())-1 {
				return out, fmt.Errorf("birth date year out of range")
			}
			start, err := commanderSubtractYears(today, q.Int("age_to_years")+1)
			if err != nil {
				return out, err
			}
			add("i.date_of_birth >= $%d::date", start.AddDate(0, 0, 1))
		}
		if q["age_from_years"] != nil {
			if q.Int("age_from_years") >= int64(today.Year())-1 {
				return out, fmt.Errorf("birth date year out of range")
			}
			end, err := commanderSubtractYears(today, q.Int("age_from_years"))
			if err != nil {
				return out, err
			}
			add("i.date_of_birth <= $%d::date", end)
		}
	}
	users, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(r) FROM (SELECT u.id,u.public_id,i.first_name,i.last_name
 FROM users u LEFT JOIN user_info i ON i.id=u.id LEFT JOIN airline_position p ON p.id=i.position_id WHERE `+strings.Join(filters, " AND ")+` ORDER BY lower(coalesce(i.last_name,'')),lower(coalesce(i.first_name,'')),u.id) r`, args...)
	if err != nil {
		return out, err
	}
	ids := make([]int64, 0, len(users))
	for _, user := range users {
		ids = append(ids, user.number("id"))
	}
	var bound any
	if q["as_of_date"] != nil {
		day := q["as_of_date"].(time.Time)
		if day.Year() == 9999 && day.Month() == 12 && day.Day() == 31 {
			return out, fmt.Errorf("asOfDate bound out of range")
		}
		bound = day.AddDate(0, 0, 1)
	}
	args = []any{airline, ids, bound}
	if kind == "instructors" {
		args = append(args, q["pilot_id"])
	}
	out.airline, out.query, out.users, out.args, out.cte = airline, q, users, args, commanderAnalyticsCTE(kind)
	return out, nil
}

func (s *Service) commanderAnalyticsResponse(w http.ResponseWriter, r *http.Request, kind string) error {
	a, err := s.commanderAnalyticsInput(r, kind)
	if err != nil {
		return err
	}
	completedRows, err := queryRecords(r.Context(), s.Auth.DB, a.cte+`SELECT jsonb_build_object('id',owner_id) FROM latest_assessments GROUP BY owner_id`, a.args...)
	if err != nil {
		return err
	}
	completed := map[int64]bool{}
	for _, row := range completedRows {
		completed[row.number("id")] = true
	}
	filters := record{}
	for _, name := range []string{"aircraft_id", "pilot_id", "age_from_years", "age_to_years", "position_id", "as_of_date"} {
		filters[name] = a.query[name]
	}
	if filters["as_of_date"] != nil {
		filters["as_of_date"] = filters["as_of_date"].(time.Time).Format("2006-01-02")
	}
	var items []record
	if kind == "trend" {
		items, err = commanderAnalyticsTrend(r.Context(), s.Auth.DB, a)
	} else {
		items, err = commanderAnalyticsDistribution(r.Context(), s.Auth.DB, a, completed)
	}
	if err != nil {
		return err
	}
	owner := "pilots"
	if kind == "instructors" {
		owner = "instructors"
	}
	platform.WriteJSON(w, 200, commanderWire(record{"total_" + owner: len(a.users), owner + "_with_completed_training": len(completed), "filters": filters, "items": items}))
	return nil
}

func commanderAnalyticsCompetences(ctx context.Context, db runtimeDB, airline int64) ([]record, error) {
	return queryRecords(ctx, db, `SELECT to_jsonb(r) FROM (SELECT id AS competence_id,code AS competence_code,name AS competence_name,order_index FROM competence WHERE airline_id=$1 ORDER BY order_index,id) r`, airline)
}
