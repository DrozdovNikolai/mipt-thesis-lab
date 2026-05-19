package training

// Clone trees in depth-first sibling order. An unreachable library
// folder is detected by the later item pass, even when the folder is empty.
func (e *airlineClone) cloneFolders(table string, source []record, base record, count string) {
	type parentKey struct {
		id      int64
		present bool
	}
	children := map[parentKey][]record{}
	for _, row := range source {
		key := parentKey{row.number("parent_id"), row["parent_id"] != nil}
		children[key] = append(children[key], row)
	}
	for _, rows := range children {
		e.sortRows(rows, "order_index", "id")
	}
	type entry struct {
		row    record
		parent any
	}
	stack := []entry{}
	push := func(rows []record, parent any) {
		for i := len(rows) - 1; i >= 0; i-- {
			stack = append(stack, entry{rows[i], parent})
		}
	}
	push(children[parentKey{}], nil)
	for len(stack) > 0 && e.err == nil {
		item := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		row := item.row.project("name order_index")
		for key, value := range base {
			row[key] = value
		}
		row["parent_id"] = item.parent
		if table != "scenario_content_folder" {
			row["color_hex"] = item.row["color_hex"]
			row["aircraft_id"] = e.mapped("aircraft_airline", item.row["aircraft_id"], table+".aircraft_id", true)
		}
		if table == "block_folder" {
			kind := item.row.text("library_kind")
			if kind != "exercise" && kind != "competence" {
				kind = "exercise"
			}
			row["library_kind"] = kind
		}
		id := e.add(table, row, item.row["id"], count)
		push(children[parentKey{item.row.number("id"), true}], id)
	}
}

func (e *airlineClone) cloneFolderItems(folderTable, itemTable, objectTable, objectKey, count string) {
	for _, folder := range e.rows[folderTable] {
		folderID := e.mapped(folderTable, folder["id"], itemTable+".folder_id", true)
		for _, source := range e.children(itemTable, "folder_id", folder.number("id")) {
			e.add(itemTable, record{"folder_id": folderID, "order_index": source["order_index"], objectKey: e.mapped(objectTable, source[objectKey], itemTable+"."+objectKey, true)}, nil, count)
		}
	}
}

func (e *airlineClone) cloneElementLinks(table, parentKey string, oldID, newID int64, count string) {
	for _, source := range e.children(table, parentKey, oldID) {
		row := source.project("order_index details starting_height ending_height profile_type")
		row[parentKey] = newID
		row["element_id"] = e.mapped("element", source["element_id"], table+".element_id", true)
		e.add(table, row, nil, count)
	}
}

func (e *airlineClone) cloneLibrary() {
	for _, source := range e.rows["element"] {
		row := source.project("default_duration_minutes name severity")
		row["airline_id"] = e.target
		row["aircraft_id"] = e.mapped("aircraft_airline", source["aircraft_id"], "element.aircraft_id", true)
		e.add("element", row, source["id"], "elements")
	}
	e.cloneFolders("element_folder", e.rows["element_folder"], record{"airline_id": e.target}, "element_folders")
	e.cloneFolderItems("element_folder", "element_folder_item", "element", "element_id", "element_folder_items")
	for _, source := range e.rows["element_block"] {
		param := e.lookup("element_block_param", source["element_block_param_id"])
		row := param.project("duration_minutes crew_member_number intensity zfw_t guidance_doc guidance_plain_text")
		row["original_tl_id"] = e.takeoff(param["original_tl_id"])
		row["destination_tl_id"] = e.takeoff(param["destination_tl_id"])
		paramID := e.add("element_block_param", row, nil, "")
		id := e.add("element_block", record{"airline_id": e.target, "element_block_param_id": paramID}, source["id"], "element_blocks")
		e.cloneElementLinks("element_block_element", "block_id", source.number("id"), id, "element_block_elements")
		e.cloneCompetenceLinks("element_block_competence", "block_id", source.number("id"), id, "element_block_competences")
	}
	e.cloneFolders("block_folder", e.rows["block_folder"], record{"airline_id": e.target}, "block_folders")
	e.cloneFolderItems("block_folder", "block_folder_item", "element_block", "block_id", "block_folder_items")
}
