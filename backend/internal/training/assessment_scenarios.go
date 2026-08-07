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

func (s *Service) registerAssessmentScenarios(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/assessment"
	mux.HandleFunc("GET "+p+"/scenarios", platform.Wrap(s.listAssessmentScenarios))
	for _, entry := range []struct{ route, field string }{
		{"/scenario-days/{scenario_day_module_id}/exercises", "scenario_day_module_id"},
		{"/scenarios/by-id/{scenario_id}/exercises", "scenario_id"},
		{"/scenarios/{scenario_name}/exercises", "scenario_name"},
	} {
		mux.HandleFunc("GET "+p+entry.route, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			return s.readAssessmentScenario(w, r, entry.field)
		}))
	}
}

func assessmentAirline(id *int64) any {
	if id == nil || *id == 0 {
		return nil
	}
	return *id
}

func scenarioDayLabel(title string, day, count int64) string {
	if count > 1 {
		return fmt.Sprintf("%s-DAY %d", title, day)
	}
	return title
}

func (s *Service) listAssessmentScenarios(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	// This selector follows its existing optional airline scope. It does not
	// filter assigned aircraft or deleted_at; the detail readers have a separate
	// active/deleted contract. A row represents a day, not a whole scenario.
	rows, err := queryRecords(r.Context(), s.Auth.DB, `WITH ranked AS (
		SELECT d.*, row_number() OVER(PARTITION BY scenario_id,day_index ORDER BY order_index,module_id,id) AS rank
		FROM scenario_day_module d
	), counts AS (SELECT scenario_id,count(DISTINCT day_index) AS days_count FROM scenario_day_module GROUP BY scenario_id)
	SELECT to_jsonb(s)||jsonb_build_object('scenario_day_module_id',d.id,'day_index',d.day_index,'days_count',n.days_count,'aircraft_code',a.code)
	FROM scenario s JOIN ranked d ON d.scenario_id=s.id AND d.rank=1 JOIN counts n ON n.scenario_id=s.id
	LEFT JOIN aircraft_airline a ON a.id=s.aircraft_id
	WHERE s.status='PUBLISHED' AND ($1::bigint IS NULL OR s.airline_id=$1)
	ORDER BY s.created_at,s.id,d.day_index`, assessmentAirline(user.AirlineID))
	if err != nil {
		return err
	}
	items := []record{}
	for _, row := range rows {
		item := row.project("id scenario_day_module_id day_index days_count code status aircraft_code comments")
		item["scenario_id"], item["scenario_title"] = row["id"], row["title"]
		item["title"] = scenarioDayLabel(row.text("title"), row.number("day_index"), row.number("days_count"))
		item["created_at"] = nil
		if date := row.text("created_at"); date != "" {
			item["created_at"] = strings.SplitN(date, "T", 2)[0]
		}
		items = append(items, item)
	}
	platform.WriteJSON(w, 200, commanderWire(record{"items": items}))
	return nil
}

func (s *Service) readAssessmentScenario(w http.ResponseWriter, r *http.Request, field string) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	var id any
	var day *int64
	ctx, airline := r.Context(), assessmentAirline(user.AirlineID)
	if field == "scenario_name" {
		rows, err := queryRecords(ctx, s.Auth.DB, `SELECT jsonb_build_object('id',id) FROM scenario WHERE title=$1 AND deleted_at IS NULL AND ($2::bigint IS NULL OR airline_id=$2)`, pythonTrim(r.PathValue(field)), airline)
		if err != nil {
			return err
		}
		if len(rows) == 0 {
			return platform.Error(404, "Scenario not found")
		}
		if len(rows) > 1 {
			return platform.Error(409, "Scenario title is not unique; use /assessment/scenarios/by-id/{scenario_id}/exercises")
		}
		id = rows[0]["id"]
	} else {
		path, _, err := libraryInput(r, nil, field)
		if err != nil {
			return err
		}
		id = path[field]
		if field == "scenario_day_module_id" {
			row, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(d) FROM scenario_day_module d JOIN scenario s ON s.id=d.scenario_id WHERE d.id=$1 AND s.status<>'ARCHIVED' AND s.deleted_at IS NULL AND ($2::bigint IS NULL OR s.airline_id=$2)`, id, airline)
			if errors.Is(err, pgx.ErrNoRows) {
				return platform.Error(404, "Scenario day not found")
			}
			if err != nil {
				return err
			}
			value := row.number("day_index")
			day = &value
			id = row["scenario_id"]
		}
	}
	row, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(s) FROM scenario s WHERE s.id=$1 AND s.status<>'ARCHIVED' AND s.deleted_at IS NULL AND ($2::bigint IS NULL OR s.airline_id=$2)`, id, airline)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Scenario not found")
	}
	if err != nil {
		return err
	}
	graph, err := loadSourceScenarioMode(ctx, s.Auth.DB, row.number("id"), true)
	if err != nil {
		return err
	}
	// Instructor uses Scenario.day_modules, including legacy inconsistent links.
	// The editor loader instead reads Module.day_link; replace just that relation.
	graph.Days, err = queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(d) FROM scenario_day_module d WHERE d.scenario_id=$1`, row["id"])
	if err != nil {
		return err
	}
	response, err := s.assessmentScenarioResponse(ctx, graph, day)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(response))
	return nil
}
