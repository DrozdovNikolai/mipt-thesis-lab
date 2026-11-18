package training

import (
	"context"
	"fmt"
	"sort"
	"time"
)

// Each view has a different assessment partition. Reports are still deduplicated
// independently per assessment/competence after selecting the relevant sessions.
func commanderAnalyticsCTE(kind string) string {
	effective := "coalesce(t.completed_at,t.updated_at,t.created_at)"
	year, half := "NULL::integer", "NULL::integer"
	owner, partition, filter, join := "a.user_id", "a.user_id", "a.user_id=ANY($2::bigint[])", ""
	if kind == "trend" {
		year = "extract(year FROM " + effective + ")::integer"
		half = "CASE WHEN extract(month FROM " + effective + ")<=6 THEN 1 ELSE 2 END"
		partition += "," + year + "," + half
	}
	if kind == "instructors" {
		owner = "t.instructor_id"
		partition = "t.instructor_id,a.user_id"
		join = " JOIN users p ON p.id=a.user_id "
		filter = "t.instructor_id=ANY($2::bigint[]) AND p.airline_id=$1 AND ($4::uuid IS NULL OR p.public_id=$4)"
	}
	return `WITH assessment_ranked AS (SELECT ` + owner + ` AS owner_id,a.user_id AS pilot_id,a.id AS assessment_id,` + year + ` AS bucket_year,` + half + ` AS bucket_half,
 row_number() OVER(PARTITION BY ` + partition + ` ORDER BY ` + effective + ` DESC,a.created_at DESC,a.id DESC) AS rank
 FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id ` + join + `
 WHERE ` + filter + ` AND t.status='COMPLETED' AND ($3::timestamptz IS NULL OR ` + effective + `<$3)),
 latest_assessments AS (SELECT owner_id,pilot_id,assessment_id,bucket_year,bucket_half FROM assessment_ranked WHERE rank=1),
 report_ranked AS (SELECT a.owner_id,a.pilot_id,a.bucket_year,a.bucket_half,f.assessment_id,f.competence_id,
 coalesce(f.grade_code_snapshot,f.grade) AS grade_code,f.grade_label_snapshot AS grade_label,
 f.grade_score_snapshot AS score,f.grade_color_hex_snapshot AS grade_color_hex,
 row_number() OVER(PARTITION BY f.assessment_id,f.competence_id ORDER BY f.updated_at DESC,f.created_at DESC,f.id DESC) AS rank
 FROM latest_assessments a JOIN final_report f ON f.assessment_id=a.assessment_id
 JOIN competence c ON c.id=f.competence_id WHERE c.airline_id=$1),
 latest_reports AS (SELECT * FROM report_ranked WHERE rank=1) `
}

func commanderAnalyticsScale(ctx context.Context, db runtimeDB, airline int64) ([]string, map[string]record, error) {
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(r) FROM (SELECT v.code AS grade_code,v.label AS grade_label,v.score_numeric::text AS grade_score_numeric,v.color_hex AS grade_color_hex
 FROM grading_scale_value v WHERE v.grading_scheme_id=(SELECT id FROM grading_scheme WHERE airline_id=$1 AND is_active ORDER BY version DESC,id DESC LIMIT 1)
 ORDER BY v.order_index,v.id) r`, airline)
	if err != nil {
		return nil, nil, err
	}
	order := []string{}
	meta := map[string]record{}
	for _, row := range rows {
		code := row.text("grade_code")
		order = append(order, code)
		meta[code] = row.project("grade_label grade_score_numeric grade_color_hex")
	}
	return order, meta, nil
}

func commanderAnalyticsDistribution(ctx context.Context, db runtimeDB, a commanderAnalytics, completed map[int64]bool) ([]record, error) {
	order, meta, err := commanderAnalyticsScale(ctx, db, a.airline)
	if err != nil {
		return nil, err
	}
	subject := "owner_id"
	if a.kind == "competencies" {
		subject = "competence_id"
	}
	aggregates, err := queryRecords(ctx, db, a.cte+`SELECT to_jsonb(r) FROM (SELECT `+subject+` AS subject_id,grade_code,grade_label,
 score::text AS grade_score_numeric,grade_color_hex,count(*) AS amount FROM latest_reports
 GROUP BY `+subject+`,grade_code,grade_label,score,grade_color_hex) r`, a.args...)
	if err != nil {
		return nil, err
	}
	counts := map[int64]map[string]int64{}
	for _, row := range aggregates {
		id, code := row.number("subject_id"), row.text("grade_code")
		if counts[id] == nil {
			counts[id] = map[string]int64{}
		}
		counts[id][code] += row.number("amount")
		// Active scale metadata wins. For previously unseen codes the reference
		// takes the first aggregate row, independent of which competence uses it.
		if meta[code] == nil {
			meta[code] = row.project("grade_label grade_score_numeric grade_color_hex")
		}
	}
	subjects := []record{}
	countKey, totalKey := "grade_count", "assessed_grade_count"
	if a.kind == "competencies" {
		subjects, err = commanderAnalyticsCompetences(ctx, db, a.airline)
		if err != nil {
			return nil, err
		}
		countKey, totalKey = "pilot_count", "assessed_pilot_count"
	} else {
		name := "pilot_id"
		if a.kind == "instructors" {
			name = "instructor_id"
		}
		for _, user := range a.users {
			if !completed[user.number("id")] {
				continue
			}
			subjects = append(subjects, record{"subject_id": user["id"], name: user["public_id"], "first_name": user["first_name"], "last_name": user["last_name"]})
		}
	}
	for _, item := range subjects {
		id := item.number("subject_id")
		if a.kind == "competencies" {
			id = item.number("competence_id")
		}
		delete(item, "subject_id")
		codes := append([]string{}, order...)
		known := map[string]bool{}
		for _, code := range codes {
			known[code] = true
		}
		extra := []string{}
		for code := range counts[id] {
			if !known[code] {
				extra = append(extra, code)
			}
		}
		sort.Strings(extra)
		codes = append(codes, extra...)
		grades := []record{}
		var total int64
		for _, code := range codes {
			value := meta[code].project("grade_label grade_score_numeric grade_color_hex")
			value["grade_code"], value[countKey] = code, counts[id][code]
			grades = append(grades, value)
			total += counts[id][code]
		}
		item[totalKey], item["grades"] = total, grades
	}
	return subjects, nil
}

func commanderAnalyticsTrend(ctx context.Context, db runtimeDB, a commanderAnalytics) ([]record, error) {
	aggregates, err := queryRecords(ctx, db, a.cte+`SELECT to_jsonb(r) FROM (
 SELECT bucket_year,bucket_half,competence_id,avg(score)::text AS average_score_numeric,count(*) AS pilot_count FROM latest_reports
 WHERE score IS NOT NULL GROUP BY bucket_year,bucket_half,competence_id ORDER BY bucket_year,bucket_half,competence_id) r`, a.args...)
	if err != nil {
		return nil, err
	}
	points := map[int64][]record{}
	for _, row := range aggregates {
		year, half := int(row.number("bucket_year")), int(row.number("bucket_half"))
		month := time.January
		if half == 2 {
			month = time.July
		}
		start := time.Date(year, month, 1, 0, 0, 0, 0, time.UTC)
		end := start.AddDate(0, 6, -1)
		point := row.project("average_score_numeric pilot_count")
		point["period_start"], point["period_end"], point["period_label"] = start.Format("2006-01-02"), end.Format("2006-01-02"), fmt.Sprintf("H%d %d", half, year)
		id := row.number("competence_id")
		points[id] = append(points[id], point)
	}
	items, err := commanderAnalyticsCompetences(ctx, db, a.airline)
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		value := points[item.number("competence_id")]
		if value == nil {
			value = []record{}
		}
		item["points"] = value
	}
	return items, nil
}
