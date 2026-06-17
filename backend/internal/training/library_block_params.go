package training

import (
	"context"
	"fmt"
	"strings"

	"north55/backend/internal/platform"
)

func libraryRecord(value any) record {
	switch v := value.(type) {
	case platform.Object:
		return record(v)
	case record:
		return v
	case map[string]any:
		return record(v)
	}
	return nil
}
func libraryGuidanceStorage(params record) (any, any, error) {
	doc, err := normalizeGuidance(params["guidance_doc"])
	if err != nil {
		return nil, nil, err
	}
	if doc == nil {
		plain, _ := params["guidance_plain_text"].(string)
		plain = pythonTrim(plain)
		if plain == "" {
			return nil, nil, nil
		}
		doc, err = normalizeGuidance(map[string]any{"ops": []any{map[string]any{"insert": plain}}})
		if err != nil {
			return nil, nil, err
		}
	}
	if doc == nil {
		return nil, nil, nil
	}
	var out strings.Builder
	for _, op := range doc["ops"].([]any) {
		out.WriteString(libraryRecord(op).text("insert"))
	}
	plain := pythonTrim(strings.ReplaceAll(strings.TrimSuffix(out.String(), "\n"), "\u00a0", " "))
	if plain == "" {
		return nil, nil, nil
	}
	return doc, plain, nil
}
func libraryInsertTL(ctx context.Context, db runtimeDB, payload any, takeoff bool) (any, error) {
	data := libraryRecord(payload)
	if data == nil {
		return nil, nil
	}
	row, err := insertTrainingRow(ctx, db, "take_off_landing_param", data.project(libraryTLFields))
	if err != nil {
		return nil, err
	}
	if takeoff {
		details := data.project(libraryTakeoffFields)
		hasDetails := false
		for _, value := range details {
			hasDetails = hasDetails || value != nil
		}
		if hasDetails {
			details["take_off_landing_param_id"] = row["id"]
			if _, err = insertTrainingRow(ctx, db, "takeoff_param_details", details); err != nil {
				return nil, err
			}
		}
	}
	return row["id"], nil
}
func libraryNewBlockParams(ctx context.Context, db runtimeDB, payload record) (record, error) {
	data := payload.project(libraryParamFields)
	var err error
	data["original_tl_id"], err = libraryInsertTL(ctx, db, payload["original_tl"], true)
	if err != nil {
		return nil, err
	}
	data["destination_tl_id"], err = libraryInsertTL(ctx, db, payload["destination_tl"], false)
	if err != nil {
		return nil, err
	}
	data["guidance_doc"], data["guidance_plain_text"], err = libraryGuidanceStorage(payload)
	if err != nil {
		return nil, err
	}
	return data, nil
}
func libraryReplaceBlockParams(ctx context.Context, db runtimeDB, block, payload record) error {
	old, err := libraryFind(ctx, db, "element_block_param", block["element_block_param_id"])
	if err != nil {
		return err
	}
	if old == nil {
		old, err = insertTrainingRow(ctx, db, "element_block_param", record{}.project(libraryParamFields))
		if err != nil {
			return err
		}
		if err = libraryUpdate(ctx, db, "element_block", block, record{"element_block_param_id": old["id"]}); err != nil {
			return err
		}
	}
	ids := []int64{}
	for _, key := range []string{"original_tl_id", "destination_tl_id"} {
		if id := old.number(key); id != 0 && !libraryContains(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) > 0 {
		if _, err = db.Exec(ctx, "DELETE FROM take_off_landing_param WHERE id=ANY($1::bigint[])", ids); err != nil {
			return err
		}
	}
	// A TL INSERT flushes the cleared parameter before the new links are set.
	// Keep that intermediate UPDATE so SQL triggers see the same transaction.
	cleared := record{}.project(libraryParamFields)
	flushCleared := libraryRecord(payload["original_tl"]) != nil || libraryRecord(payload["destination_tl"]) != nil
	if flushCleared {
		if err = libraryUpdate(ctx, db, "element_block_param", old, cleared); err != nil {
			return err
		}
		for key := range cleared {
			old[key] = nil
		}
	}
	data, err := libraryNewBlockParams(ctx, db, payload)
	if err != nil {
		return err
	}
	// Compare JSON values by numeric equality (1 == 1.0 == true).
	// Without an intermediate flush, assigning an equal document is a no-op.
	if jsonEqual(old["guidance_doc"], data["guidance_doc"]) {
		data["guidance_doc"] = old["guidance_doc"]
	}
	return libraryUpdate(ctx, db, "element_block_param", old, data)
}

func libraryTLDTO(ctx context.Context, db runtimeDB, id any) (any, error) {
	if id == nil {
		return nil, nil
	}
	row, err := queryRecord(ctx, db, `SELECT to_jsonb(t)||coalesce(to_jsonb(d),'{}'::jsonb) FROM take_off_landing_param t LEFT JOIN takeoff_param_details d ON d.take_off_landing_param_id=t.id WHERE t.id=$1`, id)
	if err != nil {
		return nil, err
	}
	return map[string]any(row.project(libraryTLFields + " " + libraryTakeoffFields)), nil
}
func libraryBlockParamDTO(ctx context.Context, db runtimeDB, id any) (any, error) {
	row, err := libraryFind(ctx, db, "element_block_param", id)
	if err != nil || row == nil {
		return nil, err
	}
	data := row.project("intensity zfw_t guidance_doc guidance_plain_text duration_minutes crew_member_number")
	data["original_tl"], err = libraryTLDTO(ctx, db, row["original_tl_id"])
	if err != nil {
		return nil, err
	}
	data["destination_tl"], err = libraryTLDTO(ctx, db, row["destination_tl_id"])
	if err != nil {
		return nil, err
	}
	var fatal error
	value, err := platform.ValidateObject(map[string]any(data), nil, libraryParamModel(nil, &fatal))
	if err != nil || fatal != nil {
		return nil, fmt.Errorf("invalid stored block parameters: %v %v", err, fatal)
	}
	result := record(value)
	for _, key := range []string{"original_tl", "destination_tl"} {
		if result[key] != nil {
			result[key] = libraryRecord(result[key])
		}
	}
	return result, nil
}
