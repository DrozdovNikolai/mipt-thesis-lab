package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func commanderError(status int, code, message string) error {
	return &platform.APIError{Status: status, Code: code, Message: message}
}
func commanderAirline(user *auth.User) (int64, error) {
	if user.AirlineID == nil || *user.AirlineID <= 0 {
		return 0, commanderError(400, "AIRLINE_REQUIRED", "User is not assigned to an airline")
	}
	return *user.AirlineID, nil
}
func (s *Service) registerCommanderTrainings(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/commander/training-sessions"
	mux.HandleFunc("GET "+p, platform.Wrap(s.commanderSessions))
	mux.HandleFunc("GET "+p+"/{training_session_id}", platform.Wrap(s.commanderSessionDetail))
}

// Aliases are shared by grouped list, related-day lookup and detail. Ownership
// follows the grading scheme's airline, independently of the instructor's tenant.
const commanderSessionSelect = `SELECT t.id AS training_session_id,t.completed_at,t.scenario_day_module_id,
 t.scenario_revision_id,t.scenario_revision_number,t.notes,t.day_index_snapshot AS day_index,
 t.days_count_snapshot AS days_count,t.scenario_id_snapshot AS scenario_id,
 t.scenario_title_snapshot AS scenario_title,t.aircraft_id_snapshot AS aircraft_id,t.aircraft_code_snapshot AS aircraft_code,
 t.instructor_id AS instructor_user_id_internal,iu.public_id AS instructor_public_id,
 ii.first_name AS instructor_first_name,ii.last_name AS instructor_last_name,ii.photo_url AS instructor_photo_url,
 a1.user_id AS cm1_user_id_internal,u1.public_id AS cm1_public_id,i1.first_name AS cm1_first_name,i1.last_name AS cm1_last_name,i1.photo_url AS cm1_photo_url,
 a2.user_id AS cm2_user_id_internal,u2.public_id AS cm2_public_id,i2.first_name AS cm2_first_name,i2.last_name AS cm2_last_name,i2.photo_url AS cm2_photo_url
 FROM training_session t JOIN grading_scheme g ON g.id=t.grading_scheme_id
 LEFT JOIN users iu ON iu.id=t.instructor_id LEFT JOIN user_info ii ON ii.id=iu.id
 LEFT JOIN crew_member_assessment a1 ON a1.training_session_id=t.id AND a1.training_role='cm1'
 LEFT JOIN users u1 ON u1.id=a1.user_id LEFT JOIN user_info i1 ON i1.id=u1.id
 LEFT JOIN crew_member_assessment a2 ON a2.training_session_id=t.id AND a2.training_role='cm2'
 LEFT JOIN users u2 ON u2.id=a2.user_id LEFT JOIN user_info i2 ON i2.id=u2.id`

var commanderSessionQueryFields = []platform.Field{
	{Name: "completed_from", Alias: "completedFrom", Kind: "date", Nullable: true}, {Name: "completed_to", Alias: "completedTo", Kind: "date", Nullable: true},
	{Name: "scenario_id", Alias: "scenarioId", Kind: "integer", Min: 1, Nullable: true},
	{Name: "instructor_id", Alias: "instructorId", Kind: "uuid", Nullable: true}, {Name: "participant_id", Alias: "participantId", Kind: "uuid", Nullable: true},
	{Name: "cm1_id", Alias: "cm1Id", Kind: "uuid", Nullable: true}, {Name: "cm2_id", Alias: "cm2Id", Kind: "uuid", Nullable: true},
	{Name: "aircraft_id", Alias: "aircraftId", Kind: "integer", Min: 1, Nullable: true},
	{Name: "limit", Kind: "integer", Min: 1, Max: 200, Default: int64(50)}, {Name: "offset", Kind: "integer", NonNegative: true, Default: int64(0)},
}

func (s *Service) commanderSessions(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), commanderSessionQueryFields...)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	if q["completed_from"] != nil && q["completed_to"] != nil && q["completed_from"].(time.Time).After(q["completed_to"].(time.Time)) {
		return commanderError(400, "INVALID_COMPLETED_RANGE", "completedFrom must be less than or equal to completedTo")
	}
	args := []any{airline}
	where := []string{"g.airline_id=$1", "t.status='COMPLETED'"}
	add := func(clause string, value any) {
		args = append(args, value)
		where = append(where, fmt.Sprintf(clause, len(args)))
	}
	for _, f := range []struct{ name, clause string }{{"completed_from", "t.completed_at >= $%d"}, {"scenario_id", "t.scenario_id_snapshot=$%d"}, {"instructor_id", "iu.public_id=$%d"}, {"cm1_id", "u1.public_id=$%d"}, {"cm2_id", "u2.public_id=$%d"}, {"aircraft_id", "t.aircraft_id_snapshot=$%d"}} {
		if q[f.name] != nil {
			add(f.clause, q[f.name])
		}
	}
	if q["completed_to"] != nil {
		add("t.completed_at < $%d", q["completed_to"].(time.Time).AddDate(0, 0, 1))
	}
	if q["participant_id"] != nil {
		args = append(args, q["participant_id"])
		where = append(where, fmt.Sprintf("(u1.public_id=$%d OR u2.public_id=$%d)", len(args), len(args)))
	}
	groupable := "scenario_id IS NOT NULL AND cm1_user_id_internal IS NOT NULL AND cm2_user_id_internal IS NOT NULL"
	cte := "WITH base AS (" + commanderSessionSelect + " WHERE " + strings.Join(where, " AND ") + "), grouped AS (SELECT base.*,row_number() OVER (PARTITION BY CASE WHEN " + groupable + " THEN scenario_id ELSE -training_session_id END,CASE WHEN " + groupable + " THEN least(cm1_user_id_internal,cm2_user_id_internal) ELSE -training_session_id END,CASE WHEN " + groupable + " THEN greatest(cm1_user_id_internal,cm2_user_id_internal) ELSE -training_session_id END ORDER BY completed_at DESC,training_session_id DESC) AS group_rank FROM base) "
	var total int64
	if err = s.Auth.DB.QueryRow(r.Context(), cte+"SELECT count(*) FROM grouped WHERE group_rank=1", args...).Scan(&total); err != nil {
		return err
	}
	args = append(args, q.Int("limit"), q.Int("offset"))
	rows, err := queryRecords(r.Context(), s.Auth.DB, cte+fmt.Sprintf("SELECT to_jsonb(g) FROM grouped g WHERE group_rank=1 ORDER BY completed_at DESC,training_session_id DESC LIMIT $%d OFFSET $%d", len(args)-1, len(args)), args...)
	if err != nil {
		return err
	}
	items, err := commanderListItems(r.Context(), s.Auth.DB, airline, rows, true)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(record{"total": total, "limit": q["limit"], "offset": q["offset"], "items": items}))
	return nil
}

type commanderGroup [3]int64

func commanderGroupKey(r record) (commanderGroup, bool) {
	if r["scenario_id"] == nil || r["cm1_user_id_internal"] == nil || r["cm2_user_id_internal"] == nil {
		return commanderGroup{}, false
	}
	a, b := r.number("cm1_user_id_internal"), r.number("cm2_user_id_internal")
	if a > b {
		a, b = b, a
	}
	return commanderGroup{r.number("scenario_id"), a, b}, true
}
func commanderTitle(r record, withDay bool) string {
	title := pythonTrim(r.text("scenario_title"))
	if title == "" {
		title = fmt.Sprintf("Training Session %d", r.number("training_session_id"))
	}
	if withDay && r["day_index"] != nil && r.number("days_count") > 1 {
		title += fmt.Sprintf("-DAY %d", r.number("day_index"))
	}
	return title
}
func commanderListItems(ctx context.Context, db runtimeDB, airline int64, rows []record, scenarioTitle bool) ([]record, error) {
	out := []record{}
	keys := map[commanderGroup]bool{}
	for _, r := range rows {
		if k, ok := commanderGroupKey(r); ok {
			keys[k] = true
		}
	}
	related := map[commanderGroup][]record{}
	if len(keys) > 0 {
		args := []any{airline}
		tuples := []string{}
		for k := range keys {
			args = append(args, k[0], k[1], k[2])
			tuples = append(tuples, fmt.Sprintf("($%d::bigint,$%d::bigint,$%d::bigint)", len(args)-2, len(args)-1, len(args)))
		}
		query := commanderSessionSelect + " WHERE g.airline_id=$1 AND t.status='COMPLETED' AND t.completed_at IS NOT NULL AND a1.user_id IS NOT NULL AND a2.user_id IS NOT NULL AND (t.scenario_id_snapshot,least(a1.user_id,a2.user_id),greatest(a1.user_id,a2.user_id)) IN (" + strings.Join(tuples, ",") + ") ORDER BY t.completed_at DESC,t.id DESC"
		candidates, err := queryRecords(ctx, db, "SELECT to_jsonb(r) FROM ("+query+") r", args...)
		if err != nil {
			return nil, err
		}
		for _, r := range candidates {
			k, _ := commanderGroupKey(r)
			related[k] = append(related[k], r)
		}
	}
	for _, r := range rows {
		item := r.project("day_index completed_at instructor_first_name instructor_last_name instructor_photo_url cm1_first_name cm1_last_name cm1_photo_url cm2_first_name cm2_last_name cm2_photo_url aircraft_id")
		item["id"] = r["training_session_id"]
		item["title"] = commanderTitle(r, !scenarioTitle)
		item["day_title"] = nil
		if scenarioTitle {
			if title := commanderTitle(r, true); title != item["title"] {
				item["day_title"] = title
			}
		}
		for _, who := range []string{"instructor", "cm1", "cm2"} {
			item[who+"_id"] = r[who+"_public_id"]
		}
		previous := []record{}
		seen := map[int64]bool{}
		if k, ok := commanderGroupKey(r); ok {
			for _, c := range related[k] {
				id := c.number("scenario_day_module_id")
				if c["scenario_day_module_id"] == nil || r["scenario_day_module_id"] != nil && id == r.number("scenario_day_module_id") || seen[id] {
					continue
				}
				seen[id] = true
				index := int64(-1)
				if c["day_index"] != nil {
					index = c.number("day_index")
				}
				titleRow := record{}
				for k, v := range c {
					titleRow[k] = v
				}
				if index < 0 {
					titleRow["day_index"] = nil
				}
				previous = append(previous, record{"id": c["training_session_id"], "title": commanderTitle(titleRow, true), "day_index": titleRow["day_index"], "sort_index": index, "sort_day": id})
			}
		}
		sort.SliceStable(previous, func(i, j int) bool {
			a, b := previous[i], previous[j]
			if a.number("sort_index") != b.number("sort_index") {
				return a.number("sort_index") > b.number("sort_index")
			}
			return a.number("sort_day") > b.number("sort_day")
		})
		for _, p := range previous {
			delete(p, "sort_index")
			delete(p, "sort_day")
		}
		item["previous_days"] = previous
		out = append(out, item)
	}
	return out, nil
}

func commanderWire(value any) any {
	switch v := value.(type) {
	case record:
		return commanderWire(map[string]any(v))
	case map[string]any:
		out := map[string]any{}
		for k, item := range v {
			if item != nil && (k == "completed_at" || k == "signed_at" || k == "timestamp" || k == "accepted_at" || k == "created_at" || k == "updated_at") {
				if raw, ok := item.(string); ok {
					if t, err := time.Parse(time.RFC3339Nano, raw); err == nil {
						item = apiTime(&t)
					}
				}
			}
			out[camelKey(k)] = commanderWire(item)
		}
		return out
	case []record:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, commanderWire(item))
		}
		return out
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, commanderWire(item))
		}
		return out
	}
	return value
}

func (s *Service) commanderSessionDetail(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "pilots:read")
	if err != nil {
		return err
	}
	id, err := platform.ValidateObject(map[string]any{"training_session_id": r.PathValue("training_session_id")}, []any{"path"}, platform.Schema{Fields: []platform.Field{{Name: "training_session_id", Kind: "integer", Min: 1, Required: true}}})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tid := id.Int("training_session_id")
	row, err := queryRecord(r.Context(), s.Auth.DB, "SELECT to_jsonb(r) FROM ("+commanderSessionSelect+" WHERE g.airline_id=$1 AND t.status='COMPLETED' AND t.id=$2) r", airline, tid)
	if errors.Is(err, pgx.ErrNoRows) {
		return commanderError(404, "TRAINING_SESSION_NOT_FOUND", "Training session not found")
	}
	if err != nil {
		return err
	}
	items, err := commanderListItems(r.Context(), s.Auth.DB, airline, []record{row}, false)
	if err != nil {
		return err
	}
	session := items[0]
	for _, k := range strings.Fields("scenario_id scenario_revision_id scenario_revision_number scenario_day_module_id day_index days_count aircraft_code notes") {
		session[k] = row[k]
	}
	modules, exercises, sortKeys, err := commanderModules(r.Context(), s.Auth.DB, tid)
	if err != nil {
		return err
	}
	assessments, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(a)||jsonb_build_object('pilot_id',u.public_id,'pilot_first_name',i.first_name,'pilot_last_name',i.last_name,'pilot_photo_url',i.photo_url) FROM crew_member_assessment a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN user_info i ON i.id=u.id WHERE a.training_session_id=$1 ORDER BY a.training_role,a.id`, tid)
	if err != nil {
		return err
	}
	runtime, participants, runs, err := commanderRuntime(r.Context(), s.Auth.DB, tid, assessments, exercises)
	if err != nil {
		return err
	}
	for _, m := range modules {
		for _, e := range m["exercises"].([]record) {
			items := runs[e.number("id")]
			if items == nil {
				items = []record{}
			}
			e["runs"] = items
		}
	}
	reports, err := commanderAssessments(r.Context(), s.Auth.DB, tid, assessments, exercises, sortKeys)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(record{"session": session, "crew_runtime": runtime, "participants": participants, "modules": modules, "assessments": reports}))
	return nil
}
