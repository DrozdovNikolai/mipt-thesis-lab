package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func (s *Service) assessmentUserProfile(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), platform.Field{Name: "name", Kind: "string", Max: 120, Nullable: true}, platform.Field{Name: "user_id", Alias: "userId", Kind: "integer", GreaterThanZero: true, Nullable: true})
	if err != nil {
		return err
	}
	name := assessmentUserWords(q.String("name"))
	if q["user_id"] == nil && name == "" {
		return platform.Error(400, "name or userId is required")
	}
	selected, err := assessmentUserSelection(r.Context(), s.Auth.DB, user.AirlineID, name, q["user_id"], 1)
	if err != nil {
		return err
	}
	if len(selected) == 0 {
		return platform.Error(404, "User not found")
	}
	found, err := s.Auth.LoadUser(r.Context(), uuid.MustParse(selected[0].text("public_id")))
	if err != nil {
		return err
	}
	latest, err := assessmentUserHistory(r.Context(), s.Auth.DB, found.InternalID)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, assessmentUserWire(record{"user": assessmentUserInfo(found, selected[0]["airline"]), "latest_assessment": latest}))
	return nil
}

func assessmentUserHistory(ctx context.Context, db runtimeDB, userID int64) (any, error) {
	assessment, err := queryRecord(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id WHERE a.user_id=$1 AND t.status='COMPLETED' ORDER BY coalesce(t.completed_at,t.updated_at,t.created_at) DESC,a.created_at DESC,a.id DESC LIMIT 1`, userID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	id := assessment.number("id")
	// The source returns all reports, in its database retrieval order. Do not
	// reuse Commander's latest-report filtering or frozen name projection here.
	grades, err := queryRecords(ctx, db, `SELECT to_jsonb(f)||jsonb_build_object('grade_score_snapshot',grade_score_snapshot::text,'grade_weight_snapshot',grade_weight_snapshot::text) FROM final_report f WHERE assessment_id=$1`, id)
	if err != nil {
		return nil, err
	}
	remarks, err := queryRecords(ctx, db, "SELECT to_jsonb(m) FROM mistake_report m WHERE assessment_id=$1", id)
	if err != nil {
		return nil, err
	}
	compIDs, indicatorIDs, eventIDs := []int64{}, []int64{}, []int64{}
	for _, grade := range grades {
		if grade["competence_id"] != nil {
			compIDs = append(compIDs, grade.number("competence_id"))
		}
	}
	for _, remark := range remarks {
		if remark["competence_id"] != nil {
			compIDs = append(compIDs, remark.number("competence_id"))
		}
		if remark["behavioural_indicator_id"] != nil {
			indicatorIDs = append(indicatorIDs, remark.number("behavioural_indicator_id"))
		}
		if remark["assignment_event_id_at_observation"] != nil {
			eventIDs = append(eventIDs, remark.number("assignment_event_id_at_observation"))
		}
	}
	load := func(table string, ids []int64) (map[int64]record, error) {
		out := map[int64]record{}
		if len(ids) == 0 {
			return out, nil
		}
		rows, err := queryRecords(ctx, db, "SELECT to_jsonb(v) FROM "+table+" v WHERE id=ANY($1::bigint[])", ids)
		for _, row := range rows {
			out[row.number("id")] = row
		}
		return out, err
	}
	comps, err := load("competence", compIDs)
	if err != nil {
		return nil, err
	}
	indicators, err := load("behavioural_indicator", indicatorIDs)
	if err != nil {
		return nil, err
	}
	events, err := load("training_session_crew_assignment_event", eventIDs)
	if err != nil {
		return nil, err
	}
	finals, mistakes := []record{}, []record{}
	for _, grade := range grades {
		code := pythonString(grade["competence_id"])
		if comp := comps[grade.number("competence_id")]; comp != nil {
			code = comp.text("code")
		}
		item := record{"id": grade["id"], "competence_code": code, "grade": grade["grade"], "grade_code": grade["grade"], "grade_label": grade["grade"], "grade_score_numeric": grade["grade_score_snapshot"], "grade_weight": grade["grade_weight_snapshot"], "grade_color_hex": grade["grade_color_hex_snapshot"]}
		for key, source := range map[string]string{"grade_code": "grade_code_snapshot", "grade_label": "grade_label_snapshot"} {
			if grade.text(source) != "" {
				item[key] = grade[source]
			}
		}
		for _, field := range []string{"grade_score_numeric", "grade_weight"} {
			if strings.EqualFold(item.text(field), "NaN") || strings.Contains(item.text(field), "Infinity") {
				return nil, fmt.Errorf("profile report requires finite decimal")
			}
		}
		finals = append(finals, item)
	}
	for _, remark := range remarks {
		item := remark.project("id client_report_id timeline_source exercise_id timestamp exercise_offset_sec exercise_offset_ms exercise_session_key is_positive hashtag comment")
		item["competence_code"] = comps[remark.number("competence_id")].text("code")
		if bi := indicators[remark.number("behavioural_indicator_id")]; bi != nil {
			item["indicator_name"] = bi["code"]
			if bi.text("short_name") != "" {
				item["indicator_name"] = bi["short_name"]
			}
		}
		item["assignment_event_id_at_observation"] = events[remark.number("assignment_event_id_at_observation")]["public_id"]
		item["color"] = "#ff453a"
		if jsonTruthy(remark["is_positive"]) {
			item["color"] = "#6ea1f2"
		}
		mistakes = append(mistakes, item)
	}
	return record{"id": assessment["id"], "summary": assessment["summary"], "final_reports": finals, "mistake_reports": mistakes, "ai_reviews": []string{}}, nil
}
