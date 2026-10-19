package training

import (
	"context"
	"fmt"
	"sort"
	"strings"
)

func commanderFallback(values ...any) any {
	for _, v := range values {
		if v != nil && v != "" {
			return v
		}
	}
	return nil
}

func commanderAssessments(ctx context.Context, db runtimeDB, tid int64, assessments, exercises []record, sortKeys map[int64][3]int64) ([]record, error) {
	grades, err := queryRecords(ctx, db, `SELECT to_jsonb(f)||jsonb_build_object('grade_score_snapshot',f.grade_score_snapshot::text,'competence',to_jsonb(c)) FROM (SELECT DISTINCT ON (f.assessment_id,f.competence_id) f.* FROM final_report f JOIN crew_member_assessment a ON a.id=f.assessment_id WHERE a.training_session_id=$1 ORDER BY f.assessment_id,f.competence_id,COALESCE(f.updated_at,f.created_at) DESC,f.created_at DESC,f.id DESC) f LEFT JOIN competence c ON c.id=f.competence_id`, tid)
	if err != nil {
		return nil, err
	}
	remarks, err := queryRecords(ctx, db, `SELECT to_jsonb(m)||jsonb_build_object('competence',to_jsonb(c),'indicator',to_jsonb(b),'observed',to_jsonb(e)) FROM mistake_report m JOIN crew_member_assessment a ON a.id=m.assessment_id LEFT JOIN competence c ON c.id=m.competence_id LEFT JOIN behavioural_indicator b ON b.id=m.behavioural_indicator_id LEFT JOIN training_session_crew_assignment_event e ON e.id=m.assignment_event_id_at_observation WHERE a.training_session_id=$1 ORDER BY m.exercise_offset_sec,m.timestamp,m.id`, tid)
	if err != nil {
		return nil, err
	}
	gradeRows := map[int64][]record{}
	remarkRows := map[int64][]record{}
	planned := map[int64]int64{}
	for _, e := range exercises {
		planned[e.number("runtime_exercise_id")] = e.number("crew_member_number")
	}
	for _, g := range grades {
		gradeRows[g.number("assessment_id")] = append(gradeRows[g.number("assessment_id")], g)
	}
	for _, m := range remarks {
		remarkRows[m.number("assessment_id")] = append(remarkRows[m.number("assessment_id")], m)
	}
	out := []record{}
	for _, a := range assessments {
		id := a.number("id")
		item := a.project("id training_role pilot_id pilot_first_name pilot_last_name summary result signed_at")
		finals := []record{}
		for _, g := range gradeRows[id] {
			c := g.object("competence")
			order := g["competence_order_index_snapshot"]
			if order == nil {
				order = c.number("order_index")
			}
			finals = append(finals, record{"id": g["id"], "competence_id": g["competence_id"], "competence_code": commanderFallback(g["competence_code_snapshot"], c["code"], fmt.Sprint(g.number("competence_id"))), "competence_name": commanderFallback(g["competence_name_snapshot"], c["name"], fmt.Sprintf("Competence %d", g.number("competence_id"))), "order_index": order, "grade_code": commanderFallback(g["grade_code_snapshot"], g["grade"]), "grade_label": commanderFallback(g["grade_label_snapshot"], g["grade_code_snapshot"], g["grade"]), "grade_score_numeric": g["grade_score_snapshot"], "grade_color_hex": g["grade_color_hex_snapshot"]})
		}
		sort.SliceStable(finals, func(i, j int) bool {
			for _, key := range []string{"order_index", "competence_id", "id"} {
				x, y := finals[i].number(key), finals[j].number(key)
				if x != y {
					return x < y
				}
			}
			return false
		})
		item["final_reports"] = finals
		byExercise := map[int64][]record{}
		for _, m := range remarkRows[id] {
			exercise := m.number("exercise_id")
			if len(sortKeys) > 0 {
				if _, ok := sortKeys[exercise]; !ok {
					continue
				}
			}
			c, b, e := m.object("competence"), m.object("indicator"), m.object("observed")
			projection, slot := "LEGACY_STATIC", strings.ToUpper(a.text("training_role"))
			if m.text("timeline_source") == "TIMELINE" {
				projection = "TIMELINE"
				if e == nil {
					return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
				}
				switch id {
				case e.number("cm1_assessment_id_after"):
					slot = "CM1"
				case e.number("cm2_assessment_id_after"):
					slot = "CM2"
				default:
					return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
				}
			}
			duty := "NONE"
			if p := planned[exercise]; p == 1 || p == 2 {
				duty = "PM"
				if slot == fmt.Sprintf("CM%d", p) {
					duty = "PF"
				}
			}
			r := m.project("id client_report_id timeline_source exercise_id timestamp exercise_offset_sec exercise_offset_ms exercise_session_key competence_id behavioural_indicator_id is_positive hashtag comment")
			r["assignment_event_id_at_observation"] = e["public_id"]
			r["crew_slot_at_observation"] = slot
			r["duty_at_observation"] = duty
			r["role_projection_source"] = projection
			r["competence_code"] = commanderFallback(m["competence_code_snapshot"], c["code"])
			r["competence_name"] = commanderFallback(m["competence_name_snapshot"], c["name"])
			r["behavioural_indicator_code"] = commanderFallback(m["behavioural_indicator_code_snapshot"], b["code"])
			r["behavioural_indicator_name"] = commanderFallback(m["behavioural_indicator_name_snapshot"], b["name"], b["short_name"])
			byExercise[exercise] = append(byExercise[exercise], r)
		}
		ids := []int64{}
		for exercise := range byExercise {
			ids = append(ids, exercise)
		}
		key := func(id int64) [3]int64 {
			if k, ok := sortKeys[id]; ok {
				return k
			}
			return [3]int64{1_000_000_000, 1_000_000_000, id}
		}
		sort.Slice(ids, func(i, j int) bool {
			a, b := key(ids[i]), key(ids[j])
			for k := 0; k < 3; k++ {
				if a[k] != b[k] {
					return a[k] < b[k]
				}
			}
			return false
		})
		reports := []record{}
		for _, exercise := range ids {
			rows := byExercise[exercise]
			positive := 0
			for _, r := range rows {
				if r["is_positive"] == true {
					positive++
				}
			}
			reports = append(reports, record{"exercise_id": exercise, "remark_count": len(rows), "positive_remark_count": positive, "negative_remark_count": len(rows) - positive, "remarks": rows})
		}
		item["exercise_reports"] = reports
		item["ai_reviews"] = []record{}
		out = append(out, item)
	}
	return out, nil
}
