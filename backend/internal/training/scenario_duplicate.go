package training

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func duplicateScenarioTitle(source, requested string) string {
	if title := pythonTrim(requested); title != "" {
		return title
	}
	base := pythonTrim(source)
	if base == "" {
		base = "Scenario"
	}
	const suffix = " (copy)"
	runes := []rune(base)
	if len(runes)+len(suffix) <= 255 {
		return base + suffix
	}
	return pythonTrim(string(runes[:255-len(suffix)])) + suffix
}

func duplicateScenarioSnapshot(source sourceScenario, targetID int64, clearColumns bool) (record, map[int64]string, error) {
	days := map[int64]int64{}
	for _, day := range source.Days {
		days[day.number("module_id")] = max(1, day.number("day_index"))
	}
	modules, originalIDs := []record{}, map[int64]string{}
	previous, exerciseID := int64(1), int64(-1)
	for i, module := range source.Modules {
		moduleID := -int64(i + 1)
		day := max(previous, days[module.Row.number("id")])
		if i == 0 {
			day = 1
		}
		m := module.Row.project("order_index duration_minutes content_subcolumn_id")
		m["id"], m["client_uid"], m["scenario_id"] = moduleID, uuid.NewString(), targetID
		m["day_index"], m["day_start"] = day, i > 0 && day > previous
		previous = day
		if clearColumns {
			m["content_subcolumn_id"] = nil
		}
		exercises := []record{}
		for _, exercise := range module.Exercises {
			e := exercise.Row.project("kind order_index duration_minutes crew_member_number")
			e["id"], e["client_uid"], e["module_id"] = exerciseID, uuid.NewString(), moduleID
			originalIDs[exercise.Row.number("id")] = fmt.Sprint(exerciseID)
			exerciseID--
			if e.text("kind") == "" {
				e["kind"] = "standard"
			}
			competences := []int64{}
			for _, c := range exercise.Competences {
				competences = append(competences, c.number("id"))
			}
			e["competence_ids"] = competences
			elements := []record{}
			for _, element := range exercise.Elements {
				elements = append(elements, element.project("element_id order_index details starting_height ending_height profile_type"))
			}
			e["elements"], e["params"] = elements, editorSourceParams(exercise.Param)
			exercises = append(exercises, e)
		}
		m["exercises"] = exercises
		modules = append(modules, m)
	}
	// This model is built inside the source service. Invalid persisted content
	// raises a server error after the empty destination scenario was committed.
	raw, err := json.Marshal(record{"modules": modules})
	if err != nil {
		return nil, nil, err
	}
	var input any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err = decoder.Decode(&input); err != nil {
		return nil, nil, err
	}
	var fatal error
	model := scenarioSnapshotSchema(nil, &fatal)
	value, err := platform.ValidateObject(input, nil, model)
	if err != nil || fatal != nil {
		return nil, nil, fmt.Errorf("invalid duplicate source snapshot: %v %v", err, fatal)
	}
	return record(scenarioModelDefaults(value, model)), originalIDs, nil
}
