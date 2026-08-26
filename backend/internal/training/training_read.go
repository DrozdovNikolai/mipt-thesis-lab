package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

var snakePart = regexp.MustCompile(`_([a-zA-Z0-9])`)

func camelKey(key string) string {
	return snakePart.ReplaceAllStringFunc(key, func(s string) string { return strings.ToUpper(s[1:]) })
}
func camelValue(v any) any {
	switch value := v.(type) {
	case map[string]any:
		out := map[string]any{}
		for key, item := range value {
			out[camelKey(key)] = camelValue(item)
		}
		return out
	case record:
		return camelValue(map[string]any(value))
	case []any:
		out := make([]any, len(value))
		for i, item := range value {
			out[i] = camelValue(item)
		}
		return out
	}
	return v
}
func snapshotPhase(row record, phase string) map[string]any {
	out := map[string]any{}
	for category, fields := range map[string]string{"weather": weatherFields, "aircraft": aircraftFieldsList, "atc": atcFields} {
		values := map[string]any{}
		for _, key := range strings.Fields(fields) {
			values[camelKey(key)] = row.text(phase + "_" + category + "_" + key)
		}
		out[category] = values
	}
	return out
}
func snapshotMedia(row record, prefix, source string) map[string]any {
	id := row.number(source)
	if id == 0 {
		id = row.number("id")
	}
	return map[string]any{"id": id, "url": prefix + row.text("storage_key"), "orderIndex": row.number("order_index"), "originalFilename": row.text("original_filename"), "displayName": row["display_name"], "contentType": row.text("content_type"), "sizeBytes": row.number("size_bytes"), "sha256": row.text("sha256")}
}
func (s *Service) trainingExercisesResponse(ctx context.Context, db runtimeDB, id int64) (map[string]any, error) {
	training, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if err != nil {
		return nil, err
	}
	label := training.text("scenario_label_snapshot")
	if label == "" {
		label = training.text("scenario_title_snapshot")
	}
	if label == "" {
		label = fmt.Sprintf("Training Session %d", id)
	}
	pdfRows, err := queryRecords(ctx, db, `SELECT to_jsonb(p) FROM training_session_scenario_pdf p WHERE training_session_id=$1 ORDER BY order_index,id`, id)
	if err != nil {
		return nil, err
	}
	pdfs := []map[string]any{}
	for _, pdf := range pdfRows {
		pdfs = append(pdfs, snapshotMedia(pdf, s.Auth.Config.APIPrefix+"/training/scenario-pdfs/", "source_scenario_pdf_id"))
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise e JOIN training_session_module m ON m.id=e.training_session_module_id WHERE e.training_session_id=$1 ORDER BY m.order_index,m.runtime_module_id,e.order_index,e.runtime_exercise_id`, id)
	if err != nil {
		return nil, err
	}
	ids := []int64{}
	for _, row := range rows {
		ids = append(ids, row.number("id"))
	}
	elements, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise_element e WHERE training_session_exercise_id=ANY($1) ORDER BY order_index,content_id,id`, ids)
	if err != nil {
		return nil, err
	}
	images, err := queryRecords(ctx, db, `SELECT to_jsonb(i) FROM training_session_exercise_image i WHERE training_session_exercise_id=ANY($1) ORDER BY order_index,id`, ids)
	if err != nil {
		return nil, err
	}
	contentByExercise, imagesByExercise := map[int64][]map[string]any{}, map[int64][]map[string]any{}
	for _, e := range elements {
		eid := e.number("training_session_exercise_id")
		contentID := e.number("content_id")
		if contentID == 0 {
			contentID = int64(len(contentByExercise[eid]) + 1)
		}
		item := map[string]any{"id": contentID, "elementId": e["source_element_id"], "type": e.text("type_label_snapshot"), "colorHex": e["color_hex_snapshot"], "elements": e.text("element_name_snapshot"), "details": e.text("details")}
		for _, key := range []string{"starting_height", "ending_height"} {
			if e[key] != nil {
				item[camelKey(key)] = e[key]
			}
		}
		profile := strings.ToUpper(strings.TrimSpace(e.text("profile_type")))
		if profile != "FLAT" && profile != "UP" && profile != "DOWN" && profile != "LINKED" {
			profile = "FLAT"
		}
		if profile != "FLAT" || e["starting_height"] != nil || e["ending_height"] != nil {
			item["profileType"] = profile
		}
		contentByExercise[eid] = append(contentByExercise[eid], item)
	}
	for _, image := range images {
		eid := image.number("training_session_exercise_id")
		imagesByExercise[eid] = append(imagesByExercise[eid], snapshotMedia(image, s.Auth.Config.APIPrefix+"/training/exercise-images/", "source_exercise_image_id"))
	}
	exercises := []map[string]any{}
	for _, e := range rows {
		content := contentByExercise[e.number("id")]
		if content == nil {
			content = []map[string]any{}
		}
		images := imagesByExercise[e.number("id")]
		if images == nil {
			images = []map[string]any{}
		}
		pf := ""
		if e.number("crew_member_number") != 0 {
			pf = fmt.Sprintf("CM%d", e.number("crew_member_number"))
		}
		isService, _ := e["is_service"].(bool)
		exercises = append(exercises, map[string]any{"id": e.number("runtime_exercise_id"), "resolvedForAssessmentId": e["resolved_for_assessment_id"], "setup": e.text("setup_label"), "kind": e.text("kind"), "sourceKind": e.text("source_kind_snapshot"), "name": e.text("name"), "displayLabel": e.text("display_label"), "stepLabel": e.text("step_label"), "isService": isService, "duration": e.number("duration_minutes"), "pf": pf, "aircraft": map[string]any{"acType": e.text("aircraft_ac_type"), "engines": e.text("aircraft_engines")}, "performance": map[string]any{"departure": snapshotPhase(e, "departure"), "arrival": snapshotPhase(e, "arrival")}, "guidanceDoc": camelValue(e["guidance_doc"]), "guidancePlainText": e.text("guidance_plain_text"), "guidance": e.text("guidance_plain_text"), "content": content, "images": images})
	}
	var first any
	if len(pdfs) > 0 {
		first = pdfs[0]
	}
	return map[string]any{"scenario": label, "exercises": exercises, "pdfs": pdfs, "pdf": first}, nil
}
func (s *Service) loadCreateTrainingResponse(ctx context.Context, db runtimeDB, id, instructor int64) (map[string]any, error) {
	training, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1 AND instructor_id=$2`, id, instructor)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	if err != nil {
		return nil, err
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE training_session_id=$1`, id)
	if err != nil {
		return nil, err
	}
	roles := map[string]record{}
	for _, row := range rows {
		roles[strings.ToLower(row.text("training_role"))] = row
	}
	cm1, cm2 := roles["cm1"], roles["cm2"]
	if len(roles) != 2 || cm1 == nil || cm2 == nil || cm1["user_id"] == nil || cm2["user_id"] == nil {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	state, err := loadRuntimeState(ctx, db, id, false)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, runtimeError("RUNTIME_CHAIN_CORRUPT")
	}
	if err != nil {
		return nil, err
	}
	response, err := s.trainingExercisesResponse(ctx, db, id)
	if err != nil {
		return nil, err
	}
	for key, value := range map[string]any{"clientCreationId": training["client_creation_id"], "trainingId": id, "cm1AssessmentId": cm1.number("id"), "cm2AssessmentId": cm2.number("id"), "scenarioRevisionId": training["scenario_revision_id"], "scenarioRevisionNumber": training["scenario_revision_number"], "participants": []map[string]any{{"assessmentId": cm1.number("id"), "userId": cm1.number("user_id"), "initialCrewSlot": "CM1"}, {"assessmentId": cm2.number("id"), "userId": cm2.number("user_id"), "initialCrewSlot": "CM2"}}, "crewRuntime": state.response(), "commentContract": map[string]any{"version": training.number("comment_contract_version"), "quickCommentsEntitled": training.number("comment_contract_version") == 1}, "evaluationCatalog": training["evaluation_catalog_snapshot"], "evaluationCatalogSha256": training["evaluation_catalog_sha256"]} {
		response[key] = value
	}
	return response, nil
}
func (s *Service) getTrainingExercises(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	if _, err = getRuntimeTraining(r.Context(), s.Auth.DB, id, user); err != nil {
		return err
	}
	value, err := s.trainingExercisesResponse(r.Context(), s.Auth.DB, id)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, value)
	return nil
}
func (s *Service) deleteTraining(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	requested := map[int64]bool{}
	if values, ok := r.URL.Query()["cmAssessmentIds"]; ok {
		raw := []any{}
		for _, v := range values {
			raw = append(raw, v)
		}
		o, err := platform.ValidateObject(map[string]any{"cmAssessmentIds": raw}, []any{"query"}, platform.Schema{Fields: []platform.Field{{Name: "ids", Alias: "cmAssessmentIds", Kind: "list", Item: &platform.Field{Kind: "integer"}}}})
		if err != nil {
			return err
		}
		for _, v := range o["ids"].([]any) {
			requested[v.(int64)] = true
		}
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	training, err := queryRecord(ctx, tx, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Training not found")
	}
	if err != nil {
		return err
	}
	if training["instructor_id"] != nil && training.number("instructor_id") != user.InternalID {
		return platform.Error(403, "Training belongs to another instructor")
	}
	rows, err := tx.Query(ctx, `SELECT id FROM crew_member_assessment WHERE training_session_id=$1`, id)
	if err != nil {
		return err
	}
	ids := []int64{}
	for rows.Next() {
		var aid int64
		if err = rows.Scan(&aid); err != nil {
			rows.Close()
			return err
		}
		if len(requested) == 0 || requested[aid] {
			ids = append(ids, aid)
		}
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	if training.text("status") != "DELETED" {
		if _, err = tx.Exec(ctx, `UPDATE training_session SET status='DELETED',updated_at=now() WHERE id=$1`, id); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Training deleted", "action", "assessment.delete_training", "training_id", id, "user_id", user.ID.String())
	platform.WriteJSON(w, 200, map[string]any{"trainingId": id, "deletedAssessmentIds": ids})
	return nil
}
