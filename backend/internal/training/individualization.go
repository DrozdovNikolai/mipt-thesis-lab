package training

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
)

type competenceRanks map[int64]int64

func latestPilotRanks(ctx context.Context, db runtimeDB, userID int64) (competenceRanks, error) {
	var assessment int64
	err := db.QueryRow(ctx, `SELECT a.id FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id WHERE a.user_id=$1 AND t.status='COMPLETED' ORDER BY t.completed_at DESC NULLS LAST,t.updated_at DESC,t.created_at DESC,t.id DESC,a.id DESC LIMIT 1`, userID).Scan(&assessment)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT competence_id FROM final_report WHERE assessment_id=$1 ORDER BY grade_score_snapshot ASC NULLS LAST,competence_id,id`, assessment)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := competenceRanks{}
	index := int64(0)
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		if _, ok := out[id]; !ok {
			out[id] = index
		}
		index++
	}
	if len(out) == 0 {
		out = nil
	}
	return out, rows.Err()
}
func positionCohortRanks(ctx context.Context, db runtimeDB, airline, position int64) (competenceRanks, error) {
	rows, err := db.Query(ctx, `WITH latest AS (
 SELECT a.id, row_number() OVER (PARTITION BY a.user_id ORDER BY t.completed_at DESC NULLS LAST,t.updated_at DESC,t.created_at DESC,t.id DESC,a.id DESC) rn
 FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id JOIN users u ON u.id=a.user_id JOIN user_info p ON p.id=u.id
 WHERE u.airline_id=$1 AND p.position_id=$2 AND t.status='COMPLETED' AND EXISTS(SELECT 1 FROM final_report f WHERE f.assessment_id=a.id)
 ), reports AS (
 SELECT f.assessment_id,f.competence_id,f.grade_score_snapshot,row_number() OVER (PARTITION BY f.assessment_id,f.competence_id ORDER BY f.updated_at DESC,f.created_at DESC,f.id DESC) rn
 FROM final_report f JOIN latest l ON l.id=f.assessment_id AND l.rn=1
 ), ranks AS (
 SELECT assessment_id,competence_id,row_number() OVER (PARTITION BY assessment_id ORDER BY grade_score_snapshot ASC NULLS LAST,competence_id) rank
 FROM reports WHERE rn=1 AND grade_score_snapshot IS NOT NULL
 ) SELECT competence_id FROM ranks GROUP BY competence_id ORDER BY avg(rank),count(DISTINCT assessment_id) DESC,competence_id`, airline, position)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := competenceRanks{}
	var index int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = index
		index++
	}
	if len(out) == 0 {
		out = nil
	}
	return out, rows.Err()
}
func blockCompetenceScore(block *sourceExercise, ranks competenceRanks) (present, best, sum, count int64) {
	best = 1000000
	seen := map[int64]bool{}
	for _, competence := range block.Competences {
		id := competence.number("id")
		if seen[id] {
			continue
		}
		seen[id] = true
		if rank, ok := ranks[id]; ok {
			best = min(best, rank)
			sum += rank
			count++
		}
	}
	if count == 0 {
		return 1, 1000000, 1000000, 0
	}
	return 0, best, sum, -count
}
func selectIndividualBlock(duration int64, blocks []*sourceExercise, personal, cohort competenceRanks, used map[int64]bool) *sourceExercise {
	var selected *sourceExercise
	var minimum [12]int64
	for _, block := range blocks {
		if len(block.Competences) == 0 {
			continue
		}
		bucket, diff := int64(4), int64(10000)
		if block.Param["duration_minutes"] != nil {
			diff = block.Param.number("duration_minutes") - duration
			if diff < 0 {
				diff = -diff
			}
			switch {
			case diff == 0:
				bucket = 0
			case diff <= 5:
				bucket = 1
			case diff <= 10:
				bucket = 2
			default:
				bucket = 3
			}
		}
		a, b, c, d := blockCompetenceScore(block, personal)
		e, f, g, h := blockCompetenceScore(block, cohort)
		reused := int64(0)
		if used[block.Row.number("id")] {
			reused = 1
		}
		key := [12]int64{bucket, diff, reused, a, b, c, d, e, f, g, h, block.Row.number("id")}
		less := selected == nil
		if selected != nil {
			for i, v := range key {
				if v != minimum[i] {
					less = v < minimum[i]
					break
				}
			}
		}
		if less {
			selected = block
			minimum = key
		}
	}
	return selected
}
func resolveIndividualExercises(ctx context.Context, db runtimeDB, s sourceScenario, day, cm1, cm2 int64) (map[int64]*sourceExercise, error) {
	out := map[int64]*sourceExercise{}
	placeholders := []*sourceExercise{}
	required := map[int64]bool{}
	users := map[int64]int64{1: cm1, 2: cm2}
	for _, module := range s.dayModules(day) {
		for _, e := range module.Exercises {
			if e.Row.text("kind") == "individual" {
				placeholders = append(placeholders, e)
				if id := users[e.Row.number("crew_member_number")]; id != 0 {
					required[id] = true
				}
			}
		}
	}
	if len(placeholders) == 0 {
		return out, nil
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(b) FROM element_block b WHERE b.airline_id=$1 AND b.archived_at IS NULL ORDER BY id`, s.Row.number("airline_id"))
	if err != nil {
		return nil, err
	}
	blocks := []*sourceExercise{}
	for _, row := range rows {
		blocks = append(blocks, &sourceExercise{Row: row})
	}
	if err = loadExerciseAssets(ctx, db, blocks, true); err != nil {
		return nil, err
	}
	valid := []*sourceExercise{}
	for _, b := range blocks {
		okay := len(b.Elements) > 0
		for _, e := range b.Elements {
			element := e.object("element")
			if element == nil || element["archived_at"] != nil || element.number("aircraft_id") != s.Row.number("aircraft_id") {
				okay = false
				break
			}
		}
		if okay {
			valid = append(valid, b)
		}
	}
	personal, cohort := map[int64]competenceRanks{}, map[int64]competenceRanks{}
	positions := map[int64]*int64{}
	cohortByPosition := map[int64]competenceRanks{}
	for id := range required {
		personal[id], err = latestPilotRanks(ctx, db, id)
		if err != nil {
			return nil, err
		}
		var position *int64
		err = db.QueryRow(ctx, `SELECT p.position_id FROM users u LEFT JOIN user_info p ON p.id=u.id WHERE u.id=$1`, id).Scan(&position)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
		positions[id] = position
		if position != nil {
			value, exists := cohortByPosition[*position]
			if !exists {
				value, err = positionCohortRanks(ctx, db, s.Row.number("airline_id"), *position)
				if err != nil {
					return nil, err
				}
				cohortByPosition[*position] = value
			}
			cohort[id] = value
		}
	}
	used := map[int64]bool{}
	for _, e := range placeholders {
		user := users[e.Row.number("crew_member_number")]
		if user == 0 || e.Row["duration_minutes"] == nil || personal[user] == nil && cohort[user] == nil {
			continue
		}
		block := selectIndividualBlock(e.Row.number("duration_minutes"), valid, personal[user], cohort[user], used)
		if block != nil {
			out[e.Row.number("id")] = block
			used[block.Row.number("id")] = true
		}
	}
	return out, nil
}
