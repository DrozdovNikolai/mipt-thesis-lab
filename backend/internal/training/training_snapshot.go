package training

import (
	"context"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"strings"
)

const weatherFields = "original destination daytime special runway braking_action wind visibility clouds temp qnh"
const aircraftFieldsList = "zfw gw cg fuel flaps thrust v1 vr v2"
const atcFields = "sid climb frequency transponder"
const mediaFields = "storage_key storage_path original_filename display_name content_type size_bytes sha256 order_index"

func emptyToNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func formatSigned(raw string) string {
	raw = pythonTrim(raw)
	if raw == "" {
		return ""
	}
	n, ok := performanceInteger(raw)
	if !ok {
		return raw
	}
	return fmt.Sprintf("%+d", n)
}
func formatWind(direction, speed, gust string) string {
	direction, speed, gust = pythonTrim(direction), pythonTrim(speed), pythonTrim(gust)
	if direction == "" || speed == "" {
		return ""
	}
	base := direction + "/" + speed
	d, goodDirection := performanceInteger(direction)
	s, goodSpeed := performanceInteger(speed)
	if goodDirection && goodSpeed {
		base = fmt.Sprintf("%03d/%02d", d, s)
	}
	if gust != "" {
		if g, ok := performanceInteger(gust); ok {
			base += fmt.Sprintf("G%02d", g)
		} else {
			base += "G" + gust
		}
	}
	return base
}
func formatClouds(amount string, ceiling any) string {
	if amount == "" {
		return ""
	}
	if ceiling == nil {
		return amount
	}
	raw := pythonTrim(fmt.Sprint(ceiling))
	amount = pythonTrim(amount)
	if raw == "" {
		return amount
	}
	n, ok := performanceInteger(raw)
	if !ok {
		return pythonTrim(amount + " " + raw)
	}
	if (amount == "FEW" || amount == "SCT" || amount == "BKN" || amount == "OVC") && n.Cmp(big.NewInt(1000)) >= 0 && new(big.Int).Mod(n, big.NewInt(100)).Sign() == 0 {
		return fmt.Sprintf("%s%03d", amount, new(big.Int).Quo(n, big.NewInt(100)))
	}
	return pythonTrim(fmt.Sprintf("%s %d", amount, n))
}
func performanceColumns(param record) (record, error) {
	out := record{}
	if param == nil {
		return out, nil
	}
	original, destination := param.object("original_tl"), param.object("destination_tl")
	for _, phase := range []string{"departure", "arrival"} {
		tl := original
		if phase == "arrival" {
			tl = destination
		}
		if tl == nil {
			continue
		}
		weather := record{"original": original.text("airport_name"), "destination": destination.text("airport_name"), "daytime": tl.text("time_of_day"), "special": tl.text("special_wx"), "runway": tl.text("runway"), "braking_action": tl.text("braking_action"), "wind": formatWind(tl.text("wind_dir"), tl.text("wind_speed"), tl.text("wind_gust")), "visibility": tl.text("visibility_value"), "clouds": formatClouds(tl.text("clouds_amount"), tl["clouds_ceiling_ft"]), "temp": formatSigned(tl.text("temperature_c")), "qnh": tl.text("qnh_hpa")}
		weight, err := formatGrossWeight(param.text("zfw_t"), tl.text("fuel"))
		if err != nil {
			return nil, err
		}
		aircraft := record{"zfw": param.text("zfw_t"), "gw": weight, "cg": tl.text("cg_percent"), "fuel": tl.text("fuel")}
		if phase == "departure" {
			details := tl.object("takeoff_details")
			for to, from := range map[string]string{"flaps": "flaps_setting", "thrust": "thrust_setting", "v1": "v1_speed", "vr": "vr_speed", "v2": "v2_speed"} {
				aircraft[to] = details.text(from)
			}
			for to, from := range map[string]string{"sid": "sid", "climb": "climb", "frequency": "frequency", "transponder": "squawk_code"} {
				out["departure_atc_"+to] = emptyToNil(details.text(from))
			}
		}
		for key, value := range weather {
			out[phase+"_weather_"+key] = emptyToNil(value.(string))
		}
		for key, value := range aircraft {
			out[phase+"_aircraft_"+key] = emptyToNil(value.(string))
		}
	}
	return out, nil
}
func loadElementColors(ctx context.Context, db runtimeDB, ids []int64) (map[int64]string, error) {
	colors := map[int64]string{}
	if len(ids) == 0 {
		return colors, nil
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(f)||jsonb_build_object('element_id',i.element_id) FROM element_folder_item i JOIN element_folder f ON f.id=i.folder_id WHERE i.element_id=ANY($1) ORDER BY i.id`, ids)
	if err != nil {
		return nil, err
	}
	folderByElement := map[int64]int64{}
	folders := map[int64]record{}
	for _, row := range rows {
		id := row.number("id")
		element := row.number("element_id")
		if _, ok := folderByElement[element]; !ok {
			folderByElement[element] = id
		}
		folders[id] = row
	}
	pending := []int64{}
	for _, f := range folders {
		if f["parent_id"] != nil {
			if _, ok := folders[f.number("parent_id")]; !ok {
				pending = append(pending, f.number("parent_id"))
			}
		}
	}
	for len(pending) > 0 {
		rows, err = queryRecords(ctx, db, `SELECT to_jsonb(f) FROM element_folder f WHERE id=ANY($1)`, pending)
		if err != nil {
			return nil, err
		}
		pending = nil
		for _, f := range rows {
			if _, ok := folders[f.number("id")]; ok {
				continue
			}
			folders[f.number("id")] = f
			if f["parent_id"] != nil {
				if _, ok := folders[f.number("parent_id")]; !ok {
					pending = append(pending, f.number("parent_id"))
				}
			}
		}
	}
	for element, start := range folderByElement {
		visited := map[int64]bool{}
		id := start
		for id != 0 && !visited[id] {
			visited[id] = true
			f, ok := folders[id]
			if !ok {
				break
			}
			if color := normalizedColor(f.text("color_hex")); color != nil {
				colors[element] = *color
				break
			}
			id = f.number("parent_id")
		}
	}
	return colors, nil
}
func buildTrainingSnapshot(ctx context.Context, db runtimeDB, trainingID int64, s sourceScenario, day int64, resolutions map[int64]*sourceExercise, assessments map[int64]int64) error {
	modules := s.dayModules(day)
	elementIDs := []int64{}
	for _, m := range modules {
		for _, e := range m.Exercises {
			for _, v := range e.Elements {
				elementIDs = append(elementIDs, v.number("element_id"))
			}
			if resolved := resolutions[e.Row.number("id")]; resolved != nil {
				for _, v := range resolved.Elements {
					elementIDs = append(elementIDs, v.number("element_id"))
				}
			}
		}
	}
	colors, err := loadElementColors(ctx, db, elementIDs)
	if err != nil {
		return err
	}
	meta := map[int64][3]int64{}
	counts := map[int64]int64{}
	days := append([]record{}, s.Days...)
	sort.SliceStable(days, func(i, j int) bool {
		for _, key := range []string{"day_index", "order_index", "id"} {
			a, b := days[i].number(key), days[j].number(key)
			if a != b {
				return a < b
			}
		}
		return false
	})
	for _, d := range days {
		index := d.number("day_index")
		counts[index]++
		meta[d.number("module_id")] = [3]int64{index, counts[index], d.number("id")}
	}
	for index, pdf := range s.Pdfs {
		row := pdf.project(mediaFields)
		row["order_index"] = index
		row["training_session_id"] = trainingID
		row["source_scenario_pdf_id"] = pdf.number("id")
		if _, err = insertSnapshotRecord(ctx, db, "training_session_scenario_pdf", row); err != nil {
			return err
		}
	}
	setup := int64(1)
	for position, module := range modules {
		m := module.Row
		dayMeta, ok := meta[m.number("id")]
		if !ok {
			dayMeta = [3]int64{day, int64(position + 1), 0}
		}
		var sourceDay any
		if dayMeta[2] != 0 {
			sourceDay = dayMeta[2]
		}
		moduleID, err := insertSnapshotRecord(ctx, db, "training_session_module", record{"training_session_id": trainingID, "runtime_module_id": m.number("id"), "source_module_id": m.number("id"), "source_scenario_day_module_id": sourceDay, "client_uid": m["client_uid"], "order_index": position, "day_index": dayMeta[0], "duration_minutes": m["duration_minutes"], "content_subcolumn_id_snapshot": m["content_subcolumn_id"], "content_subcolumn_name_snapshot": m["content_subcolumn_name"]})
		if err != nil {
			return err
		}
		label := fmt.Sprintf("Module %d", dayMeta[1])
		for _, source := range module.Exercises {
			e := source.Row
			effective := source
			resolved := resolutions[e.number("id")]
			kind := e.text("kind")
			if kind == "" {
				kind = "standard"
			}
			sourceKind := kind
			var blockID, assessmentID any
			duration, crew := e["duration_minutes"], e["crew_member_number"]
			if resolved != nil {
				effective = resolved
				kind = "standard"
				blockID = resolved.Row.number("id")
				if effective.Param["duration_minutes"] != nil {
					duration = effective.Param["duration_minutes"]
				}
				if e.number("crew_member_number") == 1 || e.number("crew_member_number") == 2 {
					assessmentID = assessments[e.number("crew_member_number")]
				}
			}
			service := kind == "preparation" || kind == "coffee_break"
			display := map[string]string{"standard": "Exercise", "preparation": "Preparation", "coffee_break": "Coffee break", "individual": "Individual"}[kind]
			setupLabel, step, name := "", display, label
			if service {
				name = display
			} else {
				setupLabel = strconv.FormatInt(setup, 10)
				display = "Exercise " + setupLabel
				step = setupLabel
				setup++
			}
			row := record{"training_session_id": trainingID, "training_session_module_id": moduleID, "runtime_exercise_id": e.number("id"), "source_exercise_id": e.number("id"), "source_block_id": blockID, "client_uid": e["client_uid"], "source_kind_snapshot": sourceKind, "kind": kind, "order_index": e["order_index"], "duration_minutes": duration, "crew_member_number": crew, "resolved_for_assessment_id": assessmentID, "setup_label": emptyToNil(setupLabel), "name": name, "display_label": display, "step_label": step, "is_service": service, "aircraft_ac_type": s.Row.text("aircraft_code"), "aircraft_engines": s.Row.text("engines"), "guidance_doc": effective.Param["guidance_doc"], "guidance_plain_text": effective.Param["guidance_plain_text"]}
			if row["aircraft_ac_type"] == "" {
				row["aircraft_ac_type"] = strconv.FormatInt(s.Row.number("aircraft_id"), 10)
			}
			performance, err := performanceColumns(effective.Param)
			if err != nil {
				return err
			}
			for key, value := range performance {
				row[key] = value
			}
			exerciseID, err := insertSnapshotRecord(ctx, db, "training_session_exercise", row)
			if err != nil {
				return err
			}
			for _, image := range source.Images {
				item := image.project(mediaFields)
				item["training_session_exercise_id"] = exerciseID
				item["source_exercise_image_id"] = image.number("id")
				if _, err = insertSnapshotRecord(ctx, db, "training_session_exercise_image", item); err != nil {
					return err
				}
			}
			offset := int64(0)
			for _, element := range effective.Elements {
				if element.number("order_index") == 0 {
					offset = 1
					break
				}
			}
			contentIDs := []int64{}
			seen := map[int64]bool{}
			valid := true
			for _, element := range effective.Elements {
				id := element.number("order_index") + offset
				if id <= 0 || seen[id] {
					valid = false
				}
				seen[id] = true
				contentIDs = append(contentIDs, id)
			}
			if !valid {
				for i := range contentIDs {
					contentIDs[i] = int64(i + 1)
				}
			}
			for i, element := range effective.Elements {
				item := element.project("order_index details starting_height ending_height profile_type")
				item["training_session_exercise_id"] = exerciseID
				item["content_id"] = contentIDs[i]
				item["source_exercise_element_id"] = nil
				if resolved == nil {
					item["source_exercise_element_id"] = element.number("id")
				}
				item["source_element_id"] = nil
				name := fmt.Sprintf("Element %d", contentIDs[i])
				typeLabel := ""
				var color any
				if library := element.object("element"); library != nil {
					item["source_element_id"] = library.number("id")
					if strings.TrimSpace(library.text("name")) != "" {
						name = library.text("name")
					}
					if library["severity"] != nil {
						severity := library.number("severity")
						typeLabel = map[int64]string{8: "HIGH", 5: "MEDIUM", 2: "LOW"}[severity]
						if typeLabel == "" {
							typeLabel = strconv.FormatInt(severity, 10)
						}
					}
					if value, ok := colors[library.number("id")]; ok {
						color = value
					}
				}
				if item["profile_type"] == nil || item["profile_type"] == "" {
					item["profile_type"] = "FLAT"
				}
				item["type_label_snapshot"] = emptyToNil(typeLabel)
				item["color_hex_snapshot"] = color
				item["element_name_snapshot"] = name
				if _, err = insertSnapshotRecord(ctx, db, "training_session_exercise_element", item); err != nil {
					return err
				}
			}
			for _, c := range effective.Competences {
				if _, err = insertSnapshotRecord(ctx, db, "training_session_exercise_competence", record{"training_session_exercise_id": exerciseID, "source_competence_id": c.number("id"), "code_snapshot": c["code"], "name_snapshot": c["name"], "order_index_snapshot": c["order_index"]}); err != nil {
					return err
				}
			}
		}
	}
	return nil
}
