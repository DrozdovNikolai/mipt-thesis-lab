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

func assessmentScenarioModules(graph sourceScenario, day *int64) ([]sourceModule, map[int64][2]int64) {
	meta := map[int64][2]int64{}
	for _, link := range graph.Days {
		meta[link.number("module_id")] = [2]int64{link.number("day_index"), link.number("order_index")}
	}
	modules := []sourceModule{}
	for _, module := range graph.Modules {
		id := module.Row.number("id")
		if _, ok := meta[id]; !ok {
			meta[id] = [2]int64{1, module.Row.number("order_index")}
		}
		if day == nil || meta[id][0] == *day {
			modules = append(modules, module)
		}
	}
	sort.SliceStable(modules, func(i, j int) bool {
		a, b := modules[i].Row, modules[j].Row
		am, bm := meta[a.number("id")], meta[b.number("id")]
		for k := range 2 {
			if am[k] != bm[k] {
				return am[k] < bm[k]
			}
		}
		if a.number("order_index") != b.number("order_index") {
			return a.number("order_index") < b.number("order_index")
		}
		return a.number("id") < b.number("id")
	})
	return modules, meta
}

func assessmentElementContent(elements []record, colors map[int64]string) ([]record, error) {
	ids := make([]int64, len(elements))
	offset := int64(0)
	if len(elements) > 0 && elements[0].number("order_index") == 0 {
		offset = 1
	}
	seen, valid := map[int64]bool{}, true
	for i, e := range elements {
		id := e.number("order_index") + offset
		ids[i] = id
		if id <= 0 || seen[id] {
			valid = false
		}
		seen[id] = true
	}
	if !valid {
		for i := range ids {
			ids[i] = int64(i + 1)
		}
	}
	out := []record{}
	for i, link := range elements {
		element := link.object("element")
		if element == nil {
			continue
		}
		severity := ""
		if element["severity"] != nil {
			severity = map[int64]string{8: "HIGH", 5: "MEDIUM", 2: "LOW"}[element.number("severity")]
			if severity == "" {
				severity = fmt.Sprint(element["severity"])
			}
		}
		item := record{"id": ids[i], "element_id": element["id"], "type": severity, "elements": element["name"], "details": link.text("details"), "color_hex": nil}
		if color, ok := colors[element.number("id")]; ok {
			item["color_hex"] = color
		}
		profile := strings.ToUpper(pythonTrim(link.text("profile_type")))
		if !libraryContainsString([]string{"FLAT", "UP", "DOWN", "LINKED"}, profile) {
			profile = "FLAT"
		}
		for _, field := range []string{"starting_height", "ending_height"} {
			if link[field] != nil {
				if link.number(field) < 0 {
					return nil, fmt.Errorf("invalid stored element height")
				}
				item[field] = link[field]
			}
		}
		if profile != "FLAT" || item["starting_height"] != nil || item["ending_height"] != nil {
			item["profile_type"] = profile
		}
		out = append(out, item)
	}
	return out, nil
}

func (s *Service) assessmentScenarioResponse(ctx context.Context, graph sourceScenario, day *int64) (record, error) {
	modules, meta := assessmentScenarioModules(graph, day)
	ids := []int64{}
	for _, module := range modules {
		for _, e := range module.Exercises {
			for _, element := range e.Elements {
				ids = append(ids, element.number("element_id"))
			}
		}
	}
	colors, err := loadElementColors(ctx, s.Auth.DB, ids)
	if err != nil {
		return nil, err
	}
	setup, counts := int64(1), map[int64]int64{}
	exercises := []record{}
	for _, module := range modules {
		moduleDay := meta[module.Row.number("id")][0]
		counts[moduleDay]++
		label := fmt.Sprintf("Module %d", counts[moduleDay])
		sort.SliceStable(module.Exercises, func(i, j int) bool {
			a, b := module.Exercises[i].Row, module.Exercises[j].Row
			if a.number("order_index") != b.number("order_index") {
				return a.number("order_index") < b.number("order_index")
			}
			return a.number("id") < b.number("id")
		})
		for _, source := range module.Exercises {
			e, param := source.Row, source.Param
			kind := e.text("kind")
			if kind == "" {
				kind = "standard"
			}
			service := kind == "preparation" || kind == "coffee_break"
			name, display, step, setupLabel := label, "", "", ""
			if service {
				display = map[string]string{"preparation": "Preparation", "coffee_break": "Coffee break"}[kind]
				name = display
				step = display
			} else {
				setupLabel = fmt.Sprint(setup)
				display = "Exercise " + setupLabel
				step = setupLabel
				setup++
			}
			guidance := param["guidance_doc"]
			if guidance != nil {
				if _, ok := guidance.(map[string]any); !ok {
					return nil, fmt.Errorf("invalid stored guidance document")
				}
			}
			content, err := assessmentElementContent(source.Elements, colors)
			if err != nil {
				return nil, err
			}
			images := []record{}
			for _, image := range source.Images {
				images = append(images, record(snapshotMedia(image, s.Auth.Config.APIPrefix+"/training/exercise-images/", "id")))
			}
			pf := ""
			if e.number("crew_member_number") != 0 {
				pf = fmt.Sprintf("CM%d", e.number("crew_member_number"))
			}
			aircraft := graph.Row["aircraft_code"]
			if aircraft == nil {
				aircraft = fmt.Sprint(graph.Row["aircraft_id"])
			}
			performance, err := performanceColumns(param)
			if err != nil {
				return nil, err
			}
			exercises = append(exercises, record{"id": e["id"], "resolved_for_assessment_id": nil, "setup": setupLabel, "kind": kind, "source_kind": kind, "name": name, "display_label": display, "step_label": step, "is_service": service, "duration": e.number("duration_minutes"), "pf": pf, "aircraft": record{"ac_type": aircraft, "engines": graph.Row.text("engines")}, "performance": record{"departure": snapshotPhase(performance, "departure"), "arrival": snapshotPhase(performance, "arrival")}, "guidance_doc": guidance, "guidance_plain_text": param.text("guidance_plain_text"), "guidance": param.text("guidance_plain_text"), "content": content, "images": images})
		}
	}
	pdfs := []record{}
	var first any
	for _, pdf := range graph.Pdfs {
		pdfs = append(pdfs, record(snapshotMedia(pdf, s.Auth.Config.APIPrefix+"/training/scenario-pdfs/", "id")))
	}
	if len(pdfs) > 0 {
		first = pdfs[0]
	}
	label := graph.Row.text("title")
	if day != nil {
		days := map[int64]bool{}
		for _, link := range graph.Days {
			days[link.number("day_index")] = true
		}
		label = scenarioDayLabel(label, *day, int64(max(1, len(days))))
	}
	return record{"scenario": label, "exercises": exercises, "pdfs": pdfs, "pdf": first}, nil
}
