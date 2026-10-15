package training

import (
	"context"
	"fmt"
)

func commanderModules(ctx context.Context, db runtimeDB, tid int64) ([]record, []record, map[int64][3]int64, error) {
	modules, err := queryRecords(ctx, db, `SELECT to_jsonb(m) FROM training_session_module m WHERE training_session_id=$1 ORDER BY order_index,runtime_module_id`, tid)
	if err != nil {
		return nil, nil, nil, err
	}
	exercises, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise e WHERE training_session_id=$1 ORDER BY order_index,runtime_exercise_id`, tid)
	if err != nil {
		return nil, nil, nil, err
	}
	elements, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise_element e JOIN training_session_exercise x ON x.id=e.training_session_exercise_id WHERE x.training_session_id=$1 ORDER BY e.order_index,COALESCE(e.content_id,0),e.id`, tid)
	if err != nil {
		return nil, nil, nil, err
	}
	competences, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM training_session_exercise_competence c JOIN training_session_exercise x ON x.id=c.training_session_exercise_id WHERE x.training_session_id=$1 ORDER BY c.order_index_snapshot,lower(c.code_snapshot),c.id`, tid)
	if err != nil {
		return nil, nil, nil, err
	}
	byModule := map[int64][]record{}
	byElements := map[int64][]record{}
	byCompetences := map[int64][]record{}
	for _, e := range exercises {
		byModule[e.number("training_session_module_id")] = append(byModule[e.number("training_session_module_id")], e)
	}
	for _, e := range elements {
		byElements[e.number("training_session_exercise_id")] = append(byElements[e.number("training_session_exercise_id")], e)
	}
	for _, e := range competences {
		byCompetences[e.number("training_session_exercise_id")] = append(byCompetences[e.number("training_session_exercise_id")], e)
	}
	out := []record{}
	sortKeys := map[int64][3]int64{}
	number := int64(0)
	for position, m := range modules {
		item := m.project("client_uid order_index duration_minutes")
		item["id"] = m["runtime_module_id"]
		item["content_subcolumn_id"] = m["content_subcolumn_id_snapshot"]
		item["content_subcolumn_name"] = m["content_subcolumn_name_snapshot"]
		list := []record{}
		for _, e := range byModule[m.number("id")] {
			id := e.number("runtime_exercise_id")
			sortKeys[id] = [3]int64{int64(position), e.number("order_index"), id}
			x := e.project("client_uid order_index duration_minutes crew_member_number resolved_for_assessment_id")
			x["id"] = id
			x["module_id"] = m["runtime_module_id"]
			kind := e.text("kind")
			if kind == "" {
				kind = e.text("source_kind_snapshot")
			}
			if kind == "" {
				kind = "standard"
			}
			x["kind"] = kind
			label := e.text("display_label")
			if label == "" {
				label = map[string]string{"preparation": "Preparation", "coffee_break": "Coffee break", "individual": "Individual", "standard": "Exercise"}[kind]
			}
			if label == "" {
				label = "Exercise"
			}
			x["exercise_number"] = nil
			if kind != "preparation" && kind != "coffee_break" {
				number++
				x["exercise_number"] = number
				label = fmt.Sprintf("Exercise %d", number)
			}
			x["display_label"] = label
			els := []record{}
			for _, el := range byElements[e.number("id")] {
				key := el.number("content_id")
				if key == 0 {
					key = el.number("id")
				}
				source := el["source_element_id"]
				if source == nil {
					source = -el.number("id")
				}
				name := el.text("element_name_snapshot")
				if name == "" {
					name = fmt.Sprintf("Element %d", el.number("id"))
				}
				els = append(els, record{"id": key, "element_id": source, "element_name": name, "order_index": el.number("order_index"), "details": el["details"]})
			}
			x["elements"] = els
			cs := []record{}
			for _, c := range byCompetences[e.number("id")] {
				id := c["source_competence_id"]
				if id == nil {
					id = -c.number("id")
				}
				cs = append(cs, record{"id": id, "code": c["code_snapshot"], "name": c["name_snapshot"], "order_index": c.number("order_index_snapshot")})
			}
			x["competences"] = cs
			list = append(list, x)
		}
		item["exercises"] = list
		out = append(out, item)
	}
	return out, exercises, sortKeys, nil
}
