package training

import (
	"context"
	"time"
)

// New submissions follow the assessment workflow. Validation errors roll back the transaction.
func submissionWithoutSpeech(t record) string {
	status := t.text("submission_status")
	if status == "" {
		status = "DRAFT"
	}
	if t["submitted_at"] == nil && status == "DRAFT" {
		return "DRAFT"
	}
	if t.text("status") != "COMPLETED" {
		return "WAITING_ASSESSMENTS"
	}
	return "COMPLETED"
}
func persistSubmissionWithoutSpeech(ctx context.Context, db runtimeDB, id int64, markSubmitted bool) error {
	t, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if err != nil {
		return err
	}
	var submitted any = t["submitted_at"]
	if markSubmitted && submitted == nil {
		submitted = time.Now().UTC()
		t["submitted_at"] = submitted
	}
	if raw, ok := submitted.(string); ok {
		submitted, err = time.Parse(time.RFC3339Nano, raw)
		if err != nil {
			return err
		}
	}
	status := submissionWithoutSpeech(t)
	_, err = db.Exec(ctx, `UPDATE training_session SET submission_status=$2::text,submission_error=NULL,submitted_at=$3,completed_at=CASE WHEN $2::text='COMPLETED' THEN COALESCE(completed_at,$4) WHEN status<>'COMPLETED' THEN NULL ELSE completed_at END,updated_at=CASE WHEN submission_status IS DISTINCT FROM $2::text OR submission_error IS NOT NULL OR submitted_at IS DISTINCT FROM $3 OR ($2::text='COMPLETED' AND completed_at IS NULL) OR (status<>'COMPLETED' AND completed_at IS NOT NULL) THEN now() ELSE updated_at END WHERE id=$1`, id, status, submitted, time.Now().UTC())
	return err
}
