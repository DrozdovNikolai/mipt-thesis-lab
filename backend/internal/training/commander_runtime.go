package training

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type commanderDurations struct{ PF, PM int64 }

func commanderParticipants(assessments []record, durations map[int64]commanderDurations, cm1, cm2 int64, actual bool) ([]record, error) {
	out := []record{}
	for _, a := range assessments {
		initial := strings.ToUpper(a.text("training_role"))
		final := initial
		if actual {
			switch a.number("id") {
			case cm1:
				final = "CM1"
			case cm2:
				final = "CM2"
			default:
				return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
			}
		}
		duration, ok := durations[a.number("id")]
		if !ok {
			return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
		}
		out = append(out, record{"assessment_id": a["id"], "pilot_id": a["pilot_id"], "first_name": a["pilot_first_name"], "last_name": a["pilot_last_name"], "photo_url": a["pilot_photo_url"], "initial_crew_slot": initial, "final_crew_slot": final, "pf_duration_ms": duration.PF, "pm_duration_ms": duration.PM})
	}
	return out, nil
}

func commanderRuntime(ctx context.Context, db runtimeDB, tid int64, assessments, exercises []record) (record, []record, map[int64][]record, error) {
	fail := func() (record, []record, map[int64][]record, error) {
		return nil, nil, nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	roles := map[string]int64{}
	for _, a := range assessments {
		roles[strings.ToLower(a.text("training_role"))] = a.number("id")
	}
	if len(roles) != 2 || roles["cm1"] == 0 || roles["cm2"] == 0 {
		return fail()
	}
	cm1, cm2 := roles["cm1"], roles["cm2"]
	durations := map[int64]commanderDurations{cm1: {}, cm2: {}}
	runs := map[int64][]record{}
	state, err := queryRecord(ctx, db, `SELECT to_jsonb(s) FROM training_session_crew_state s WHERE training_session_id=$1`, tid)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, nil, nil, err
	}
	base := record{"projection_source": "LEGACY_PLANNED", "sealed": false, "initial_event_id": nil, "current_event_id": nil, "initial_cm1_assessment_id": cm1, "initial_cm2_assessment_id": cm2, "final_cm1_assessment_id": cm1, "final_cm2_assessment_id": cm2, "swap_count": int64(0), "latest_swap": nil}
	if state == nil || state.number("capability_version") < 1 {
		events, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 ORDER BY server_revision`, tid)
		if err != nil {
			return nil, nil, nil, err
		}
		if state == nil {
			if len(events) != 0 {
				return fail()
			}
		} else {
			if state.number("capability_version") != 0 || state["live_swap_entitled"] == true || state.number("current_revision") != 0 || state.number("current_writer_sequence") != 0 || state.number("current_cm1_assessment_id") != cm1 || state.number("current_cm2_assessment_id") != cm2 || len(events) != 1 {
				return fail()
			}
			e := events[0]
			if e.text("event_kind") != "INITIAL" || e.number("server_revision") != 0 || e["previous_event_public_id"] != nil || e.text("public_id") != state.text("current_event_public_id") || e.number("cm1_assessment_id_after") != cm1 || e.number("cm2_assessment_id_after") != cm2 {
				return fail()
			}
		}
		for _, e := range exercises {
			duration := e.number("duration_minutes") * 60_000
			if duration <= 0 {
				continue
			}
			key := uuid.NewSHA1(uuid.NameSpaceURL, []byte(fmt.Sprintf("north55:legacy-run:%d:%d", tid, e.number("id"))))
			a, b := durations[cm1], durations[cm2]
			switch e.number("crew_member_number") {
			case 1:
				a.PF += duration
				b.PM += duration
			case 2:
				b.PF += duration
				a.PM += duration
			}
			durations[cm1], durations[cm2] = a, b
			id := e.number("runtime_exercise_id")
			runs[id] = append(runs[id], record{"exercise_session_key": key, "run_index": 1, "status": "COMPLETED", "active_duration_ms": duration})
		}
		participants, err := commanderParticipants(assessments, durations, cm1, cm2, false)
		return base, participants, runs, err
	}
	if state["sealed_at"] == nil {
		return fail()
	}
	var count, min, max, swaps int64
	err = db.QueryRow(ctx, `SELECT count(*),COALESCE(min(server_revision),-1),COALESCE(max(server_revision),-1),count(*) FILTER (WHERE event_kind='SWAP') FROM training_session_crew_assignment_event WHERE training_session_id=$1`, tid).Scan(&count, &min, &max, &swaps)
	if err != nil {
		return nil, nil, nil, err
	}
	revision := state.number("current_revision")
	if count != revision+1 || min != 0 || max != revision || swaps != revision {
		return fail()
	}
	initial, err := queryRecord(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 AND server_revision=0`, tid)
	if errors.Is(err, pgx.ErrNoRows) {
		return fail()
	}
	if err != nil {
		return nil, nil, nil, err
	}
	if initial.text("event_kind") != "INITIAL" || initial["previous_event_public_id"] != nil || initial.number("cm1_assessment_id_after") != cm1 || initial.number("cm2_assessment_id_after") != cm2 {
		return fail()
	}
	current, err := queryRecord(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 AND public_id=$2`, tid, state["current_event_public_id"])
	if errors.Is(err, pgx.ErrNoRows) {
		return fail()
	}
	if err != nil {
		return nil, nil, nil, err
	}
	final1, final2 := state.number("current_cm1_assessment_id"), state.number("current_cm2_assessment_id")
	if current.number("server_revision") != revision || current.number("cm1_assessment_id_after") != final1 || current.number("cm2_assessment_id_after") != final2 {
		return fail()
	}
	var invalid int64
	err = db.QueryRow(ctx, `SELECT count(*) FROM training_session_crew_assignment_event e LEFT JOIN training_session_crew_assignment_event p ON p.training_session_id=e.training_session_id AND p.public_id=e.previous_event_public_id WHERE e.training_session_id=$1 AND e.server_revision>0 AND (p.id IS NULL OR p.server_revision<>e.server_revision-1 OR p.cm1_assessment_id_after<>e.cm2_assessment_id_after OR p.cm2_assessment_id_after<>e.cm1_assessment_id_after)`, tid).Scan(&invalid)
	if err != nil {
		return nil, nil, nil, err
	}
	if invalid != 0 {
		return fail()
	}
	if revision > 0 {
		if current["previous_event_public_id"] == nil || current.text("event_kind") != "SWAP" {
			return fail()
		}
		previous, err := queryRecord(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e WHERE training_session_id=$1 AND public_id=$2`, tid, current["previous_event_public_id"])
		if errors.Is(err, pgx.ErrNoRows) {
			return fail()
		}
		if err != nil {
			return nil, nil, nil, err
		}
		if previous.number("server_revision")+1 != revision || current.number("cm1_assessment_id_after") != previous.number("cm2_assessment_id_after") || current.number("cm2_assessment_id_after") != previous.number("cm1_assessment_id_after") {
			return fail()
		}
		latest := current.project("server_revision event_scope training_session_exercise_id exercise_session_key exercise_offset_ms cm1_assessment_id_after cm2_assessment_id_after")
		latest["event_id"] = current["public_id"]
		latest["accepted_at"] = current["received_at"]
		latest["cm1_assessment_id_before"] = previous["cm1_assessment_id_after"]
		latest["cm2_assessment_id_before"] = previous["cm2_assessment_id_after"]
		base["latest_swap"] = latest
	}
	runRows, err := queryRecords(ctx, db, `SELECT to_jsonb(r)||jsonb_build_object('segment_duration',COALESCE((SELECT sum(s.to_offset_ms-s.from_offset_ms) FROM training_session_exercise_crew_segment s WHERE s.training_session_id=$1 AND s.exercise_session_key=r.exercise_session_key),0)) FROM training_session_exercise_run r WHERE r.training_session_id=$1 ORDER BY r.runtime_exercise_id,r.run_index`, tid)
	if err != nil {
		return nil, nil, nil, err
	}
	for _, r := range runRows {
		if r.text("status") != "COMPLETED" && r.text("status") != "ABANDONED" || r.number("segment_duration") != r.number("active_duration_ms") {
			return fail()
		}
		id := r.number("runtime_exercise_id")
		runs[id] = append(runs[id], r.project("exercise_session_key run_index status active_duration_ms"))
	}
	for _, duty := range []string{"pf", "pm"} {
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(r) FROM (SELECT `+duty+`_assessment_id AS assessment_id,sum(to_offset_ms-from_offset_ms) AS duration_ms FROM training_session_exercise_crew_segment WHERE training_session_id=$1 AND `+duty+`_assessment_id IS NOT NULL GROUP BY `+duty+`_assessment_id) r`, tid)
		if err != nil {
			return nil, nil, nil, err
		}
		for _, r := range rows {
			id := r.number("assessment_id")
			d, ok := durations[id]
			if !ok {
				return fail()
			}
			if duty == "pf" {
				d.PF = r.number("duration_ms")
			} else {
				d.PM = r.number("duration_ms")
			}
			durations[id] = d
		}
	}
	base["projection_source"] = "ACTUAL_TIMELINE"
	base["sealed"] = true
	base["initial_event_id"] = initial["public_id"]
	base["current_event_id"] = state["current_event_public_id"]
	base["final_cm1_assessment_id"] = final1
	base["final_cm2_assessment_id"] = final2
	base["swap_count"] = swaps
	participants, err := commanderParticipants(assessments, durations, final1, final2, true)
	return base, participants, runs, err
}
