package training

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

type airlineClone struct {
	ctx                   context.Context
	tx                    pgx.Tx
	source, target, actor int64
	rows                  map[string][]record
	childrenByKey         map[string]map[int64][]record
	sourceByID            map[string]map[int64]record
	mappedIDs             map[string]map[int64]int64
	counts                record
	err                   error
}

func cloneAirlineStructure(ctx context.Context, tx pgx.Tx, source, target, actor int64) (record, error) {
	e := &airlineClone{ctx: ctx, tx: tx, source: source, target: target, actor: actor, rows: map[string][]record{}, mappedIDs: map[string]map[int64]int64{}, counts: record{}}
	for _, key := range strings.Fields("grading_schemes grading_scale_values aircraft competences flight_types flight_type_competence_thresholds behavioural_indicators elements element_folders element_folder_items element_blocks element_block_elements element_block_competences block_folders block_folder_items content_sets content_labels content_subcolumns content_folders content_requirements content_requirement_elements content_cells scenarios scenario_label_links modules exercises exercise_elements exercise_competences") {
		e.counts[key] = int64(0)
	}
	if err := e.assertEmpty(); err != nil {
		return nil, err
	}
	e.loadSource()
	if e.err != nil {
		return nil, e.err
	}
	if _, e.err = tx.Exec(ctx, "DELETE FROM grading_scheme WHERE airline_id=$1", target); e.err != nil {
		return nil, e.err
	}
	e.cloneCatalogs()
	e.cloneLibrary()
	e.cloneContent()
	e.cloneScenarios()
	return e.counts, e.err
}
func (e *airlineClone) assertEmpty() error {
	counts := record{}
	nonempty := false
	for _, entry := range [][2]string{{"training_sessions", "training_session"}, {"aircraft", "aircraft_airline"}, {"competences", "competence"}, {"flight_types", "flight_type"}, {"elements", "element"}, {"element_folders", "element_folder"}, {"element_blocks", "element_block"}, {"block_folders", "block_folder"}, {"content_sets", "scenario_content_set"}, {"scenarios", "scenario"}} {
		query := "SELECT count(*) FROM " + entry[1] + " WHERE airline_id=$1"
		if entry[0] == "training_sessions" {
			query = "SELECT count(*) FROM training_session t JOIN grading_scheme g ON g.id=t.grading_scheme_id WHERE g.airline_id=$1"
		}
		var count int64
		if err := e.tx.QueryRow(e.ctx, query, e.target).Scan(&count); err != nil {
			return err
		}
		counts[entry[0]] = count
		nonempty = nonempty || count > 0
	}
	if nonempty {
		return &platform.APIError{Status: 400, Code: "TARGET_AIRLINE_NOT_EMPTY", Message: "Target airline training structure must be empty before cloning", Extra: map[string]any{"counts": commanderWire(counts)}}
	}
	return nil
}
func (e *airlineClone) load(table, where, order string, args ...any) {
	if e.err != nil {
		return
	}
	e.rows[table], e.err = queryRecords(e.ctx, e.tx, "SELECT to_jsonb(t) FROM "+table+" t WHERE "+where+" ORDER BY "+order, args...)
}
func (e *airlineClone) loadChildren(table, key, parent string, order string) {
	ids := []int64{}
	for _, row := range e.rows[parent] {
		ids = append(ids, row.number("id"))
	}
	e.load(table, key+"=ANY($1::bigint[])", order, ids)
}
func (e *airlineClone) loadReferenced(table, parent, field string) {
	ids := []int64{}
	for _, row := range e.rows[parent] {
		if row[field] != nil {
			ids = append(ids, row.number(field))
		}
	}
	e.load(table, "id=ANY($1::bigint[])", "id", ids)
}
func (e *airlineClone) loadSource() {
	for _, entry := range [][3]string{{"grading_scheme", "", "version,id"}, {"aircraft_airline", "", "id"}, {"competence", " AND retired_at IS NULL", "order_index,id"}, {"flight_type", "", "lower(name),id"}, {"element", " AND archived_at IS NULL", "id"}, {"element_folder", " AND archived_at IS NULL", "id"}, {"element_block", " AND archived_at IS NULL", "id"}, {"block_folder", " AND archived_at IS NULL", "id"}, {"scenario_content_set", "", "id"}, {"scenario", " AND status<>'ARCHIVED' AND deleted_at IS NULL", "id"}} {
		e.load(entry[0], "airline_id=$1"+entry[1], entry[2], e.source)
	}
	for _, entry := range [][4]string{{"grading_scale_value", "grading_scheme_id", "grading_scheme", "order_index,id"}, {"behavioural_indicator", "competence_id", "competence", "order_index,id"}, {"flight_type_competence_threshold", "flight_type_id", "flight_type", "competence_id,id"}, {"element_folder_item", "folder_id", "element_folder", "order_index,id"}, {"element_block_element", "block_id", "element_block", "order_index,id"}, {"element_block_competence", "block_id", "element_block", "competence_id,id"}, {"block_folder_item", "folder_id", "block_folder", "order_index,id"}, {"scenario_content_set_label", "content_set_id", "scenario_content_set", "order_index,id"}, {"scenario_content_subcolumn", "content_set_id", "scenario_content_set", "order_index,id"}, {"scenario_content_folder", "content_set_id", "scenario_content_set", "id"}, {"scenario_content_requirement", "content_set_id", "scenario_content_set", "folder_id,order_index,id"}, {"scenario_content_cell", "content_set_id", "scenario_content_set", "id"}, {"scenario_content_requirement_element", "requirement_id", "scenario_content_requirement", "order_index,id"}, {"scenario_content_set_label_scenario", "label_id", "scenario_content_set_label", "id"}, {"module", "scenario_id", "scenario", "order_index,id"}, {"scenario_day_module", "module_id", "module", "id"}, {"exercise", "module_id", "module", "order_index,id"}, {"exercise_element", "exercise_id", "exercise", "order_index,id"}, {"exercise_competence", "exercise_id", "exercise", "competence_id,id"}} {
		e.loadChildren(entry[0], entry[1], entry[2], entry[3])
	}
	e.loadReferenced("element_block_param", "element_block", "element_block_param_id")
	e.loadReferenced("exercise_param", "exercise", "exercise_param_id")
	ids := []int64{}
	for _, table := range []string{"element_block_param", "exercise_param"} {
		for _, row := range e.rows[table] {
			for _, field := range []string{"original_tl_id", "destination_tl_id"} {
				if row[field] != nil {
					ids = append(ids, row.number(field))
				}
			}
		}
	}
	e.load("take_off_landing_param", "id=ANY($1::bigint[])", "id", ids)
	e.load("takeoff_param_details", "take_off_landing_param_id=ANY($1::bigint[])", "take_off_landing_param_id", ids)
}
func (e *airlineClone) children(table, key string, id int64) []record {
	if e.childrenByKey == nil {
		e.childrenByKey = map[string]map[int64][]record{}
	}
	indexKey := table + "." + key
	index, ok := e.childrenByKey[indexKey]
	if !ok {
		index = map[int64][]record{}
		for _, row := range e.rows[table] {
			if row[key] != nil {
				n := row.number(key)
				index[n] = append(index[n], row)
			}
		}
		e.childrenByKey[indexKey] = index
	}
	return index[id]
}
func (e *airlineClone) lookup(table string, id any) record {
	if id == nil {
		return nil
	}
	if e.sourceByID == nil {
		e.sourceByID = map[string]map[int64]record{}
	}
	index, ok := e.sourceByID[table]
	if !ok {
		index = map[int64]record{}
		for _, row := range e.rows[table] {
			index[row.number("id")] = row
		}
		e.sourceByID[table] = index
	}
	return index[record{"id": id}.number("id")]
}
func (e *airlineClone) mapped(table string, id any, field string, required bool) any {
	if e.err != nil {
		return nil
	}
	if id == nil {
		if required {
			e.err = &platform.APIError{Status: 400, Code: "SOURCE_DATA_INTEGRITY_ERROR", Message: "Missing required mapped id for " + field, Extra: map[string]any{"field": field}}
		}
		return nil
	}
	n := record{"id": id}.number("id")
	mapped, ok := e.mappedIDs[table][n]
	if !ok {
		e.err = &platform.APIError{Status: 400, Code: "SOURCE_DATA_INTEGRITY_ERROR", Message: "Missing mapped id for " + field, Extra: map[string]any{"field": field, "source_id": n}}
		return nil
	}
	return mapped
}
func (e *airlineClone) add(table string, row record, source any, count string) int64 {
	if e.err != nil {
		return 0
	}
	// Folder order_index has a server default in SQLAlchemy: explicit
	// None on INSERT is omitted, so the database supplies zero.
	if (table == "element_folder" || table == "block_folder") && row["order_index"] == nil {
		delete(row, "order_index")
	}
	var created record
	created, e.err = insertTrainingRow(e.ctx, e.tx, table, row)
	if e.err != nil {
		return 0
	}
	id := created.number("id")
	if source != nil {
		if e.mappedIDs[table] == nil {
			e.mappedIDs[table] = map[int64]int64{}
		}
		e.mappedIDs[table][record{"id": source}.number("id")] = id
	}
	if count != "" {
		e.counts[count] = e.counts.number(count) + 1
	}
	return id
}
func (e *airlineClone) sortRows(rows []record, fields ...string) {
	sort.SliceStable(rows, func(i, j int) bool {
		for _, field := range fields {
			a, b := rows[i][field], rows[j][field]
			if a == nil && b == nil {
				continue
			}
			if a == nil || b == nil {
				if e.err == nil {
					e.err = fmt.Errorf("clone source order contains incomparable null values")
				}
				return false
			}
			x, y := rows[i].number(field), rows[j].number(field)
			if x != y {
				return x < y
			}
		}
		return false
	})
}
func (e *airlineClone) takeoff(raw any) any {
	source := e.lookup("take_off_landing_param", raw)
	if source == nil {
		return nil
	}
	row := source.project("airport_name time_of_day runway braking_action special_wx wind_dir wind_speed wind_gust visibility_value clouds_amount clouds_ceiling_ft rvr_h rvr_v temperature_c qnh_hpa fuel cg_percent")
	id := e.add("take_off_landing_param", row, nil, "")
	for _, details := range e.children("takeoff_param_details", "take_off_landing_param_id", source.number("id")) {
		d := details.project("thrust_setting flaps_setting v2_speed vr_speed v1_speed sid squawk_code frequency climb")
		d["take_off_landing_param_id"] = id
		e.add("takeoff_param_details", d, nil, "")
	}
	return id
}
