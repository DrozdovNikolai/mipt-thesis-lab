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
