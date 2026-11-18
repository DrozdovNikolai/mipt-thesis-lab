package training

import "github.com/google/uuid"

func (e *airlineClone) cloneScenarios() {
	for _, source := range e.rows["scenario"] {
		row := source.project("content_version code title engines comments status published_at valid_until")
		row["airline_id"], row["created_by"], row["updated_by"] = e.target, e.actor, e.actor
		row["aircraft_id"] = e.mapped("aircraft_airline", source["aircraft_id"], "scenario.aircraft_id", true)
		id := e.add("scenario", row, source["id"], "scenarios")
		day := int64(1)
		for index, module := range e.children("module", "scenario_id", source.number("id")) {
			if index > 0 {
				links := e.children("scenario_day_module", "module_id", module.number("id"))
				if len(links) > 0 && links[0].number("day_index") > day {
					day = links[0].number("day_index")
				}
			}
			row := module.project("order_index duration_minutes")
			row["scenario_id"], row["client_uid"] = id, uuid.NewString()
			row["content_subcolumn_id"] = e.mapped("scenario_content_subcolumn", module["content_subcolumn_id"], "module.content_subcolumn_id", false)
			moduleID := e.add("module", row, nil, "modules")
			e.add("scenario_day_module", record{"scenario_id": id, "module_id": moduleID, "day_index": day, "order_index": module["order_index"]}, nil, "")
			for _, exercise := range e.children("exercise", "module_id", module.number("id")) {
				e.cloneExercise(exercise, moduleID)
			}
		}
	}
	// Preserve source set/label/link order; links to excluded scenarios disappear.
	for _, set := range e.rows["scenario_content_set"] {
		for _, label := range e.children("scenario_content_set_label", "content_set_id", set.number("id")) {
			for _, link := range e.children("scenario_content_set_label_scenario", "label_id", label.number("id")) {
				if e.lookup("scenario", link["scenario_id"]) == nil {
					continue
				}
				e.add("scenario_content_set_label_scenario", record{
					"label_id":    e.mapped("scenario_content_set_label", link["label_id"], "scenario_content_set_label_scenario.label_id", true),
					"scenario_id": e.mapped("scenario", link["scenario_id"], "scenario_content_set_label_scenario.scenario_id", true),
				}, nil, "scenario_label_links")
			}
		}
	}
}

func (e *airlineClone) cloneExercise(source record, moduleID int64) {
	var paramID any
	if param := e.lookup("exercise_param", source["exercise_param_id"]); param != nil {
		row := param.project("intensity zfw_t guidance_doc guidance_plain_text")
		row["original_tl_id"] = e.takeoff(param["original_tl_id"])
		row["destination_tl_id"] = e.takeoff(param["destination_tl_id"])
		paramID = e.add("exercise_param", row, nil, "")
	}
	row := source.project("kind order_index duration_minutes crew_member_number")
	if row["kind"] == nil || row["kind"] == "" {
		row["kind"] = "standard"
	}
	row["module_id"], row["client_uid"], row["exercise_param_id"] = moduleID, uuid.NewString(), paramID
	id := e.add("exercise", row, nil, "exercises")
	e.cloneElementLinks("exercise_element", "exercise_id", source.number("id"), id, "exercise_elements")
	e.cloneCompetenceLinks("exercise_competence", "exercise_id", source.number("id"), id, "exercise_competences")
}
