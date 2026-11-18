package training

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func (s *Service) registerCompetencies(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("GET "+p+"/competencies", platform.Wrap(s.assessmentCompetencies))
	mux.HandleFunc("GET "+p+"/competences", platform.Wrap(s.listCompetences))
	mux.HandleFunc("POST "+p+"/competences", platform.Wrap(s.writeCompetence))
	mux.HandleFunc("PUT "+p+"/competences/order", platform.Wrap(s.reorderCompetences))
	mux.HandleFunc("PUT "+p+"/competences/{competence_id}", platform.Wrap(s.writeCompetence))
	mux.HandleFunc("DELETE "+p+"/competences/{competence_id}", platform.Wrap(s.retireCompetence))
	p += "/competences/{competence_id}/behavioural-indicators"
	mux.HandleFunc("GET "+p, platform.Wrap(s.manageIndicators))
	mux.HandleFunc("POST "+p, platform.Wrap(s.manageIndicators))
	mux.HandleFunc("PUT "+p+"/{indicator_id}", platform.Wrap(s.manageIndicators))
	mux.HandleFunc("DELETE "+p+"/{indicator_id}", platform.Wrap(s.manageIndicators))
}

func activeCompetences(ctx context.Context, db runtimeDB, airline int64) ([]record, error) {
	return queryRecords(ctx, db, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND retired_at IS NULL ORDER BY order_index,id`, airline)
}

func activeCompetence(ctx context.Context, db runtimeDB, airline, id int64) (record, error) {
	row, err := queryRecord(ctx, db, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND id=$2 AND retired_at IS NULL`, airline, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, platform.Error(404, "Competence not found")
	}
	return row, err
}

func (s *Service) listCompetences(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	rows, err := activeCompetences(r.Context(), s.Auth.DB, airline)
	if err != nil {
		return err
	}
	for i, row := range rows {
		rows[i] = row.project("id code name description created_at updated_at")
	}
	platform.WriteJSON(w, 200, commanderWire(rows))
	return nil
}

func (s *Service) assessmentCompetencies(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	if user.AirlineID == nil || *user.AirlineID == 0 {
		platform.WriteJSON(w, 200, record{"items": []record{}, "gradingScale": nil})
		return nil
	}
	airline := *user.AirlineID
	rows, err := activeCompetences(r.Context(), s.Auth.DB, airline)
	if err != nil {
		return err
	}
	ids := make([]int64, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.number("id"))
	}
	indicators, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(b) FROM behavioural_indicator b WHERE competence_id=ANY($1::bigint[]) AND retired_at IS NULL ORDER BY order_index,id`, ids)
	if err != nil {
		return err
	}
	byCompetence := map[int64][]record{}
	for _, indicator := range indicators {
		if helperPositive(indicator.text("code")) {
			continue
		}
		item := indicator.project("id code short_name order_index")
		item["long_name"], item["name"] = indicator["name"], indicator["name"]
		if indicator.text("short_name") != "" {
			item["name"] = indicator["short_name"]
		}
		id := indicator.number("competence_id")
		byCompetence[id] = append(byCompetence[id], item)
	}
	items := []record{}
	for _, row := range rows {
		item := row.project("id name order_index")
		item["code"] = assessmentUpper(row.text("code"))
		values := byCompetence[row.number("id")]
		if values == nil {
			values = []record{}
		}
		item["indicators"] = values
		items = append(items, item)
	}
	scheme, err := activeGrading(r.Context(), s.Auth.DB, airline)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(400, "Active grading scheme is not configured for airline")
	}
	if err != nil {
		return err
	}
	grading, err := readGradingResponse(r.Context(), s.Auth.DB, scheme, false)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(record{"items": items, "grading_scale": grading}))
	return nil
}
