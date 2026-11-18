package training

import (
	"context"
	"net/http"
	"sort"
	"time"

	"north55/backend/internal/platform"
)

const commanderRoleFields = "initial_crew_slot final_crew_slot swap_count pf_duration_ms pm_duration_ms role_projection_source"
const commanderGradeFields = "competence_id competence_code competence_name order_index grade_code grade_label grade_score_numeric grade_color_hex"

// Summary preserves the source's aggregate role projection. Unlike full detail,
// legacy summaries report zero observed PF/PM time and do not invent planned time.
func commanderPilotRoles(ctx context.Context, db runtimeDB, trainings []record) (map[int64]record, error) {
	out := map[int64]record{}
	byID := map[int64]record{}
	ids := []int64{}
	for _, row := range trainings {
		if row["assessment_id"] != nil && row["training_role"] != nil {
			id := row.number("training_session_id")
			byID[id] = row
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return out, nil
	}
	data, err := queryRecords(ctx, db, `SELECT jsonb_build_object('training_session_id',t.id,
 'state',(SELECT to_jsonb(s) FROM training_session_crew_state s WHERE s.training_session_id=t.id),
 'swap_count',(SELECT count(*) FROM training_session_crew_assignment_event e WHERE e.training_session_id=t.id AND e.event_kind='SWAP'),
 'segments',COALESCE((SELECT jsonb_agg(to_jsonb(s)) FROM training_session_exercise_crew_segment s WHERE s.training_session_id=t.id),'[]'::jsonb))
 FROM training_session t WHERE t.id=ANY($1::bigint[])`, ids)
	if err != nil {
		return nil, err
	}
	for _, row := range data {
		id := row.number("training_session_id")
		assessment := byID[id]
		initial := assessmentUpper(assessment.text("training_role"))
		if initial != "CM1" && initial != "CM2" {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		state := row.object("state")
		actual := state != nil && state["sealed_at"] != nil && state.number("capability_version") >= 1
		if state != nil && state.number("capability_version") >= 1 && state["sealed_at"] == nil || row.number("swap_count") > 0 && !actual {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		final, source := initial, "LEGACY_PLANNED"
		pf, pm := int64(0), int64(0)
		if actual {
			if state.number("current_cm1_assessment_id") == assessment.number("assessment_id") {
				final = "CM1"
			} else if state.number("current_cm2_assessment_id") == assessment.number("assessment_id") {
				final = "CM2"
			} else {
				return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
			}
			source = "ACTUAL_TIMELINE"
			for _, raw := range row["segments"].([]any) {
				segment := record(raw.(map[string]any))
				duration := max(int64(0), segment.number("to_offset_ms")-segment.number("from_offset_ms"))
				if segment.number("pf_assessment_id") == assessment.number("assessment_id") {
					pf += duration
				}
				if segment.number("pm_assessment_id") == assessment.number("assessment_id") {
					pm += duration
				}
			}
		}
		out[id] = record{"initial_crew_slot": initial, "final_crew_slot": final, "swap_count": row["swap_count"], "pf_duration_ms": pf, "pm_duration_ms": pm, "role_projection_source": source}
	}
	return out, nil
}

func commanderPositionAverages(ctx context.Context, db runtimeDB, airline int64, position *int64) ([]record, error) {
	if position == nil || *position == 0 {
		return []record{}, nil
	}
	rows, err := queryRecords(ctx, db, `SELECT jsonb_build_object('id',u.id) FROM users u JOIN user_info i ON i.id=u.id WHERE u.airline_id=$1 AND i.position_id=$2`, airline, *position)
	if err != nil {
		return nil, err
	}
	ids := []int64{}
	for _, row := range rows {
		ids = append(ids, row.number("id"))
	}
	if len(ids) == 0 {
		return []record{}, nil
	}
	return queryRecords(ctx, db, commanderLatestPilotCTE(true)+`SELECT to_jsonb(r) FROM (
 SELECT c.id AS competence_id,c.code AS competence_code,c.name AS competence_name,c.order_index,
 avg(f.score)::numeric(10,4)::text AS average_score_numeric FROM latest_reports f JOIN competence c ON c.id=f.competence_id
 WHERE f.score IS NOT NULL GROUP BY c.id,c.code,c.name,c.order_index ORDER BY c.order_index,c.id) r`, airline, ids, nil)
}

func (s *Service) commanderPilotSummary(w http.ResponseWriter, r *http.Request) error {
	airline, pilot, err := s.commanderReadPilot(r)
	if err != nil {
		return err
	}
	ctx := r.Context()
	ratings, err := commanderPilotRatings(ctx, s.Auth.DB, airline, []int64{pilot.InternalID})
	if err != nil {
		return err
	}
	rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r)||jsonb_build_object('assessment_id',p.id,'training_role',p.training_role) FROM (`+commanderSessionSelect+`
 WHERE g.airline_id=$1 AND t.status='COMPLETED' AND t.completed_at IS NOT NULL) r
 JOIN crew_member_assessment p ON p.training_session_id=r.training_session_id AND p.user_id=$2
 ORDER BY r.completed_at DESC,r.training_session_id DESC,p.id DESC`, airline, pilot.InternalID)
	if err != nil {
		return err
	}
	roles, err := commanderPilotRoles(ctx, s.Auth.DB, rows)
	if err != nil {
		return err
	}
	grouped := []record{}
	seen := map[commanderGroup]bool{}
	seenSessions := map[int64]bool{}
	for _, row := range rows {
		if key, ok := commanderGroupKey(row); ok {
			if seen[key] {
				continue
			}
			seen[key] = true
		} else {
			id := row.number("training_session_id")
			if seenSessions[id] {
				continue
			}
			seenSessions[id] = true
		}
		grouped = append(grouped, row)
	}
	sessions, err := commanderListItems(ctx, s.Auth.DB, airline, grouped, true)
	if err != nil {
		return err
	}
	roleFor := func(id int64) record {
		if value := roles[id]; value != nil {
			return value
		}
		return record{"initial_crew_slot": nil, "final_crew_slot": nil, "swap_count": 0, "pf_duration_ms": 0, "pm_duration_ms": 0, "role_projection_source": "LEGACY_PLANNED"}
	}
	for i, item := range sessions {
		item["training_role"] = grouped[i]["training_role"]
		for key, value := range roleFor(grouped[i].number("training_session_id")) {
			item[key] = value
		}
	}
	averages, err := commanderPositionAverages(ctx, s.Auth.DB, airline, pilot.PositionID)
	if err != nil {
		return err
	}
	result := record{"pilot": commanderProfile(pilot, ratings[pilot.InternalID]), "latest_completed_training": nil, "position_average_grades": averages, "competence_histories": []record{}, "completed_training_sessions": sessions}
	if len(rows) > 0 {
		contexts := map[int64]record{}
		ids := []int64{}
		for _, row := range rows {
			id := row.number("assessment_id")
			contexts[id] = record{"training_session_id": row["training_session_id"], "training_session_title": commanderTitle(row, true), "completed_at": row["completed_at"], "training_role": row["training_role"]}
			for key, value := range roleFor(row.number("training_session_id")) {
				contexts[id][key] = value
			}
			ids = append(ids, id)
		}
		reports, err := queryRecords(ctx, s.Auth.DB, `WITH ranked AS (
 SELECT f.assessment_id,f.competence_id,c.code AS competence_code,c.name AS competence_name,c.order_index,
 coalesce(f.grade_code_snapshot,f.grade) AS grade_code,coalesce(f.grade_label_snapshot,f.grade_code_snapshot,f.grade) AS grade_label,
 f.grade_score_snapshot::text AS grade_score_numeric,f.grade_color_hex_snapshot AS grade_color_hex,
 row_number() OVER(PARTITION BY f.assessment_id,f.competence_id ORDER BY f.updated_at DESC,f.created_at DESC,f.id DESC) AS rank
 FROM final_report f JOIN competence c ON c.id=f.competence_id WHERE f.assessment_id=ANY($2::bigint[]) AND c.airline_id=$1)
 SELECT to_jsonb(r) FROM ranked r WHERE rank=1 ORDER BY order_index,competence_id,assessment_id DESC`, airline, ids)
		if err != nil {
			return err
		}
		latestID := rows[0].number("assessment_id")
		latest := contexts[latestID].project("training_session_id completed_at training_role " + commanderRoleFields)
		latest["title"] = contexts[latestID]["training_session_title"]
		grades := []record{}
		histories := map[int64]record{}
		ordered := []record{}
		for _, report := range reports {
			aid, cid := report.number("assessment_id"), report.number("competence_id")
			if aid == latestID {
				grades = append(grades, report.project(commanderGradeFields))
			}
			if histories[cid] == nil {
				histories[cid] = report.project("competence_id competence_code competence_name order_index")
				histories[cid]["history"] = []record{}
				ordered = append(ordered, histories[cid])
			}
			entry := contexts[aid].project("training_session_id training_session_title completed_at")
			for key, value := range report.project("grade_code grade_label grade_score_numeric grade_color_hex") {
				entry[key] = value
			}
			histories[cid]["history"] = append(histories[cid]["history"].([]record), entry)
		}
		for _, history := range ordered {
			entries := history["history"].([]record)
			sort.SliceStable(entries, func(i, j int) bool {
				a, _ := time.Parse(time.RFC3339Nano, entries[i].text("completed_at"))
				b, _ := time.Parse(time.RFC3339Nano, entries[j].text("completed_at"))
				if !a.Equal(b) {
					return a.After(b)
				}
				return entries[i].number("training_session_id") > entries[j].number("training_session_id")
			})
		}
		latest["grades"] = grades
		result["latest_completed_training"], result["competence_histories"] = latest, ordered
	}
	platform.WriteJSON(w, 200, commanderWire(result))
	return nil
}
