package training

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
)

// DB records retain SQL NULL and exact JSON numbers. All projected snapshot
// fields are explicitly selected below; client objects never become SQL identifiers.
type record map[string]any

func (r record) number(key string) int64 {
	switch value := r[key].(type) {
	case nil:
		return 0
	case int64:
		return value
	case int:
		return int64(value)
	case json.Number:
		n, err := value.Int64()
		if err != nil {
			panic(err)
		}
		return n
	}
	panic("noninteger database field: " + key)
}
func (r record) text(key string) string { value, _ := r[key].(string); return value }
func (r record) object(key string) record {
	switch value := r[key].(type) {
	case map[string]any:
		return record(value)
	case record:
		return value
	}
	return nil
}
func (r record) project(keys string) record {
	out := record{}
	for _, key := range strings.Fields(keys) {
		out[key] = r[key]
	}
	return out
}
func decodeRecord(data []byte) (record, error) {
	var out record
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	err := d.Decode(&out)
	return out, err
}
func queryRecords(ctx context.Context, db runtimeDB, query string, args ...any) ([]record, error) {
	rows, err := db.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []record{}
	for rows.Next() {
		var data []byte
		if err = rows.Scan(&data); err != nil {
			return nil, err
		}
		value, err := decodeRecord(data)
		if err != nil {
			return nil, err
		}
		out = append(out, value)
	}
	return out, rows.Err()
}
func queryRecord(ctx context.Context, db runtimeDB, query string, args ...any) (record, error) {
	var raw []byte
	if err := db.QueryRow(ctx, query, args...).Scan(&raw); err != nil {
		return nil, err
	}
	return decodeRecord(raw)
}
func insertSnapshotRecord(ctx context.Context, db runtimeDB, table string, row record) (int64, error) {
	switch table {
	case "training_session", "crew_member_assessment", "training_session_module", "training_session_exercise", "training_session_exercise_element", "training_session_exercise_competence", "training_session_exercise_image", "training_session_scenario_pdf", "scenario_revision":
	default:
		return 0, fmt.Errorf("unsupported snapshot table %q", table)
	}
	keys := make([]string, 0, len(row))
	for key := range row {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	columns, parameters := []string{}, []string{}
	values := []any{}
	for i, key := range keys {
		columns = append(columns, pgx.Identifier{key}.Sanitize())
		parameters = append(parameters, "$"+strconv.Itoa(i+1))
		value := row[key]
		if number, ok := value.(json.Number); ok {
			integer, err := number.Int64()
			if err != nil {
				return 0, err
			}
			value = integer
		}
		values = append(values, value)
	}
	var id int64
	err := db.QueryRow(ctx, "INSERT INTO "+pgx.Identifier{table}.Sanitize()+" ("+strings.Join(columns, ",")+") VALUES ("+strings.Join(parameters, ",")+") RETURNING id", values...).Scan(&id)
	return id, err
}

type sourceExercise struct {
	Row, Param                    record
	Elements, Competences, Images []record
}
type sourceModule struct {
	Row       record
	Exercises []*sourceExercise
}
type sourceScenario struct {
	Row        record
	Modules    []sourceModule
	Days, Pdfs []record
}

func loadSourceScenario(ctx context.Context, db runtimeDB, id int64) (sourceScenario, error) {
	return loadSourceScenarioMode(ctx, db, id, false)
}

// The editor reads live ORM relationships; frozen snapshots retain their
// existing deterministic ordering. Keep each projection's ordering explicit.
func loadSourceScenarioMode(ctx context.Context, db runtimeDB, id int64, editor bool) (sourceScenario, error) {
	var s sourceScenario
	var err error
	s.Row, err = queryRecord(ctx, db, `SELECT to_jsonb(s)||jsonb_build_object('aircraft_code',a.code) FROM scenario s LEFT JOIN aircraft_airline a ON a.id=s.aircraft_id WHERE s.id=$1`, id)
	if err != nil {
		return s, err
	}
	dayQuery := `SELECT to_jsonb(d) FROM scenario_day_module d WHERE d.scenario_id=$1 ORDER BY d.day_index,d.order_index,d.module_id,d.id`
	if editor {
		dayQuery = `SELECT to_jsonb(d) FROM scenario_day_module d JOIN module m ON m.id=d.module_id WHERE m.scenario_id=$1 ORDER BY m.id`
	}
	s.Days, err = queryRecords(ctx, db, dayQuery, id)
	if err != nil {
		return s, err
	}
	s.Pdfs, err = queryRecords(ctx, db, `SELECT to_jsonb(p) FROM scenario_pdf p WHERE p.scenario_id=$1 ORDER BY p.order_index,p.id`, id)
	if err != nil {
		return s, err
	}
	modules, err := queryRecords(ctx, db, `SELECT to_jsonb(m)||jsonb_build_object('content_subcolumn_name',c.name,'content_subcolumn',to_jsonb(c)) FROM module m LEFT JOIN scenario_content_subcolumn c ON c.id=m.content_subcolumn_id WHERE m.scenario_id=$1 ORDER BY m.order_index,m.id`, id)
	if err != nil {
		return s, err
	}
	moduleIDs := []int64{}
	moduleIndex := map[int64]int{}
	for i, row := range modules {
		moduleIDs = append(moduleIDs, row.number("id"))
		moduleIndex[row.number("id")] = i
		s.Modules = append(s.Modules, sourceModule{Row: row, Exercises: []*sourceExercise{}})
	}
	exerciseQuery := `SELECT to_jsonb(e) FROM exercise e WHERE e.module_id=ANY($1)`
	if !editor {
		exerciseQuery += ` ORDER BY e.order_index,e.id`
	}
	rows, err := queryRecords(ctx, db, exerciseQuery, moduleIDs)
	if err != nil {
		return s, err
	}
	exercises := []*sourceExercise{}
	for _, row := range rows {
		e := &sourceExercise{Row: row}
		exercises = append(exercises, e)
		index := moduleIndex[row.number("module_id")]
		s.Modules[index].Exercises = append(s.Modules[index].Exercises, e)
	}
	if editor {
		for i := range s.Modules {
			sort.SliceStable(s.Modules[i].Exercises, func(a, b int) bool {
				return s.Modules[i].Exercises[a].Row.number("order_index") < s.Modules[i].Exercises[b].Row.number("order_index")
			})
		}
	}
	if err = loadExerciseAssetsMode(ctx, db, exercises, false, editor); err != nil {
		return s, err
	}
	return s, nil
}
func loadExerciseAssets(ctx context.Context, db runtimeDB, exercises []*sourceExercise, blocks bool) error {
	return loadExerciseAssetsMode(ctx, db, exercises, blocks, false)
}

func loadExerciseAssetsMode(ctx context.Context, db runtimeDB, exercises []*sourceExercise, blocks, editor bool) error {
	if len(exercises) == 0 {
		return nil
	}
	ids, paramIDs := []int64{}, []int64{}
	byID := map[int64]*sourceExercise{}
	paramKey, paramTable, linkKey, elementTable, competenceTable := "exercise_param_id", "exercise_param", "exercise_id", "exercise_element", "exercise_competence"
	if blocks {
		paramKey, paramTable, linkKey, elementTable, competenceTable = "element_block_param_id", "element_block_param", "block_id", "element_block_element", "element_block_competence"
	}
	for _, e := range exercises {
		ids = append(ids, e.Row.number("id"))
		byID[e.Row.number("id")] = e
		if e.Row[paramKey] != nil {
			paramIDs = append(paramIDs, e.Row.number(paramKey))
		}
		e.Elements = []record{}
		e.Competences = []record{}
		e.Images = []record{}
	}
	params, err := queryRecords(ctx, db, "SELECT to_jsonb(p) FROM "+paramTable+" p WHERE p.id=ANY($1)", paramIDs)
	if err != nil {
		return err
	}
	tlIDs := []int64{}
	for _, p := range params {
		for _, key := range []string{"original_tl_id", "destination_tl_id"} {
			if p[key] != nil {
				tlIDs = append(tlIDs, p.number(key))
			}
		}
	}
	tlRows, err := queryRecords(ctx, db, `SELECT to_jsonb(t)||jsonb_build_object('takeoff_details',to_jsonb(d)) FROM take_off_landing_param t LEFT JOIN takeoff_param_details d ON d.take_off_landing_param_id=t.id WHERE t.id=ANY($1)`, tlIDs)
	if err != nil {
		return err
	}
	tlByID, paramByID := map[int64]record{}, map[int64]record{}
	for _, tl := range tlRows {
		tlByID[tl.number("id")] = tl
	}
	for _, p := range params {
		p["original_tl"] = tlByID[p.number("original_tl_id")]
		p["destination_tl"] = tlByID[p.number("destination_tl_id")]
		paramByID[p.number("id")] = p
	}
	for _, e := range exercises {
		e.Param = paramByID[e.Row.number(paramKey)]
	}
	elementQuery := "SELECT to_jsonb(l)||jsonb_build_object('element',to_jsonb(e)) FROM " + elementTable + " l LEFT JOIN element e ON e.id=l.element_id WHERE l." + linkKey + "=ANY($1)"
	if !editor {
		elementQuery += " ORDER BY l.order_index,l.id"
	}
	var elements []record
	if editor {
		elements, err = loadEditorElementLinks(ctx, db, elementTable, linkKey, ids)
	} else {
		elements, err = queryRecords(ctx, db, elementQuery, ids)
	}
	if err != nil {
		return err
	}
	for _, element := range elements {
		e := byID[element.number(linkKey)]
		e.Elements = append(e.Elements, element)
	}
	if editor {
		for _, e := range exercises {
			sort.SliceStable(e.Elements, func(a, b int) bool { return e.Elements[a].number("order_index") < e.Elements[b].number("order_index") })
		}
	}
	competences, err := queryRecords(ctx, db, "SELECT to_jsonb(c)||jsonb_build_object('owner_id',l."+linkKey+") FROM "+competenceTable+" l JOIN competence c ON c.id=l.competence_id WHERE l."+linkKey+"=ANY($1) ORDER BY c.order_index,c.id", ids)
	if err != nil {
		return err
	}
	for _, c := range competences {
		e := byID[c.number("owner_id")]
		e.Competences = append(e.Competences, c)
	}
	if !blocks {
		images, err := queryRecords(ctx, db, `SELECT to_jsonb(i) FROM exercise_image i WHERE i.exercise_id=ANY($1) ORDER BY i.order_index,i.id`, ids)
		if err != nil {
			return err
		}
		for _, image := range images {
			e := byID[image.number("exercise_id")]
			e.Images = append(e.Images, image)
		}
	}
	return nil
}

// SQLAlchemy loads association rows before their elements, in batches of 500.
// A join may reverse that scan and reorder equal-order links when an element
// changes. Preserve association order before the caller's stable sort, since
// Instructor derives content IDs from that order.
func loadEditorElementLinks(ctx context.Context, db runtimeDB, table, owner string, ids []int64) ([]record, error) {
	out := []record{}
	elementIDs := []int64{}
	for start := 0; start < len(ids); start += 500 {
		rows, err := queryRecords(ctx, db, "SELECT to_jsonb(l) FROM "+table+" l WHERE l."+owner+"=ANY($1::bigint[])", ids[start:min(start+500, len(ids))])
		if err != nil {
			return nil, err
		}
		out = append(out, rows...)
		for _, row := range rows {
			elementIDs = append(elementIDs, row.number("element_id"))
		}
	}
	elements := map[int64]record{}
	for start := 0; start < len(elementIDs); start += 500 {
		rows, err := queryRecords(ctx, db, "SELECT to_jsonb(e) FROM element e WHERE e.id=ANY($1::bigint[])", elementIDs[start:min(start+500, len(elementIDs))])
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			elements[row.number("id")] = row
		}
	}
	for _, row := range out {
		row["element"] = elements[row.number("element_id")]
	}
	return out, nil
}
func (s sourceScenario) dayModules(day int64) []sourceModule {
	meta := map[int64][2]int64{}
	for _, d := range s.Days {
		meta[d.number("module_id")] = [2]int64{d.number("day_index"), d.number("order_index")}
	}
	modules := []sourceModule{}
	for _, m := range s.Modules {
		md, ok := meta[m.Row.number("id")]
		if !ok {
			md = [2]int64{1, m.Row.number("order_index")}
			meta[m.Row.number("id")] = md
		}
		if md[0] == day {
			modules = append(modules, m)
		}
	}
	sort.SliceStable(modules, func(i, j int) bool {
		a, b := modules[i].Row, modules[j].Row
		ma, mb := meta[a.number("id")], meta[b.number("id")]
		if ma[1] != mb[1] {
			return ma[1] < mb[1]
		}
		if a.number("order_index") != b.number("order_index") {
			return a.number("order_index") < b.number("order_index")
		}
		return a.number("id") < b.number("id")
	})
	return modules
}
