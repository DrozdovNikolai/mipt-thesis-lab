package training

import (
	"context"
	"fmt"
	"net/http"
	"sort"

	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/platform"
)

func (s *Service) readScenarioPublication(w http.ResponseWriter, r *http.Request, validate bool) error {
	privilege := "training:read"
	if validate {
		privilege = "training:write"
	}
	user, err := s.Auth.Authenticate(r, privilege)
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "scenario_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	scenario, err := scenarioGet(r.Context(), s.Auth.DB, path["scenario_id"], airline, aircraft, false, false)
	if err != nil {
		return err
	}
	var response any
	if validate {
		response, err = scenarioPublicationValidation(r.Context(), s.Auth.DB, scenario)
	} else {
		response, err = scenarioContentSubcolumns(r.Context(), s.Auth.DB, scenario.number("id"))
	}
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(response))
	return nil
}

func scenarioContentSubcolumns(ctx context.Context, db runtimeDB, scenarioID int64) ([]record, error) {
	sets, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM scenario_content_set c
JOIN scenario_content_set_label l ON l.content_set_id=c.id
JOIN scenario_content_set_label_scenario x ON x.label_id=l.id WHERE x.scenario_id=$1`, scenarioID)
	if err != nil {
		return nil, err
	}
	out, seen := []record{}, map[int64]bool{}
	for _, set := range sets {
		id := set.number("id")
		if seen[id] {
			continue
		}
		seen[id] = true
		aircraft, err := libraryFind(ctx, db, "aircraft_airline", set["aircraft_id"])
		if err != nil {
			return nil, err
		}
		subcolumns, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM scenario_content_subcolumn c WHERE content_set_id=$1 ORDER BY order_index,id`, id)
		if err != nil {
			return nil, err
		}
		item := set.project("id name aircraft_id")
		item["aircraft_code"], item["subcolumns"] = aircraft["code"], subcolumns
		out = append(out, item)
	}
	return out, nil
}

func publicationName(value, prefix string, id int64) string {
	if name := pythonTrim(value); name != "" {
		return name
	}
	return fmt.Sprintf("%s %d", prefix, id)
}

func scenarioPublicationValidation(ctx context.Context, db runtimeDB, scenario record) (record, error) {
	labels, err := queryRecords(ctx, db, `SELECT to_jsonb(l)||jsonb_build_object('content_set',to_jsonb(c))
FROM scenario_content_set_label l JOIN scenario_content_set_label_scenario x ON x.label_id=l.id
LEFT JOIN scenario_content_set c ON c.id=l.content_set_id WHERE x.scenario_id=$1`, scenario["id"])
	if err != nil {
		return nil, err
	}
	labelIDs, byLabel := []int64{}, map[int64]record{}
	for _, label := range labels {
		labelIDs = append(labelIDs, label.number("id"))
		byLabel[label.number("id")] = label
	}
	result := record{"ok": true, "missing": []record{}}
	if len(labelIDs) == 0 {
		return result, nil
	}
	cells, err := queryRecords(ctx, db, `SELECT to_jsonb(c)||jsonb_build_object('topic_name',q.topic_name,'subcolumn_name',s.name)
FROM scenario_content_cell c LEFT JOIN scenario_content_requirement q ON q.id=c.requirement_id
LEFT JOIN scenario_content_subcolumn s ON s.id=c.subcolumn_id WHERE c.set_label_id=ANY($1::bigint[]) AND c.value IS TRUE`, labelIDs)
	if err != nil {
		return nil, err
	}
	if len(cells) == 0 {
		return result, nil
	}
	requirementIDs := []int64{}
	for _, cell := range cells {
		requirementIDs = append(requirementIDs, cell.number("requirement_id"))
	}
	elements, err := queryRecords(ctx, db, `SELECT jsonb_build_object('requirement_id',r.requirement_id,'element_id',e.id,'name',e.name)
FROM scenario_content_requirement_element r JOIN element e ON e.id=r.element_id
WHERE r.requirement_id=ANY($1::bigint[]) AND e.airline_id=$2 AND e.aircraft_id=$3 ORDER BY e.id`, requirementIDs, scenario["airline_id"], scenario["aircraft_id"])
	if err != nil {
		return nil, err
	}
	byRequirement := map[int64][]record{}
	for _, e := range elements {
		id := e.number("requirement_id")
		byRequirement[id] = append(byRequirement[id], record{"element_id": e["element_id"], "name": publicationName(e.text("name"), "Element", e.number("element_id"))})
	}
	present, err := queryRecords(ctx, db, `SELECT jsonb_build_object('subcolumn_id',m.content_subcolumn_id,'element_id',x.element_id)
FROM module m JOIN exercise e ON e.module_id=m.id JOIN exercise_element x ON x.exercise_id=e.id
WHERE m.scenario_id=$1 AND m.content_subcolumn_id IS NOT NULL`, scenario["id"])
	if err != nil {
		return nil, err
	}
	presentIDs := map[[2]int64]bool{}
	for _, e := range present {
		presentIDs[[2]int64{e.number("subcolumn_id"), e.number("element_id")}] = true
	}
	groups, topics := map[[2]int64]record{}, map[[3]int64]bool{}
	missing := false
	for _, cell := range cells {
		labelID, subcolumnID, requirementID := cell.number("set_label_id"), cell.number("subcolumn_id"), cell.number("requirement_id")
		eligible := byRequirement[requirementID]
		fulfilled := false
		for _, e := range eligible {
			if presentIDs[[2]int64{subcolumnID, e.number("element_id")}] {
				fulfilled = true
				break
			}
		}
		if fulfilled {
			continue
		}
		missing = true
		set := byLabel[labelID].object("content_set")
		topicKey := [3]int64{labelID, subcolumnID, requirementID}
		if set == nil || topics[topicKey] {
			continue
		}
		topics[topicKey] = true
		key := [2]int64{labelID, subcolumnID}
		group := groups[key]
		if group == nil {
			group = record{"content_set_id": set["id"], "content_set_name": set["name"], "set_label_id": labelID, "subcolumn_id": subcolumnID, "subcolumn_name": publicationName(cell.text("subcolumn_name"), "Type", subcolumnID), "missing_topics": []record{}}
			groups[key] = group
		}
		if eligible == nil {
			eligible = []record{}
		}
		group["missing_topics"] = append(group["missing_topics"].([]record), record{"requirement_id": requirementID, "topic_name": publicationName(cell.text("topic_name"), "Topic", requirementID), "elements": eligible})
	}
	out, lower := []record{}, cases.Lower(language.Und)
	for _, group := range groups {
		items := group["missing_topics"].([]record)
		sort.SliceStable(items, func(i, j int) bool {
			a, b := lower.String(items[i].text("topic_name")), lower.String(items[j].text("topic_name"))
			if a != b {
				return a < b
			}
			return items[i].number("requirement_id") < items[j].number("requirement_id")
		})
		out = append(out, group)
	}
	sort.Slice(out, func(i, j int) bool {
		for _, field := range []string{"content_set_id", "subcolumn_id", "set_label_id"} {
			if a, b := out[i].number(field), out[j].number(field); a != b {
				return a < b
			}
		}
		return false
	})
	return record{"ok": !missing, "missing": out}, nil
}
