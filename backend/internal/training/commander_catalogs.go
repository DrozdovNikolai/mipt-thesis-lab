package training

import (
	"fmt"
	"net/http"
	"strings"

	"north55/backend/internal/platform"
)

func (s *Service) registerCommanderCatalogs(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/commander"
	mux.HandleFunc("GET "+p+"/competences", platform.Wrap(s.commanderCompetences))
	mux.HandleFunc("GET "+p+"/aircraft", platform.Wrap(s.commanderAircraft))
	mux.HandleFunc("GET "+p+"/scenarios", platform.Wrap(s.commanderScenarios))
	mux.HandleFunc("GET "+p+"/flight-types", platform.Wrap(s.commanderFlightTypes))
	mux.HandleFunc("POST "+p+"/flight-types", platform.Wrap(s.commanderCreateFlightType))
	mux.HandleFunc("PUT "+p+"/flight-types/{flight_type_id}", platform.Wrap(s.commanderUpdateFlightType))
	mux.HandleFunc("PUT "+p+"/flight-types/{flight_type_id}/thresholds", platform.Wrap(s.commanderReplaceThresholds))
	mux.HandleFunc("DELETE "+p+"/flight-types/{flight_type_id}", platform.Wrap(s.commanderDeleteFlightType))
}

func (s *Service) commanderCompetences(w http.ResponseWriter, r *http.Request) error {
	return s.commanderCatalog(w, r, `SELECT to_jsonb(c) FROM (SELECT id,code,name,description,created_at,updated_at FROM competence WHERE airline_id=$1 ORDER BY order_index,id) c`)
}
func (s *Service) commanderAircraft(w http.ResponseWriter, r *http.Request) error {
	return s.commanderCatalog(w, r, `SELECT to_jsonb(a) FROM (SELECT `+aircraftColumns+` FROM aircraft_airline WHERE airline_id=$1 ORDER BY lower(code),id) a`)
}
func (s *Service) commanderCatalog(w http.ResponseWriter, r *http.Request, query string) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	items, err := queryRecords(r.Context(), s.Auth.DB, query, airline)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(items))
	return nil
}

func (s *Service) commanderScenarios(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(),
		platform.Field{Name: "q", Kind: "string", Max: 255, Nullable: true},
		platform.Field{Name: "aircraft_id", Alias: "aircraftId", Kind: "integer", Min: 1, Nullable: true},
		platform.Field{Name: "limit", Kind: "integer", Min: 1, Max: 200, Default: int64(20)},
		platform.Field{Name: "offset", Kind: "integer", NonNegative: true, Default: int64(0)},
	)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	args := []any{airline}
	where := []string{"s.airline_id=$1"}
	if needle := pythonTrim(q.String("q")); needle != "" {
		args = append(args, "%"+needle+"%")
		where = append(where, fmt.Sprintf("(s.title ILIKE $%d OR s.code ILIKE $%d)", len(args), len(args)))
	}
	if q["aircraft_id"] != nil {
		args = append(args, q["aircraft_id"])
		where = append(where, fmt.Sprintf("s.aircraft_id=$%d", len(args)))
	}
	filter := strings.Join(where, " AND ")
	var total int64
	if err = s.Auth.DB.QueryRow(r.Context(), "SELECT count(*) FROM scenario s WHERE "+filter, args...).Scan(&total); err != nil {
		return err
	}
	args = append(args, q.Int("limit"), q.Int("offset"))
	items, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(r) FROM (SELECT s.id,s.title,s.status,s.aircraft_id,a.code AS aircraft_code FROM scenario s LEFT JOIN aircraft_airline a ON a.id=s.aircraft_id WHERE `+filter+fmt.Sprintf(" ORDER BY lower(s.title),s.id LIMIT $%d OFFSET $%d) r", len(args)-1, len(args)), args...)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(record{"total": total, "limit": q["limit"], "offset": q["offset"], "items": items}))
	return nil
}
