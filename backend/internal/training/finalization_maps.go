package training

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

type assessmentCatalog struct {
	Codes                   map[string]int64
	Competences, Indicators map[int64]record
	Grades                  map[string]record
}

func assessmentUpper(value string) string { return cases.Upper(language.Und).String(value) }
func (s *Service) finalizeCatalog(ctx context.Context, db runtimeDB, training record, user *auth.User) (assessmentCatalog, error) {
	c := assessmentCatalog{Codes: map[string]int64{}, Competences: map[int64]record{}, Indicators: map[int64]record{}, Grades: map[string]record{}}
	if user.AirlineID == nil {
		return c, platform.Error(400, "User is not assigned to an airline")
	}
	contract := training.number("comment_contract_version")
	if contract == 1 {
		if err := validateDraftCatalog(training); err != nil {
			return c, err
		}
		for _, raw := range training.object("evaluation_catalog_snapshot")["competencies"].([]any) {
			v := jsonMap(raw)
			id, _ := draftInteger(v["id"], "", true)
			order := int64(0)
			if jsonTruthy(v["orderIndex"]) {
				if n, ok := jsonNumeric(v["orderIndex"]); ok {
					order = n.Num().Quo(n.Num(), n.Denom()).Int64()
				} else {
					order, _ = draftInteger(v["orderIndex"], "", false)
				}
			}
			r := record{"code": assessmentUpper(pythonTrim(jsonText(v["code"]))), "name": pythonTrim(jsonText(v["name"])), "order_index": order}
			c.Competences[id] = r
			c.Codes[r.text("code")] = id
			for _, raw := range v["indicators"].([]any) {
				v := jsonMap(raw)
				indicatorID, _ := draftInteger(v["id"], "", true)
				var short any
				if v["shortName"] != nil {
					short = pythonTrim(pythonString(v["shortName"]))
				}
				c.Indicators[indicatorID] = record{"competence_id": id, "code": pythonTrim(jsonText(v["code"])), "short_name": short, "name": pythonTrim(jsonText(v["name"]))}
			}
		}
		ids := []int64{}
		for id := range c.Competences {
			ids = append(ids, id)
		}
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND id=ANY($2)`, *user.AirlineID, ids)
		if err != nil {
			return c, err
		}
		if len(rows) != len(c.Competences) {
			return c, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
		}
		ids = []int64{}
		for id := range c.Indicators {
			ids = append(ids, id)
		}
		rows, err = queryRecords(ctx, db, `SELECT to_jsonb(i) FROM behavioural_indicator i JOIN competence c ON c.id=i.competence_id WHERE c.airline_id=$1 AND i.id=ANY($2)`, *user.AirlineID, ids)
		if err != nil {
			return c, err
		}
		if len(rows) != len(c.Indicators) {
			return c, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
		}
		for _, r := range rows {
			if r.number("competence_id") != c.Indicators[r.number("id")].number("competence_id") {
				return c, draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil)
			}
		}
	} else {
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND retired_at IS NULL`, *user.AirlineID)
		if err != nil {
			return c, err
		}
		for _, r := range rows {
			r["code"] = assessmentUpper(r.text("code"))
			c.Codes[r.text("code")] = r.number("id")
			c.Competences[r.number("id")] = r
		}
	}
	scheme, err := queryRecord(ctx, db, `SELECT to_jsonb(s) FROM grading_scheme s WHERE id=$1`, training.number("grading_scheme_id"))
	if errors.Is(err, pgx.ErrNoRows) {
		return c, platform.Error(400, "Training grading scheme not found")
	}
	if err != nil {
		return c, err
	}
	if scheme.number("airline_id") != *user.AirlineID {
		return c, platform.Error(403, "Training belongs to a different airline")
	}
	grades, err := queryRecords(ctx, db, `SELECT to_jsonb(g) || jsonb_build_object('score_numeric',score_numeric::text,'grade_weight',grade_weight::text) FROM grading_scale_value g WHERE grading_scheme_id=$1`, scheme.number("id"))
	if err != nil {
		return c, err
	}
	for _, r := range grades {
		code := assessmentUpper(pythonTrim(r.text("code")))
		if code != "" {
			c.Grades[code] = r
		}
	}
	if len(c.Grades) == 0 {
		return c, platform.Error(400, "Training grading scheme has no grade values")
	}
	if contract == 0 && len(c.Competences) > 0 {
		ids := []int64{}
		for id := range c.Competences {
			ids = append(ids, id)
		}
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(i) FROM behavioural_indicator i WHERE competence_id=ANY($1) AND retired_at IS NULL`, ids)
		if err != nil {
			return c, err
		}
		for _, r := range rows {
			r["code"] = r.text("code")
			r["name"] = r.text("name")
			c.Indicators[r.number("id")] = r
		}
	}
	return c, nil
}
func helperPositive(code string) bool {
	return cases.Lower(language.Und).String(pythonTrim(code)) == "positive"
}
