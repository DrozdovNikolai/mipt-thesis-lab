package training

func (e *airlineClone) cloneContent() {
	for _, source := range e.rows["scenario_content_set"] {
		row := source.project("name valid_from valid_to")
		row["airline_id"], row["created_by"], row["updated_by"] = e.target, e.actor, e.actor
		row["aircraft_id"] = e.mapped("aircraft_airline", source["aircraft_id"], "scenario_content_set.aircraft_id", true)
		id := e.add("scenario_content_set", row, source["id"], "content_sets")
		for _, label := range e.children("scenario_content_set_label", "content_set_id", source.number("id")) {
			row := label.project("order_index label")
			row["content_set_id"] = id
			e.add("scenario_content_set_label", row, label["id"], "content_labels")
		}
		for _, sub := range e.children("scenario_content_subcolumn", "content_set_id", source.number("id")) {
			row := sub.project("name order_index")
			row["content_set_id"] = id
			e.add("scenario_content_subcolumn", row, sub["id"], "content_subcolumns")
		}
		e.cloneFolders("scenario_content_folder", e.children("scenario_content_folder", "content_set_id", source.number("id")), record{"content_set_id": id}, "content_folders")
		for _, requirement := range e.children("scenario_content_requirement", "content_set_id", source.number("id")) {
			row := requirement.project("topic_name order_index")
			row["content_set_id"] = id
			row["folder_id"] = e.mapped("scenario_content_folder", requirement["folder_id"], "scenario_content_requirement.folder_id", true)
			reqID := e.add("scenario_content_requirement", row, requirement["id"], "content_requirements")
			for _, element := range e.children("scenario_content_requirement_element", "requirement_id", requirement.number("id")) {
				e.add("scenario_content_requirement_element", record{"requirement_id": reqID, "order_index": element["order_index"], "element_id": e.mapped("element", element["element_id"], "scenario_content_requirement_element.element_id", true)}, nil, "content_requirement_elements")
			}
		}
		for _, cell := range e.children("scenario_content_cell", "content_set_id", source.number("id")) {
			e.add("scenario_content_cell", record{
				"content_set_id": id,
				"requirement_id": e.mapped("scenario_content_requirement", cell["requirement_id"], "scenario_content_cell.requirement_id", true),
				"set_label_id":   e.mapped("scenario_content_set_label", cell["set_label_id"], "scenario_content_cell.set_label_id", true),
				"subcolumn_id":   e.mapped("scenario_content_subcolumn", cell["subcolumn_id"], "scenario_content_cell.subcolumn_id", true),
				"value":          cell["value"] == true,
			}, nil, "content_cells")
		}
	}
}
