package training

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"north55/backend/internal/telemetry"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/reportpdf"
)

var reportPreviewSchema = platform.Schema{Fields: []platform.Field{
	{Name: "comment_contract_version", Alias: "commentContractVersion", Kind: "literal_integer", Choices: []string{"1"}, Nullable: true},
	{Name: "unresolved_quick_comments", Alias: "unresolvedQuickComments", Kind: "list", Default: []any{}, Max: 1000, Item: &platform.Field{Kind: "object", Schema: &quickReferenceSchema}},
	{Name: "grades", Kind: "string_dictionary", Default: map[string]any{}},
	{Name: "mistake_reports", Alias: "mistakeReports", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &mistakeReportSchema}},
	{Name: "summary", Kind: "string", Nullable: true}, {Name: "result", Kind: "boolean", Nullable: true},
}}

func reportIDs(r *http.Request, fields ...platform.Field) (platform.Object, error) {
	raw := map[string]any{}
	for _, field := range fields {
		raw[field.Name] = r.PathValue(field.Name)
	}
	return platform.ValidateObject(raw, []any{"path"}, platform.Schema{Fields: fields})
}

func (s *Service) registerAssessmentReports(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix
	mux.HandleFunc("POST "+p+"/training/trainings/{training_id}/assessments/{assessment_id}/report-preview.pdf", platform.Wrap(s.previewAssessmentReport))
	// A final wildcard lets ServeMux rank the literal /signatures/ route above
	// this assessment route; the handler still accepts only report.pdf.
	mux.HandleOperationFunc("GET "+p+"/training/assessments/{assessment_id}/{report_file}", "GET "+p+"/training/assessments/{assessment_id}/report.pdf", platform.Wrap(s.storedAssessmentReport))
	mux.HandleFunc("GET "+p+"/commander/training-sessions/{training_session_id}/assessments/{assessment_id}/report.pdf", platform.Wrap(s.commanderAssessmentReport))
}

func (s *Service) reportInstructorTraining(r *http.Request, id, userID int64) (record, error) {
	row, err := queryRecord(r.Context(), s.Auth.DB, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && row.text("status") == "DELETED" {
		return nil, commanderError(404, "HTTP_404", "Training not found")
	}
	if err != nil {
		return nil, err
	}
	if row["instructor_id"] != nil && row.number("instructor_id") != userID {
		return nil, commanderError(403, "HTTP_403", "Training belongs to another instructor")
	}
	return row, nil
}

func readReportPreview(r *http.Request) (platform.Object, bool, error) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024*1024+1))
	if err != nil {
		return nil, false, err
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	value, err := platform.ReadSchema(r, reportPreviewSchema)
	if err != nil {
		return nil, false, err
	}
	var fields map[string]json.RawMessage
	if err = json.Unmarshal(raw, &fields); err != nil {
		return nil, false, err
	}
	_, camel := fields["unresolvedQuickComments"]
	_, snake := fields["unresolved_quick_comments"]
	return value, camel || snake, nil
}

func reportPreviewContract(preview platform.Object, proof bool, assessmentID, version int64) error {
	block := platform.Object{"assessment_id": assessmentID, "unresolved_quick_comments": preview["unresolved_quick_comments"], "mistake_reports": preview["mistake_reports"], "quick_proof_present": proof}
	value := platform.Object{"comment_contract_version": preview["comment_contract_version"], "cm1": block}
	if err := validateCommentCompletion(value, version); err != nil {
		return err
	}
	if version == 1 {
		for _, raw := range preview["mistake_reports"].([]any) {
			item := raw.(platform.Object)
			item["comment"] = normalizeComment(item.String("comment"))
		}
	}
	return nil
}

func writeAssessmentPDF(w http.ResponseWriter, report reportpdf.Report, auditUser *auth.User, source string, metrics *telemetry.Metrics, ctx context.Context) error {
	started := time.Now()
	content, err := reportpdf.Render(report)
	consumer := "commander"
	if auditUser != nil {
		consumer = "instructor"
	}
	status := "succeeded"
	if err != nil {
		status = "failed"
	}
	metrics.Inc("training_report_pdf_requests_total", source, consumer, status)
	metrics.Observe("training_report_pdf_render_duration_seconds", time.Since(started).Seconds(), source, consumer)
	if err == nil {
		metrics.Observe("training_report_pdf_bytes", float64(len(content)), source, consumer)
	}
	if err != nil {
		return err
	}
	if auditUser != nil {
		platform.LogModule("app.audit", ctx).Info("Assessment report PDF rendered", "action", "assessment.report_pdf", "user_id", auditUser.ID.String(), "training_id", report.TrainingID, "assessment_id", report.AssessmentID, "source", source)
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", `inline; filename="`+reportpdf.Filename(report)+`"`)
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("Content-Length", strconv.Itoa(len(content)))
	w.WriteHeader(http.StatusOK)
	_, err = w.Write(content)
	return err
}

func (s *Service) previewAssessmentReport(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	ids, err := reportIDs(r, platform.Field{Name: "training_id", Kind: "integer", Required: true}, platform.Field{Name: "assessment_id", Kind: "integer", Required: true})
	if err != nil {
		return err
	}
	preview, proof, err := readReportPreview(r)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tid, aid := ids.Int("training_id"), ids.Int("assessment_id")
	training, err := s.reportInstructorTraining(r, tid, user.InternalID)
	if err != nil {
		return err
	}
	if err = reportPreviewContract(preview, proof, aid, training.number("comment_contract_version")); err != nil {
		return err
	}
	report, err := s.buildAssessmentReport(r.Context(), &tid, aid, airline, preview)
	if err != nil {
		return err
	}
	return writeAssessmentPDF(w, report, user, "preview", s.Auth.Config.Metrics, r.Context())
}

func (s *Service) storedAssessmentReport(w http.ResponseWriter, r *http.Request) error {
	if r.PathValue("report_file") != "report.pdf" {
		platform.WriteJSON(w, 404, map[string]string{"detail": "Not Found"})
		return nil
	}
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	ids, err := reportIDs(r, platform.Field{Name: "assessment_id", Kind: "integer", Required: true})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aid := ids.Int("assessment_id")
	assessment, err := queryRecord(r.Context(), s.Auth.DB, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE id=$1`, aid)
	if errors.Is(err, pgx.ErrNoRows) {
		return commanderError(404, "ASSESSMENT_NOT_FOUND", "Assessment not found")
	}
	if err != nil {
		return err
	}
	if _, err = s.reportInstructorTraining(r, assessment.number("training_session_id"), user.InternalID); err != nil {
		return err
	}
	report, err := s.buildAssessmentReport(r.Context(), nil, aid, airline, nil)
	if err != nil {
		return err
	}
	return writeAssessmentPDF(w, report, user, "stored", s.Auth.Config.Metrics, r.Context())
}

func (s *Service) commanderAssessmentReport(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	ids, err := reportIDs(r, platform.Field{Name: "training_session_id", Kind: "integer", Min: 1, Required: true}, platform.Field{Name: "assessment_id", Kind: "integer", Min: 1, Required: true})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tid := ids.Int("training_session_id")
	report, err := s.buildAssessmentReport(r.Context(), &tid, ids.Int("assessment_id"), airline, nil)
	if err != nil {
		return err
	}
	return writeAssessmentPDF(w, report, nil, "stored", s.Auth.Config.Metrics, r.Context())
}
