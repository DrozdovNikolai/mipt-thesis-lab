package training

import (
	"context"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/google/uuid"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func (s *Service) registerAssessmentUsers(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("POST "+p+"/users", platform.Wrap(s.createAssessmentUser))
	mux.HandleFunc("GET "+p+"/users/search", platform.Wrap(s.searchAssessmentUsers))
	mux.HandleFunc("GET "+p+"/users/profile", platform.Wrap(s.assessmentUserProfile))
	mux.HandleFunc("GET "+p+"/exercise-kinds", platform.Wrap(s.exerciseKinds))
}

func assessmentUserWords(raw string) string {
	return strings.Join(strings.FieldsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }), " ")
}

func (s *Service) exerciseKinds(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "training:read"); err != nil {
		return err
	}
	items := []record{}
	for i, code := range []string{"standard", "preparation", "coffee_break", "individual"} {
		items = append(items, record{"code": code, "label": []string{"Exercise", "Preparation", "Coffee break", "Individual"}[i], "is_service": i != 0, "allows_elements": i == 0, "allows_params": i == 0, "allows_competence_ids": i == 0, "allows_crew_member_number": i == 0 || i == 3})
	}
	platform.WriteJSON(w, 200, commanderWire(items))
	return nil
}

// The assessment selector has its own ranking and optional tenant scope. It
// deliberately keeps inactive users and requires a UserInfo row.
func assessmentUserSelection(ctx context.Context, db runtimeDB, airline *int64, name string, userID any, limit int64) ([]record, error) {
	args, where := []any{}, []string{"true"}
	bind := func(value any) string { args = append(args, value); return fmt.Sprintf("$%d", len(args)) }
	order := ""
	if userID != nil {
		where = append(where, "u.id="+bind(userID))
	} else {
		for _, word := range strings.Split(name, " ") {
			needle := bind("%" + word + "%")
			where = append(where, "(i.first_name ILIKE "+needle+" OR i.last_name ILIKE "+needle+" OR i.license_number ILIKE "+needle+" OR (coalesce(i.first_name,'')||' '||coalesce(i.last_name,'')) ILIKE "+needle+" OR (coalesce(i.last_name,'')||' '||coalesce(i.first_name,'')) ILIKE "+needle+")")
		}
		lower := cases.Lower(language.Und).String(name)
		exact, prefix := bind(lower), bind(lower+"%")
		order = " ORDER BY CASE WHEN lower(coalesce(i.license_number,''))=" + exact + " THEN 0 WHEN lower(coalesce(i.last_name,''))=" + exact + " THEN 1 WHEN lower(coalesce(i.first_name,''))=" + exact + " THEN 2 WHEN (lower(coalesce(i.first_name,''))||' '||lower(coalesce(i.last_name,'')))=" + exact + " THEN 3 WHEN (lower(coalesce(i.last_name,''))||' '||lower(coalesce(i.first_name,'')))=" + exact + " THEN 4 WHEN lower(coalesce(i.license_number,'')) LIKE " + prefix + " THEN 5 WHEN lower(coalesce(i.last_name,'')) LIKE " + prefix + " THEN 6 WHEN lower(coalesce(i.first_name,'')) LIKE " + prefix + " THEN 7 ELSE 8 END,lower(coalesce(i.last_name,'')),lower(coalesce(i.first_name,'')),u.id"
	}
	if airline != nil && *airline != 0 {
		where = append(where, "u.airline_id="+bind(*airline))
	}
	limitParam := bind(limit)
	return queryRecords(ctx, db, "SELECT jsonb_build_object('public_id',u.public_id,'airline',a.name) FROM users u JOIN user_info i ON i.id=u.id LEFT JOIN airline a ON a.id=u.airline_id WHERE "+strings.Join(where, " AND ")+order+" LIMIT "+limitParam, args...)
}

func assessmentUserInfo(user *auth.User, airline any) record {
	item := record{"id": user.InternalID, "email": user.Email, "photo_url": "", "airline": airline}
	for key, value := range map[string]*string{"first_name": user.FirstName, "last_name": user.LastName, "position": user.Position, "license": user.LicenseNumber, "phone": user.Phone, "photo_url": user.PhotoURL} {
		if value != nil {
			item[key] = *value
		}
	}
	if user.PositionID != nil {
		item["position_id"] = *user.PositionID
	}
	codes := map[string]bool{}
	for _, raw := range user.AircraftCodes {
		if code := pythonTrim(raw); code != "" {
			codes[code] = true
		}
	}
	ordered := []string{}
	for code := range codes {
		ordered = append(ordered, code)
	}
	sort.Strings(ordered)
	if len(ordered) > 0 {
		item["aircraft_code"] = ordered[0]
	}
	return item
}

// response_model_exclude_none applies to the whole assessment read response.
func assessmentUserWire(value any) any {
	var omit func(any) any
	omit = func(value any) any {
		switch v := value.(type) {
		case map[string]any:
			out := map[string]any{}
			for key, item := range v {
				if item != nil {
					out[key] = omit(item)
				}
			}
			return out
		case []any:
			out := make([]any, 0, len(v))
			for _, item := range v {
				out = append(out, omit(item))
			}
			return out
		}
		return value
	}
	return omit(commanderWire(value))
}

func (s *Service) searchAssessmentUsers(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), platform.Field{Name: "q", Kind: "string", Max: 120, Default: ""}, platform.Field{Name: "limit", Kind: "integer", Min: 1, Max: 20, Default: int64(8)})
	if err != nil {
		return err
	}
	name := assessmentUserWords(q.String("q"))
	items := []record{}
	if utf8.RuneCountInString(name) >= 2 {
		selected, err := assessmentUserSelection(r.Context(), s.Auth.DB, user.AirlineID, name, nil, q.Int("limit"))
		if err != nil {
			return err
		}
		ids := []uuid.UUID{}
		for _, row := range selected {
			ids = append(ids, uuid.MustParse(row.text("public_id")))
		}
		users, err := s.Auth.LoadUsers(r.Context(), ids)
		if err != nil {
			return err
		}
		for i, row := range selected {
			if found := users[ids[i]]; found != nil {
				items = append(items, assessmentUserInfo(found, row["airline"]))
			}
		}
	}
	platform.WriteJSON(w, 200, assessmentUserWire(record{"items": items}))
	return nil
}
