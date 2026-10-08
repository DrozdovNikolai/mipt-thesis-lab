package training

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/reportpdf"
	"north55/backend/internal/training/canonical"
)

func reportUUID(raw string) (uuid.UUID, error) {
	value, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	return value, nil
}

func (s *Service) reportTimelineDurations(ctx context.Context, training, assessment, state record) (reportpdf.Durations, error) {
	tid, aid := training.number("id"), assessment.number("id")
	runs, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM training_session_exercise_run r WHERE training_session_id=$1`, tid)
	if err != nil {
		return reportpdf.Durations{}, err
	}
	out := reportpdf.Durations{Source: "ACTUAL_TIMELINE"}
	count := func(pf, pm, duration int64) {
		if pf == aid {
			out.PFMs += duration
		}
		if pm == aid {
			out.PMMs += duration
		}
	}
	if state["sealed_at"] != nil {
		segments, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(g) FROM training_session_exercise_crew_segment g WHERE training_session_id=$1`, tid)
		if err != nil {
			return out, err
		}
		byRun := map[string][]record{}
		for _, segment := range segments {
			byRun[segment.text("exercise_session_key")] = append(byRun[segment.text("exercise_session_key")], segment)
		}
		for _, run := range runs {
			covered := int64(0)
			for _, segment := range byRun[run.text("exercise_session_key")] {
				duration := segment.number("to_offset_ms") - segment.number("from_offset_ms")
				covered += duration
				count(segment.number("pf_assessment_id"), segment.number("pm_assessment_id"), duration)
			}
			if covered != run.number("active_duration_ms") {
				return out, runtimeError("RUNTIME_CHAIN_CORRUPT")
			}
		}
		return out, nil
	}
	exercises, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(e) FROM training_session_exercise e WHERE training_session_id=$1`, tid)
	if err != nil {
		return out, err
	}
	byExercise := map[int64]record{}
	for _, exercise := range exercises {
		byExercise[exercise.number("id")] = exercise
	}
	events, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 ORDER BY server_revision`, tid)
	if err != nil {
		return out, err
	}
	byID := map[string]record{}
	byRun := map[string][]record{}
	for _, event := range events {
		byID[event.text("public_id")] = event
		if event["exercise_session_key"] != nil {
			byRun[event.text("exercise_session_key")] = append(byRun[event.text("exercise_session_key")], event)
		}
	}
	for _, run := range runs {
		exercise, found := byExercise[run.number("training_session_exercise_id")]
		initial, seen := byID[run.text("initial_assignment_event_public_id")]
		if !found || !seen {
			return out, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		initialID, err := reportUUID(initial.text("public_id"))
		if err != nil {
			return out, err
		}
		var pfSlot *int
		if number := exercise.number("crew_member_number"); number == 1 || number == 2 {
			value := int(number)
			pfSlot = &value
		}
		projections := []canonical.CrewEventProjection{}
		for _, event := range byRun[run.text("exercise_session_key")] {
			if event["exercise_offset_ms"] == nil {
				continue
			}
			id, err := reportUUID(event.text("public_id"))
			if err != nil {
				return out, err
			}
			projections = append(projections, canonical.CrewEventProjection{EventID: id, ServerRevision: event.number("server_revision"), ExerciseOffsetMS: event.number("exercise_offset_ms"), MappingAfter: canonical.CrewMapping{CM1AssessmentID: event.number("cm1_assessment_id_after"), CM2AssessmentID: event.number("cm2_assessment_id_after")}})
		}
		segments, err := canonical.BuildCrewSegments(run.number("active_duration_ms"), pfSlot, initialID, canonical.CrewMapping{CM1AssessmentID: initial.number("cm1_assessment_id_after"), CM2AssessmentID: initial.number("cm2_assessment_id_after")}, projections)
		if err != nil {
			return out, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		for _, segment := range segments {
			pf, pm := int64(0), int64(0)
			if segment.PFAssessmentID != nil {
				pf = *segment.PFAssessmentID
			}
			if segment.PMAssessmentID != nil {
				pm = *segment.PMAssessmentID
			}
			count(pf, pm, segment.ToOffsetMS-segment.FromOffsetMS)
		}
	}
	return out, nil
}

func (s *Service) reportLatestSwap(ctx context.Context, training record) (*reportpdf.RoleChange, error) {
	tid := training.number("id")
	state, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(s) FROM training_session_crew_state s WHERE training_session_id=$1`, tid)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	if state.number("capability_version") < 1 {
		return nil, nil
	}
	events, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 ORDER BY server_revision`, tid)
	if err != nil {
		return nil, err
	}
	if len(events) != int(state.number("current_revision"))+1 || len(events) == 0 || events[0].number("server_revision") != 0 || events[0].text("event_kind") != "INITIAL" || events[0]["previous_event_public_id"] != nil {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	for i, event := range events {
		if event.number("server_revision") != int64(i) || i > 0 && (event.text("event_kind") != "SWAP" || event.text("previous_event_public_id") != events[i-1].text("public_id")) {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
	}
	current := events[len(events)-1]
	if current.text("public_id") != state.text("current_event_public_id") || current.number("cm1_assessment_id_after") != state.number("current_cm1_assessment_id") || current.number("cm2_assessment_id_after") != state.number("current_cm2_assessment_id") {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	if len(events) < 2 {
		return nil, nil
	}
	rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM (SELECT a.id, a.training_role, u.login,u.email,i.first_name,i.last_name FROM crew_member_assessment a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN user_info i ON i.id=u.id WHERE a.training_session_id=$1) r`, tid)
	if err != nil {
		return nil, err
	}
	labels := map[int64]string{}
	for _, row := range rows {
		name := strings.TrimSpace(strings.Join([]string{pythonTrim(row.text("first_name")), pythonTrim(row.text("last_name"))}, " "))
		labels[row.number("id")] = reportText(name, row.text("login"), row.text("email"), fmt.Sprintf("Assessment %d", row.number("id")))
	}
	mapping := func(event record) (string, error) {
		firstID, secondID := event.number("cm1_assessment_id_after"), event.number("cm2_assessment_id_after")
		first, a := labels[firstID]
		second, b := labels[secondID]
		if !a || !b || firstID == secondID {
			return "", runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		return first + " CM1 / " + second + " CM2", nil
	}
	previous := events[len(events)-2]
	before, err := mapping(previous)
	if err != nil {
		return nil, err
	}
	after, err := mapping(current)
	if err != nil {
		return nil, err
	}
	if current.number("cm1_assessment_id_after") != previous.number("cm2_assessment_id_after") || current.number("cm2_assessment_id_after") != previous.number("cm1_assessment_id_after") {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	result := &reportpdf.RoleChange{Revision: current.number("server_revision"), Before: before, After: after, ExerciseLabel: "Between exercises"}
	if value := reportTime(current["received_at"]); value != nil {
		result.AcceptedAt = *value
	}
	if current.text("event_scope") == "EXERCISE_RUN" {
		exercise, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(e) FROM training_session_exercise e WHERE id=$1`, current.number("training_session_exercise_id"))
		if err != nil {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		run, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM training_session_exercise_run r WHERE exercise_session_key=$1`, current.text("exercise_session_key"))
		if err != nil || current["exercise_offset_ms"] == nil {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		result.ExerciseLabel = reportText(exercise.text("display_label"), exercise.text("step_label"), exercise.text("name"), fmt.Sprintf("Exercise %d", exercise.number("runtime_exercise_id")))
		attempt, offset := run.number("run_index"), current.number("exercise_offset_ms")
		result.Attempt, result.OffsetMs = &attempt, &offset
	} else if current.text("event_scope") != "SESSION" {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	return result, nil
}
