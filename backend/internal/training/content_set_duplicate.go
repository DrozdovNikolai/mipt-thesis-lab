package training

import (
	"net/http"
	"sort"

	"north55/backend/internal/platform"
)

func duplicateContentSetName(source, requested string) string {
	if name := pythonTrim(requested); name != "" {
		return name
	}
	base := pythonTrim(source)
	if base == "" {
		base = "Content set"
	}
	const suffix = " (copy)"
	if len([]rune(base))+len(suffix) <= 255 {
		return base + suffix
	}
	trimmed := pythonTrim(string([]rune(base)[:255-len(suffix)]))
	if trimmed == "" {
		return string([]rune(base)[:255])
	}
	return trimmed + suffix
}

func (s *Service) duplicateContentSet(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	model := platform.Schema{Fields: []platform.Field{{Name: "name", Kind: "string", Nullable: true, Max: 255}, libraryAircraftField()}}
	path, body, err := libraryInput(r, &model, "content_set_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	allowed, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	source, err := scopedContentSet(ctx, tx, path["content_set_id"], airline, allowed)
	if err != nil {
		return err
	}
	aircraft := source.number("aircraft_id")
	if body["aircraft_id"] != nil {
		ids, err := libraryAircraft(ctx, tx, user, body["aircraft_id"], true, false)
		if err != nil {
			return err
		}
		aircraft = ids[0]
	}
	data := source.project("airline_id valid_from valid_to")
	data["aircraft_id"], data["name"] = aircraft, duplicateContentSetName(source.text("name"), body.String("name"))
	data["created_by"], data["updated_by"] = user.InternalID, user.InternalID
	target, err := insertTrainingRow(ctx, tx, "scenario_content_set", data)
	if err != nil {
		return err
	}
	subcolumns, err := queryRecords(ctx, tx, `SELECT to_jsonb(c) FROM scenario_content_subcolumn c WHERE content_set_id=$1 ORDER BY order_index,id`, source["id"])
	if err != nil {
		return err
	}
	for _, column := range subcolumns {
		row := column.project("name order_index")
		row["content_set_id"] = target["id"]
		if _, err = insertTrainingRow(ctx, tx, "scenario_content_subcolumn", row); err != nil {
			return err
		}
	}
	folders, err := queryRecords(ctx, tx, `SELECT to_jsonb(f) FROM scenario_content_folder f WHERE content_set_id=$1 ORDER BY order_index,id`, source["id"])
	if err != nil {
		return err
	}
	children := map[int64][]record{}
	for _, folder := range folders {
		if folder["parent_id"] != nil {
			children[folder.number("parent_id")] = append(children[folder.number("parent_id")], folder)
		}
	}
	type entry struct {
		old    record
		parent any
	}
	stack := []entry{}
	// Only SQL NULL identifies a root: legacy parent 0 is not a root.
	for i := len(folders) - 1; i >= 0; i-- {
		if folders[i]["parent_id"] == nil {
			stack = append(stack, entry{old: folders[i]})
		}
	}
	folderIDs := map[int64]int64{}
	for len(stack) > 0 {
		item := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		row := item.old.project("name order_index")
		row["content_set_id"], row["parent_id"] = target["id"], item.parent
		created, err := insertTrainingRow(ctx, tx, "scenario_content_folder", row)
		if err != nil {
			return err
		}
		folderIDs[item.old.number("id")] = created.number("id")
		for i := len(children[item.old.number("id")]) - 1; i >= 0; i-- {
			stack = append(stack, entry{old: children[item.old.number("id")][i], parent: created["id"]})
		}
	}
	// Preserve raw relationship order for the final element-link insertion pass.
	requirements, err := queryRecords(ctx, tx, `SELECT to_jsonb(re) FROM scenario_content_requirement re WHERE content_set_id=$1`, source["id"])
	if err != nil {
		return err
	}
	ordered := append([]record{}, requirements...)
	sort.SliceStable(ordered, func(i, j int) bool {
		for _, field := range []string{"folder_id", "order_index", "id"} {
			if ordered[i].number(field) != ordered[j].number(field) {
				return ordered[i].number(field) < ordered[j].number(field)
			}
		}
		return false
	})
	requirementIDs := map[int64]int64{}
	for _, requirement := range ordered {
		folder, ok := folderIDs[requirement.number("folder_id")]
		if !ok {
			continue
		}
		row := requirement.project("topic_name order_index")
		row["content_set_id"], row["folder_id"] = target["id"], folder
		created, err := insertTrainingRow(ctx, tx, "scenario_content_requirement", row)
		if err != nil {
			return err
		}
		requirementIDs[requirement.number("id")] = created.number("id")
	}
	for _, requirement := range requirements {
		id, ok := requirementIDs[requirement.number("id")]
		if !ok {
			continue
		}
		links, err := queryRecords(ctx, tx, `SELECT to_jsonb(l) FROM scenario_content_requirement_element l WHERE requirement_id=$1 ORDER BY order_index,id`, requirement["id"])
		if err != nil {
			return err
		}
		for _, link := range links {
			row := link.project("element_id order_index")
			row["requirement_id"] = id
			if _, err = insertTrainingRow(ctx, tx, "scenario_content_requirement_element", row); err != nil {
				return err
			}
		}
	}
	labels, err := queryRecords(ctx, tx, `SELECT to_jsonb(l) FROM scenario_content_set_label l WHERE content_set_id=$1 ORDER BY order_index,id`, source["id"])
	if err != nil {
		return err
	}
	for _, label := range labels {
		row := label.project("label order_index")
		row["content_set_id"] = target["id"]
		if _, err = insertTrainingRow(ctx, tx, "scenario_content_set_label", row); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	value, err := contentSetDTO(ctx, s.Auth.DB, target)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, commanderWire(value))
	return nil
}
