package training

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"north55/backend/internal/platform"
)

const scenarioEditorFields = "id airline_id aircraft_id aircraft_code content_version code title engines comments status published_at valid_until archived_by archived_at deleted_by deleted_at created_at updated_at"

func scenarioWire(row record) any {
	for _, key := range []string{"archived_at", "deleted_at", "published_at", "valid_until", "expires_at"} {
		if value, ok := row[key].(string); ok {
			if stamp, err := time.Parse(time.RFC3339Nano, value); err == nil {
				row[key] = apiTime(&stamp)
			}
		}
	}
	return commanderWire(row)
}

func scenarioMediaDTO(row record, prefix string, pdf bool) record {
	owner, resource := "exercise_id", "/training/exercise-images/"
	if pdf {
		owner, resource = "scenario_id", "/training/scenario-pdfs/"
	}
	value := row.project("id " + owner + " order_index original_filename display_name content_type size_bytes sha256 created_at updated_at")
	value["url"] = prefix + resource + row.text("storage_key")
	return value
}

func scenarioTakeoffDTO(row record) (any, error) {
	if row == nil {
		return nil, nil
	}
	data := row.project("id " + libraryTLFields)
	for _, key := range strings.Fields(libraryTakeoffFields) {
		data[key] = row.object("takeoff_details")[key]
	}
	value, err := platform.ValidateObject(map[string]any(data), nil, libraryTLModel(nil))
	if err != nil {
		return nil, fmt.Errorf("invalid stored scenario TL: %v", err)
	}
	out := record(value)
	out["id"] = row["id"]
	return out, nil
}

func scenarioExerciseDTO(e *sourceExercise, prefix string) (record, error) {
	value := e.Row.project("id client_uid module_id kind order_index duration_minutes crew_member_number created_at updated_at")
	if value["kind"] == nil || value["kind"] == "" {
		value["kind"] = "standard"
	}
	if !libraryContainsString([]string{"standard", "individual", "preparation", "coffee_break"}, fmt.Sprint(value["kind"])) {
		return nil, fmt.Errorf("invalid stored exercise kind")
	}
	items := []any{}
	for _, row := range e.Elements {
		item, err := libraryBlockElementDTO(row)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	competences := append([]record{}, e.Competences...)
	sort.SliceStable(competences, func(i, j int) bool { return competences[i].number("id") < competences[j].number("id") })
	for i := range competences {
		competences[i] = competences[i].project("id code name description created_at updated_at")
	}
	images := []record{}
	for _, row := range e.Images {
		images = append(images, scenarioMediaDTO(row, prefix, false))
	}
	value["elements"], value["competences"], value["images"], value["params"] = items, competences, images, nil
	if e.Param != nil {
		params := e.Param.project("id intensity zfw_t guidance_doc guidance_plain_text")
		if params["guidance_doc"] != nil {
			if _, ok := params["guidance_doc"].(map[string]any); !ok {
				return nil, fmt.Errorf("invalid stored guidance document")
			}
		}
		for _, key := range []string{"original_tl", "destination_tl"} {
			var err error
			params[key], err = scenarioTakeoffDTO(e.Param.object(key))
			if err != nil {
				return nil, err
			}
		}
		// ExerciseParamRead keeps the stored guidance and ZFW unchanged. Only the
		// nested TL model has before validators in this editor response.
		value["params"] = params
	}
	return value, nil
}

func scenarioEditorDTO(graph sourceScenario, prefix string) (any, error) {
	value := graph.Row.project(scenarioEditorFields)
	modules, pdfs := []record{}, []record{}
	for _, row := range graph.Pdfs {
		pdfs = append(pdfs, scenarioMediaDTO(row, prefix, true))
	}
	value["pdfs"], value["pdf"] = pdfs, nil
	if len(pdfs) > 0 {
		value["pdf"] = pdfs[0]
	}
	days := map[int64]int64{}
	for _, day := range graph.Days {
		days[day.number("module_id")] = max(1, day.number("day_index"))
	}
	previous := int64(1)
	for i, module := range graph.Modules {
		m := module.Row.project("id client_uid scenario_id order_index duration_minutes content_subcolumn_id created_at updated_at")
		day := max(1, days[module.Row.number("id")])
		if i == 0 {
			day = 1
		}
		day = max(day, previous)
		m["day_index"], m["day_start"] = day, i > 0 && day > previous
		previous = day
		m["content_subcolumn"] = nil
		if col := module.Row.object("content_subcolumn"); col != nil {
			m["content_subcolumn"] = col.project("id content_set_id name order_index created_at updated_at")
		}
		exercises := []record{}
		for _, exercise := range module.Exercises {
			e, err := scenarioExerciseDTO(exercise, prefix)
			if err != nil {
				return nil, err
			}
			exercises = append(exercises, e)
		}
		m["exercises"] = exercises
		modules = append(modules, m)
	}
	value["modules"] = modules
	return scenarioWire(value), nil
}

func scenarioGet(ctx context.Context, db runtimeDB, id any, airline int64, aircraft []int64, archived, deleted bool) (record, error) {
	row, err := libraryFind(ctx, db, "scenario", id)
	if err != nil {
		return nil, err
	}
	if row == nil || row.number("airline_id") != airline || !libraryContains(aircraft, row.number("aircraft_id")) || (!deleted && row["deleted_at"] != nil) || (!archived && (row["status"] == nil || row.text("status") == "ARCHIVED")) {
		return nil, commanderError(404, "SCENARIO_NOT_FOUND", "Scenario not found")
	}
	return row, nil
}

func (s *Service) scenarioReadDTO(ctx context.Context, db runtimeDB, id int64) (any, error) {
	graph, err := loadSourceScenarioMode(ctx, db, id, true)
	if err != nil {
		return nil, err
	}
	return scenarioEditorDTO(graph, s.Auth.Config.APIPrefix)
}
