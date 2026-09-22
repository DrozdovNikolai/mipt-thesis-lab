package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func resolveFinalizeTraining(ctx context.Context, db runtimeDB, o platform.Object) (int64, error) {
	blocks := finalizeBlocks(o)
	ids := []int64{}
	seen := map[int64]bool{}
	for _, b := range blocks {
		if seen[b.Int("assessment_id")] {
			return 0, platform.Error(400, "Assessment IDs must be unique")
		}
		seen[b.Int("assessment_id")] = true
		ids = append(ids, b.Int("assessment_id"))
	}
	if len(ids) == 0 {
		return 0, platform.Error(400, "No assessment payload provided")
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE id=ANY($1)`, ids)
	if err != nil {
		return 0, err
	}
	if len(rows) != len(ids) {
		return 0, platform.Error(404, "Assessment not found")
	}
	id := rows[0].number("training_session_id")
	for _, row := range rows {
		if row.number("training_session_id") != id {
			return 0, platform.Error(400, "Assessments must belong to the same training session")
		}
	}
	if o["training_id"] != nil && o.Int("training_id") != id {
		return 0, platform.Error(400, "training_id does not match assessment training session")
	}
	return id, nil
}

func timelineReportEvent(ctx context.Context, db runtimeDB, id int64, exercise record, r platform.Object) (int64, error) {
	key, err := uuid.Parse(r.String("exercise_session_key"))
	if err != nil {
		return 0, runtimeError("CREW_EVENT_CONTEXT_INVALID")
	}
	run, err := queryRecord(ctx, db, `SELECT to_jsonb(r) FROM training_session_exercise_run r WHERE training_session_id=$1 AND exercise_session_key=$2`, id, key)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && (run.number("training_session_exercise_id") != exercise.number("id") || run.number("runtime_exercise_id") != exercise.number("runtime_exercise_id")) {
		return 0, runtimeError("CREW_EVENT_CONTEXT_INVALID")
	}
	if err != nil {
		return 0, err
	}
	if r.Int("exercise_offset_ms") > run.number("active_duration_ms") {
		return 0, runtimeError("CREW_EVENT_OFFSET_INVALID")
	}
	event, err := queryRecord(ctx, db, `SELECT to_jsonb(e) FROM training_session_crew_assignment_event e JOIN training_session_crew_state s ON s.training_session_id=e.training_session_id WHERE e.training_session_id=$1 AND e.public_id=$2 AND e.server_revision<=s.current_revision`, id, r["assignment_event_id_at_observation"])
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, runtimeError("CREW_EVENT_CONTEXT_INVALID")
	}
	if err != nil {
		return 0, err
	}
	if event.text("public_id") != run.text("initial_assignment_event_public_id") && event.text("event_scope") != "SESSION" {
		if event.text("event_scope") != "EXERCISE_RUN" || event.text("exercise_session_key") != key.String() || event.number("training_session_exercise_id") != exercise.number("id") || event["exercise_offset_ms"] == nil || event.number("exercise_offset_ms") > r.Int("exercise_offset_ms") {
			return 0, runtimeError("CREW_EVENT_CONTEXT_INVALID")
		}
	}
	return event.number("id"), nil
}

func finalizeOneBlock(ctx context.Context, db runtimeDB, trainingID int64, b platform.Object, c assessmentCatalog, exercises map[int64]record) (map[string]any, error) {
	id := b.Int("assessment_id")
	a, err := queryRecord(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, platform.Error(404, "Assessment not found")
	}
	if err != nil {
		return nil, err
	}
	if a.number("training_session_id") != trainingID {
		return nil, platform.Error(400, "training_id does not match assessment training session")
	}
	if _, err = db.Exec(ctx, `DELETE FROM final_report WHERE assessment_id=$1`, id); err != nil {
		return nil, err
	}
	if _, err = db.Exec(ctx, `DELETE FROM mistake_report WHERE assessment_id=$1`, id); err != nil {
		return nil, err
	}
	finalIDs, mistakeIDs := []int64{}, []int64{}
	for _, entry := range b["ordered_grades"].(canonical.Grades) {
		compID := c.Codes[assessmentUpper(entry.Code)]
		gradeCode := assessmentUpper(pythonTrim(entry.Value))
		if compID == 0 || gradeCode == "" {
			continue
		}
		grade, ok := c.Grades[gradeCode]
		if !ok {
			return nil, platform.Error(400, fmt.Sprintf("Unknown grade '%s' for active grading scale", gradeCode))
		}
		comp := c.Competences[compID]
		var reportID int64
		err = db.QueryRow(ctx, `INSERT INTO final_report(assessment_id,competence_id,competence_code_snapshot,competence_name_snapshot,competence_order_index_snapshot,grading_scale_value_id,grade,grade_code_snapshot,grade_label_snapshot,grade_score_snapshot,grade_weight_snapshot,grade_color_hex_snapshot) VALUES($1,$2,$3,$4,$5,$6,$7,$7,$8,$9::text::numeric,$10::text::numeric,$11) RETURNING id`, id, compID, comp["code"], comp["name"], comp.number("order_index"), grade.number("id"), grade["code"], grade["label"], grade["score_numeric"], grade["grade_weight"], grade["color_hex"]).Scan(&reportID)
		if err != nil {
			return nil, err
		}
		finalIDs = append(finalIDs, reportID)
	}
	for _, raw := range b["mistake_reports"].([]any) {
		r := raw.(platform.Object)
		exercise := exercises[r.Int("exercise_id")]
		if exercise == nil {
			return nil, platform.Error(400, fmt.Sprintf("Exercise %d is not available for this training scenario day", r.Int("exercise_id")))
		}
		compID := r.Int("comp_id")
		valid := false
		for _, id := range c.Codes {
			valid = valid || id == compID
		}
		if !valid {
			return nil, platform.Error(400, fmt.Sprintf("Competence %d is not available for this training", compID))
		}
		var indicator record
		if r["bi_id"] != nil {
			indicator = c.Indicators[r.Int("bi_id")]
			if indicator == nil {
				return nil, platform.Error(400, fmt.Sprintf("Behavioural indicator %d is not available for this training", r.Int("bi_id")))
			}
			if helperPositive(indicator.text("code")) {
				return nil, platform.Error(400, "Positive comments must use a real behavioural indicator and report-level isPositive")
			}
			if indicator.number("competence_id") != compID {
				return nil, platform.Error(400, fmt.Sprintf("Behavioural indicator %d does not belong to competence %d", r.Int("bi_id"), compID))
			}
		}
		var eventID any
		seconds := r.Int("exercise_offset_sec")
		if r.String("timeline_source") == "TIMELINE" {
			eventID, err = timelineReportEvent(ctx, db, trainingID, exercise, r)
			if err != nil {
				return nil, err
			}
			seconds = r.Int("exercise_offset_ms") / 1000
		}
		comp := c.Competences[compID]
		var reportID int64
		err = db.QueryRow(ctx, `INSERT INTO mistake_report(assessment_id,training_session_exercise_id,exercise_id,timestamp,exercise_offset_sec,exercise_session_key,client_report_id,timeline_source,exercise_offset_ms,assignment_event_id_at_observation,competence_id,behavioural_indicator_id,competence_code_snapshot,competence_name_snapshot,behavioural_indicator_code_snapshot,behavioural_indicator_name_snapshot,comment,hashtag,is_positive) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) RETURNING id`, id, exercise.number("id"), exercise.number("runtime_exercise_id"), r["timestamp"], seconds, r["exercise_session_key"], r["client_report_id"], r["timeline_source"], r["exercise_offset_ms"], eventID, compID, r["bi_id"], comp["code"], comp["name"], indicator["code"], indicator["name"], r["comment"], r["hashtag"], r["is_positive"]).Scan(&reportID)
		if err != nil {
			return nil, err
		}
		mistakeIDs = append(mistakeIDs, reportID)
	}
	if b["summary"] != nil || b["result"] != nil {
		_, err = db.Exec(ctx, `UPDATE crew_member_assessment SET summary=COALESCE($2,summary),result=COALESCE($3,result),updated_at=CASE WHEN ($2::text IS NOT NULL AND summary IS DISTINCT FROM $2) OR ($3::boolean IS NOT NULL AND result IS DISTINCT FROM $3) THEN now() ELSE updated_at END WHERE id=$1`, id, b["summary"], b["result"])
		if err != nil {
			return nil, err
		}
	}
	result := map[string]any{"assessmentId": id, "finalReportIds": finalIDs, "mistakeReportIds": mistakeIDs}
	if b["summary"] != nil {
		result["summary"] = b["summary"]
	}
	if b["result"] != nil {
		result["result"] = b["result"]
	}
	return result, nil
}

func maybeCompleteTraining(ctx context.Context, db runtimeDB, id int64) error {
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE training_session_id=$1`, id)
	if err != nil {
		return err
	}
	completed := len(rows) > 0
	for _, r := range rows {
		completed = completed && pythonTrim(r.text("summary")) != "" && r["result"] != nil
	}
	status := "IN_PROGRESS"
	if completed {
		status = "COMPLETED"
	}
	now := time.Now().UTC()
	_, err = db.Exec(ctx, `UPDATE training_session SET status=$2::text,completed_at=CASE WHEN $3 THEN COALESCE(completed_at,$4) ELSE NULL END,updated_at=CASE WHEN status IS DISTINCT FROM $2::text OR ($3 AND completed_at IS NULL) OR (NOT $3 AND completed_at IS NOT NULL) THEN now() ELSE updated_at END WHERE id=$1`, id, status, completed, now)
	return err
}

func (s *Service) finalizeInTransaction(ctx context.Context, db runtimeDB, training record, o platform.Object, user *auth.User, emitAudit bool) (map[string]any, error) {
	if err := validateCommentCompletion(o, training.number("comment_contract_version")); err != nil {
		return nil, err
	}
	if training.number("comment_contract_version") == 1 {
		for _, b := range finalizeBlocks(o) {
			for _, raw := range b["mistake_reports"].([]any) {
				r := raw.(platform.Object)
				r["comment"] = normalizeComment(r.String("comment"))
			}
		}
	}
	c, err := s.finalizeCatalog(ctx, db, training, user)
	if err != nil {
		return nil, err
	}
	exercises := map[int64]record{}
	needed := false
	for _, b := range finalizeBlocks(o) {
		needed = needed || len(b["mistake_reports"].([]any)) > 0
	}
	if needed {
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM training_session_exercise e WHERE training_session_id=$1`, training.number("id"))
		if err != nil {
			return nil, err
		}
		for _, r := range rows {
			exercises[r.number("runtime_exercise_id")] = r
		}
	}
	result := map[string]any{}
	for _, slot := range []string{"cm1", "cm2"} {
		if b, ok := o[slot].(platform.Object); ok {
			result[slot], err = finalizeOneBlock(ctx, db, training.number("id"), b, c, exercises)
			if err != nil {
				return nil, err
			}
			// Preserve the source record before the next block and before commit.
			// A later failure may roll back the data while retaining this audit.
			if emitAudit {
				platform.LogModule("app.audit", ctx).Info("Assessment finalized", "action", "assessment.finalize", "user_id", user.ID.String(), "assessment_id", b.Int("assessment_id"))
			}
		}
	}
	if err = maybeCompleteTraining(ctx, db, training.number("id")); err != nil {
		return nil, err
	}
	return result, nil
}

func (s *Service) finalizeAssessments(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	o, err := readAssessmentSchema(r, finalizeSchema)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	id, err := resolveFinalizeTraining(ctx, tx, o)
	if err != nil {
		return err
	}
	training, err := queryRecord(ctx, tx, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && training.text("status") == "DELETED" {
		return platform.Error(404, "Training not found")
	}
	if err != nil {
		return err
	}
	response, err := s.finalizeInTransaction(ctx, tx, training, o, user, true)
	if err != nil {
		return err
	}
	if err = persistSubmissionWithoutSpeech(ctx, tx, id, false); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, response)
	return nil
}
