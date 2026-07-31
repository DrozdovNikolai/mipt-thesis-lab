package training

import (
	"context"
	"fmt"
	"strings"
)

const takeoffFields = "airport_name time_of_day runway braking_action special_wx wind_dir wind_speed wind_gust visibility_value clouds_amount clouds_ceiling_ft rvr_h rvr_v temperature_c qnh_hpa fuel cg_percent"
const takeoffDetailFields = "thrust_setting flaps_setting v2_speed vr_speed v1_speed sid squawk_code frequency climb"

func numericSnapshotString(value any) (any, error) {
	text, details := libraryJSONOrder(nil).stringBefore("value")(value, nil)
	if len(details) > 0 {
		return nil, fmt.Errorf("invalid numeric snapshot string")
	}
	return text, nil
}
func revisionTakeoff(source record) (any, error) {
	if source == nil {
		return nil, nil
	}
	out := source.project(takeoffFields)
	for _, key := range strings.Fields(takeoffDetailFields) {
		out[key] = source.object("takeoff_details")[key]
	}
	var err error
	out["fuel"], err = numericSnapshotString(out["fuel"])
	return out, err
}
func revisionParam(source record) (any, error) {
	if source == nil {
		return nil, nil
	}
	out := source.project("intensity zfw_t guidance_doc guidance_plain_text")
	var err error
	out["zfw_t"], err = numericSnapshotString(out["zfw_t"])
	if err != nil {
		return nil, err
	}
	out["guidance_doc"], err = normalizeGuidance(out["guidance_doc"])
	if err != nil {
		return nil, err
	}
	for _, key := range []string{"original_tl", "destination_tl"} {
		out[key], err = revisionTakeoff(source.object(key))
		if err != nil {
			return nil, err
		}
	}
	return out, nil
}
func scenarioRevisionPayload(s sourceScenario) (map[string]any, error) {
	days := map[int64]int64{}
	for _, d := range s.Days {
		days[d.number("module_id")] = max(1, d.number("day_index"))
	}
	modules := []record{}
	previous := int64(1)
	for i, module := range s.Modules {
		m := module.Row.project("id client_uid scenario_id order_index duration_minutes content_subcolumn_id")
		day := max(1, days[module.Row.number("id")])
		if i == 0 {
			day = 1
		}
		day = max(day, previous)
		m["day_index"] = day
		m["day_start"] = i > 0 && day > previous
		previous = day
		exercises := []record{}
		for _, exercise := range module.Exercises {
			e := exercise.Row.project("id client_uid module_id kind order_index duration_minutes crew_member_number")
			if e["kind"] == nil || e["kind"] == "" {
				e["kind"] = "standard"
			}
			competenceIDs := []int64{}
			for _, c := range exercise.Competences {
				competenceIDs = append(competenceIDs, c.number("id"))
			}
			e["competence_ids"] = competenceIDs
			elements := []record{}
			for _, element := range exercise.Elements {
				elements = append(elements, element.project("element_id order_index details starting_height ending_height profile_type"))
			}
			e["elements"] = elements
			param, err := revisionParam(exercise.Param)
			if err != nil {
				return nil, err
			}
			e["params"] = param
			exercises = append(exercises, e)
		}
		m["exercises"] = exercises
		modules = append(modules, m)
	}
	return map[string]any{"modules": modules}, nil
}
func ensureScenarioRevision(ctx context.Context, db runtimeDB, s sourceScenario, userID int64) (id, number int64, err error) {
	payload, err := scenarioRevisionPayload(s)
	if err != nil {
		return 0, 0, err
	}
	row, err := createScenarioRevision(ctx, db, s.Row.number("id"), record{"created_by": userID, "kind": "AUTO"}, payload, true)
	if err != nil {
		return 0, 0, err
	}
	return row.number("id"), row.number("revision_number"), nil
}
