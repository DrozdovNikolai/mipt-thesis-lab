package training

import (
	"context"
	"errors"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
	"north55/backend/internal/reportpdf"
)

type reportCommentRow struct {
	value reportpdf.Comment
	stamp time.Time
}

func (s *Service) reportComments(ctx context.Context, training record, airline int64, preview platform.Object, indicators map[int64]record, assessmentID int64) ([]reportpdf.Comment, error) {
	items := []reportCommentRow{}
	if preview != nil {
		competences, err := s.reportCompetencesForComments(ctx, training, airline)
		if err != nil {
			return nil, err
		}
		if indicators == nil {
			indicators = map[int64]record{}
		}
		if training.number("comment_contract_version") != 1 {
			ids := []int64{}
			for _, raw := range preview["mistake_reports"].([]any) {
				r := raw.(platform.Object)
				if r["bi_id"] != nil {
					ids = append(ids, r.Int("bi_id"))
				}
			}
			if len(ids) > 0 {
				rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(i) FROM behavioural_indicator i WHERE id=ANY($1)`, ids)
				if err != nil {
					return nil, err
				}
				for _, row := range rows {
					indicators[row.number("id")] = row
				}
			}
		}
		for _, raw := range preview["mistake_reports"].([]any) {
			r := raw.(platform.Object)
			indicator := indicators[r.Int("bi_id")]
			value := reportpdf.Comment{CompetenceCode: competences[r.Int("comp_id")].text("code"), Positive: r.Bool("is_positive"), IndicatorCode: indicator.text("code"), IndicatorName: reportText(indicator.text("name"), indicator.text("short_name"), indicator.text("code")), Text: r.String("comment")}
			items = append(items, reportCommentRow{value: value, stamp: r["timestamp"].(time.Time)})
		}
	} else {
		rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM (
SELECT m.*,c.code AS current_competence_code,b.code AS current_indicator_code,
b.name AS current_indicator_name,b.short_name AS current_indicator_short_name
FROM mistake_report m LEFT JOIN competence c ON c.id=m.competence_id
LEFT JOIN behavioural_indicator b ON b.id=m.behavioural_indicator_id WHERE m.assessment_id=$1) r`, assessmentID)
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			value := reportpdf.Comment{CompetenceCode: reportText(row.text("competence_code_snapshot"), row.text("current_competence_code")), Positive: row["is_positive"] == true, IndicatorCode: reportText(row.text("behavioural_indicator_code_snapshot"), row.text("current_indicator_code")), IndicatorName: reportText(row.text("behavioural_indicator_name_snapshot"), row.text("current_indicator_name"), row.text("current_indicator_short_name"), row.text("current_indicator_code")), Text: row.text("comment")}
			stamp := time.Time{}
			if parsed := reportTime(row["timestamp"]); parsed != nil {
				stamp = *parsed
			}
			items = append(items, reportCommentRow{value: value, stamp: stamp})
		}
	}
	sort.SliceStable(items, func(i, j int) bool {
		if !items[i].stamp.Equal(items[j].stamp) {
			return items[i].stamp.Before(items[j].stamp)
		}
		if items[i].value.CompetenceCode != items[j].value.CompetenceCode {
			return items[i].value.CompetenceCode < items[j].value.CompetenceCode
		}
		return items[i].value.Text < items[j].value.Text
	})
	result := make([]reportpdf.Comment, 0, len(items))
	for _, item := range items {
		result = append(result, item.value)
	}
	return result, nil
}

func (s *Service) reportCompetencesForComments(ctx context.Context, training record, airline int64) (map[int64]record, error) {
	rows, _, err := s.reportCompetences(ctx, training, airline)
	if err != nil {
		return nil, err
	}
	result := map[int64]record{}
	for _, row := range rows {
		result[row.number("id")] = row
	}
	return result, nil
}

func (s *Service) buildAssessmentReport(ctx context.Context, trainingID *int64, assessmentID, airline int64, preview platform.Object) (reportpdf.Report, error) {
	out := reportpdf.Report{}
	assessment, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE id=$1`, assessmentID)
	if errors.Is(err, pgx.ErrNoRows) {
		return out, commanderError(404, "ASSESSMENT_NOT_FOUND", "Assessment not found")
	}
	if err != nil {
		return out, err
	}
	training, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1`, assessment.number("training_session_id"))
	if errors.Is(err, pgx.ErrNoRows) {
		return out, commanderError(404, "TRAINING_SESSION_NOT_FOUND", "Training session not found")
	}
	if err != nil {
		return out, err
	}
	if trainingID != nil && training.number("id") != *trainingID {
		return out, commanderError(404, "ASSESSMENT_NOT_FOUND", "Assessment not found in training session")
	}
	scheme, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(g) FROM grading_scheme g WHERE id=$1`, training.number("grading_scheme_id"))
	if errors.Is(err, pgx.ErrNoRows) || err == nil && scheme.number("airline_id") != airline {
		return out, commanderError(403, "HTTP_403", "Insufficient privileges")
	}
	if err != nil {
		return out, err
	}
	competences, indicators, err := s.reportCompetences(ctx, training, airline)
	if err != nil {
		return out, err
	}
	aircraft := training.text("aircraft_code_snapshot")
	out.TrainingID, out.AssessmentID, out.Role = training.number("id"), assessmentID, assessment.text("training_role")
	out.Title, out.CompletedAt, out.GeneratedAt, out.AircraftCode = reportTitle(training), reportTime(training["completed_at"]), time.Now().UTC(), aircraft
	out.Trainee, err = s.reportPerson(ctx, assessment["user_id"], aircraft, assessment.text("signature_storage_path"))
	if err != nil {
		return out, err
	}
	out.Instructor, err = s.reportPerson(ctx, training["instructor_id"], aircraft, "")
	if err != nil {
		return out, err
	}
	out.Durations, err = s.reportDurations(ctx, training, assessment)
	if err != nil {
		return out, err
	}
	out.LatestSwap, err = s.reportLatestSwap(ctx, training)
	if err != nil {
		return out, err
	}
	var previewGrades map[string]any
	if preview != nil {
		previewGrades = preview["grades"].(map[string]any)
	}
	out.Grades, err = s.reportGrades(ctx, training, assessment, competences, previewGrades)
	if err != nil {
		return out, err
	}
	out.Comments, err = s.reportComments(ctx, training, airline, preview, indicators, assessmentID)
	if err != nil {
		return out, err
	}
	if preview == nil {
		out.Summary = assessment.text("summary")
		if value, ok := assessment["result"].(bool); ok {
			out.Result = &value
		}
	} else {
		out.Summary = preview.String("summary")
		if value, ok := preview["result"].(bool); ok {
			out.Result = &value
		}
	}
	return out, nil
}
