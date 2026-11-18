package training

func (e *airlineClone) cloneCatalogs() {
	for _, source := range e.rows["grading_scheme"] {
		row := source.project("name version is_active")
		row["airline_id"] = e.target
		id := e.add("grading_scheme", row, source["id"], "grading_schemes")
		for _, value := range e.children("grading_scale_value", "grading_scheme_id", source.number("id")) {
			row := value.project("code label score_numeric grade_weight order_index color_hex is_pass")
			row["grading_scheme_id"] = id
			e.add("grading_scale_value", row, nil, "grading_scale_values")
		}
	}
	for _, source := range e.rows["aircraft_airline"] {
		row := source.project("code name active color_hex")
		row["airline_id"] = e.target
		e.add("aircraft_airline", row, source["id"], "aircraft")
	}
	for _, source := range e.rows["competence"] {
		row := source.project("code name description order_index")
		row["airline_id"] = e.target
		id := e.add("competence", row, source["id"], "competences")
		for _, indicator := range e.children("behavioural_indicator", "competence_id", source.number("id")) {
			if indicator["retired_at"] != nil {
				continue
			}
			row := indicator.project("code short_name name order_index")
			row["competence_id"] = id
			e.add("behavioural_indicator", row, nil, "behavioural_indicators")
		}
	}
	for _, source := range e.rows["flight_type"] {
		row := source.project("name normalized_name is_main")
		row["airline_id"] = e.target
		id := e.add("flight_type", row, nil, "flight_types")
		for _, threshold := range e.children("flight_type_competence_threshold", "flight_type_id", source.number("id")) {
			if _, ok := e.mappedIDs["competence"][threshold.number("competence_id")]; !ok {
				continue
			}
			e.add("flight_type_competence_threshold", record{
				"flight_type_id": id,
				"competence_id":  e.mapped("competence", threshold["competence_id"], "flight_type_competence_threshold.competence_id", true),
				"value":          threshold["value"],
			}, nil, "flight_type_competence_thresholds")
		}
	}
}

func (e *airlineClone) cloneCompetenceLinks(table, parentKey string, oldID, newID int64, count string) {
	for _, source := range e.children(table, parentKey, oldID) {
		if _, ok := e.mappedIDs["competence"][source.number("competence_id")]; !ok {
			continue
		}
		e.add(table, record{parentKey: newID, "competence_id": e.mapped("competence", source["competence_id"], table+".competence_id", true)}, nil, count)
	}
}
