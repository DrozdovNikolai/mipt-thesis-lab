package training

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/reportpdf"
)

func reportTime(value any) *time.Time {
	raw, ok := value.(string)
	if !ok || raw == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return nil
	}
	return &t
}

func reportText(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func reportTitle(training record) string {
	scenario := pythonTrim(training.text("scenario_title_snapshot"))
	day, count := training["day_index_snapshot"], training["days_count_snapshot"]
	if scenario != "" && day != nil && count != nil {
		return fmt.Sprintf("%s / Day %d of %d", scenario, training.number("day_index_snapshot"), training.number("days_count_snapshot"))
	}
	if scenario != "" && day != nil {
		return fmt.Sprintf("%s / Day %d", scenario, training.number("day_index_snapshot"))
	}
	if scenario != "" {
		return scenario
	}
	return fmt.Sprintf("Training Session %d", training.number("id"))
}

func (s *Service) reportPerson(ctx context.Context, userID any, aircraftCode, signaturePath string) (reportpdf.Person, error) {
	person := reportpdf.Person{AircraftType: aircraftCode}
	if userID != nil {
		row, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM (
SELECT u.login,u.email,i.first_name,i.last_name,i.license_number,p.name AS position_name,
i.signature_storage_path FROM users u LEFT JOIN user_info i ON i.id=u.id
LEFT JOIN airline_position p ON p.id=i.position_id WHERE u.id=$1) r`, userID)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return person, err
		}
		if err == nil {
			person.Name = strings.TrimSpace(strings.Join([]string{pythonTrim(row.text("first_name")), pythonTrim(row.text("last_name"))}, " "))
			if person.Name == "" {
				person.Name = reportText(row.text("login"), row.text("email"))
			}
			person.License = pythonTrim(row.text("license_number"))
			person.Position = pythonTrim(row.text("position_name"))
			if signaturePath == "" {
				signaturePath = row.text("signature_storage_path")
			}
		}
	}
	if signaturePath != "" {
		stream, err := s.Storage.Open(ctx, filestorage.Media, signaturePath)
		if err == nil {
			defer stream.Close()
			person.Signature, err = io.ReadAll(io.LimitReader(stream, 10<<20))
			if err != nil {
				return person, err
			}
		} else if !errors.Is(err, filestorage.ErrNotFound) && !errors.Is(err, filestorage.ErrInvalidPath) {
			return person, err
		}
	}
	return person, nil
}

func (s *Service) reportCompetences(ctx context.Context, training record, airline int64) ([]record, map[int64]record, error) {
	if training.number("comment_contract_version") != 1 {
		rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 ORDER BY order_index,id`, airline)
		return rows, nil, err
	}
	if err := validateDraftCatalog(training); err != nil {
		return nil, nil, err
	}
	catalog := training.object("evaluation_catalog_snapshot")
	competences, indicators := []record{}, map[int64]record{}
	for _, raw := range catalog["competencies"].([]any) {
		item := record(jsonMap(raw))
		id, _ := draftInteger(item["id"], "", true)
		order, _ := draftInteger(item["orderIndex"], "", false)
		competences = append(competences, record{"id": id, "code": item["code"], "name": item["name"], "order_index": order})
		for _, child := range item["indicators"].([]any) {
			indicator := record(jsonMap(child))
			indicatorID, _ := draftInteger(indicator["id"], "", true)
			indicators[indicatorID] = record{"id": indicatorID, "competence_id": id, "code": indicator["code"], "name": indicator["name"], "short_name": indicator["shortName"]}
		}
	}
	sort.SliceStable(competences, func(i, j int) bool {
		if competences[i].number("order_index") != competences[j].number("order_index") {
			return competences[i].number("order_index") < competences[j].number("order_index")
		}
		return competences[i].number("id") < competences[j].number("id")
	})
	ids := []int64{}
	for _, row := range competences {
		ids = append(ids, row.number("id"))
	}
	actual, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND id=ANY($2)`, airline, ids)
	if err != nil {
		return nil, nil, err
	}
	if len(actual) != len(competences) {
		return nil, nil, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
	}
	ids = ids[:0]
	for id := range indicators {
		ids = append(ids, id)
	}
	actual, err = queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(i) FROM behavioural_indicator i JOIN competence c ON c.id=i.competence_id WHERE c.airline_id=$1 AND i.id=ANY($2)`, airline, ids)
	if err != nil {
		return nil, nil, err
	}
	if len(actual) != len(indicators) {
		return nil, nil, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
	}
	for _, row := range actual {
		if row.number("competence_id") != indicators[row.number("id")].number("competence_id") {
			return nil, nil, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
		}
	}
	return competences, indicators, nil
}

func (s *Service) reportGrades(ctx context.Context, training, assessment record, competences []record, preview map[string]any) ([]reportpdf.Grade, error) {
	values, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(v) FROM grading_scale_value v WHERE grading_scheme_id=$1`, training.number("grading_scheme_id"))
	if err != nil {
		return nil, err
	}
	byCode := map[string]record{}
	for _, value := range values {
		code := assessmentUpper(pythonTrim(value.text("code")))
		if code != "" {
			byCode[code] = value
		}
	}
	stored := map[int64]record{}
	if preview == nil {
		rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(f) FROM (SELECT DISTINCT ON (competence_id) * FROM final_report WHERE assessment_id=$1 ORDER BY competence_id,COALESCE(updated_at,created_at) DESC,created_at DESC,id DESC) f`, assessment.number("id"))
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			stored[row.number("competence_id")] = row
		}
	}
	normalized := map[string]string{}
	for code, value := range preview {
		str, _ := value.(string)
		normalized[assessmentUpper(pythonTrim(code))] = assessmentUpper(pythonTrim(str))
	}
	grades := []reportpdf.Grade{}
	for _, c := range competences {
		grade := reportpdf.Grade{ID: c.number("id"), Code: c.text("code"), Name: c.text("name"), OrderIndex: c.number("order_index")}
		if report, ok := stored[grade.ID]; ok {
			grade.Code = reportText(report.text("competence_code_snapshot"), grade.Code)
			grade.Name = reportText(report.text("competence_name_snapshot"), grade.Name)
			if report["competence_order_index_snapshot"] != nil {
				grade.OrderIndex = report.number("competence_order_index_snapshot")
			}
			grade.Label = reportText(report.text("grade_label_snapshot"), report.text("grade_code_snapshot"), report.text("grade"))
			grade.ColorHex = report.text("grade_color_hex_snapshot")
		} else {
			code := normalized[assessmentUpper(pythonTrim(grade.Code))]
			grade.Label = code
			if value, ok := byCode[code]; ok {
				grade.Label = value.text("label")
				grade.ColorHex = value.text("color_hex")
			}
		}
		grades = append(grades, grade)
	}
	return grades, nil
}

func (s *Service) reportDurations(ctx context.Context, training, assessment record) (reportpdf.Durations, error) {
	state, err := queryRecord(ctx, s.Auth.DB, `SELECT to_jsonb(s) FROM training_session_crew_state s WHERE training_session_id=$1`, training.number("id"))
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return reportpdf.Durations{}, err
	}
	if err == nil && state.number("capability_version") >= 1 {
		return s.reportTimelineDurations(ctx, training, assessment, state)
	}
	rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(e) FROM training_session_exercise e JOIN training_session_module m ON m.id=e.training_session_module_id WHERE e.training_session_id=$1 ORDER BY m.order_index,m.id,e.order_index,e.id`, training.number("id"))
	if err != nil {
		return reportpdf.Durations{}, err
	}
	selected := int64(0)
	if assessment.text("training_role") == "cm1" {
		selected = 1
	} else if assessment.text("training_role") == "cm2" {
		selected = 2
	}
	out := reportpdf.Durations{Source: "LEGACY_PLANNED"}
	for _, row := range rows {
		ms := row.number("duration_minutes") * 60_000
		crew := row.number("crew_member_number")
		if ms <= 0 || crew != 1 && crew != 2 {
			continue
		}
		if crew == selected {
			out.PFMs += ms
		} else {
			out.PMMs += ms
		}
	}
	return out, nil
}
