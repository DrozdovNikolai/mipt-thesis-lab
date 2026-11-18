package training

import (
	"fmt"
	"net/http"

	"north55/backend/internal/platform"
)

func (s *Service) listEditorScenarioSummary(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), libraryAircraftField(),
		platform.Field{Name: "q", Kind: "string", Nullable: true},
		platform.Field{Name: "status", Kind: "string", Nullable: true},
		platform.Field{Name: "include_archived", Alias: "includeArchived", Kind: "boolean", Default: false},
		platform.Field{Name: "sort", Kind: "string", Default: "updated_at_desc"},
		platform.Field{Name: "limit", Kind: "integer", AllowBigInteger: true, Default: int64(10)},
		platform.Field{Name: "offset", Kind: "integer", AllowBigInteger: true, Default: int64(0)})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(u)
	if err != nil {
		return err
	}
	aircraft, err := libraryAircraft(r.Context(), s.Auth.DB, u, q["aircraft_id"], false, false)
	if err != nil {
		return err
	}
	limit := q.Int("limit")
	if q.CompareInteger("limit", 100) > 0 {
		limit = 100
	}
	if q.CompareInteger("limit", 1) < 0 {
		limit = 1
	}
	var offset any = q["offset"]
	if q.CompareInteger("offset", 0) < 0 {
		offset = int64(0)
	}
	status, search := q.String("status"), pythonTrim(q.String("q"))
	filter := `s.airline_id=$1 AND s.aircraft_id=ANY($2::bigint[]) AND s.deleted_at IS NULL AND (($3::text<>'' AND s.status=$3) OR ($3='' AND ($4 OR s.status<>'ARCHIVED'))) AND ($5::text='' OR s.title ILIKE ('%'||$5||'%') OR s.code ILIKE ('%'||$5||'%'))`
	args := []any{airline, aircraft, status, q.Bool("include_archived"), search}
	var total int64
	if err = s.Auth.DB.QueryRow(r.Context(), `SELECT count(s.id) FROM scenario s WHERE `+filter, args...).Scan(&total); err != nil {
		return err
	}
	orders := map[string]string{"updated_at_desc": "s.updated_at DESC,s.id DESC", "updated_at_asc": "s.updated_at,s.id", "created_at_desc": "s.created_at DESC,s.id DESC", "created_at_asc": "s.created_at,s.id", "title_asc": "s.title,s.id", "title_desc": "s.title DESC,s.id DESC"}
	aliases := map[string]string{"updatedAtDesc": "updated_at_desc", "updatedAtAsc": "updated_at_asc", "createdAtDesc": "created_at_desc", "createdAtAsc": "created_at_asc", "titleAsc": "title_asc", "titleDesc": "title_desc"}
	sortKey := q.String("sort")
	if alias, ok := aliases[sortKey]; ok {
		sortKey = alias
	}
	order, ok := orders[sortKey]
	if !ok {
		return &platform.APIError{Status: 400, Code: "INVALID_SORT", Message: "Unsupported sort option", Extra: map[string]any{"sort": q["sort"]}}
	}
	// Only the server-selected order expression is interpolated. Search, scope
	// and pagination remain parameters; the aggregates match the source joins.
	query := `SELECT to_jsonb(s)||jsonb_build_object('aircraft_code',a.code,'modules_count',coalesce(m.modules_count,0),'days_count',coalesce(m.days_count,0),'duration_total_minutes',coalesce(m.duration_total_minutes,0),'content_set_id',l.content_set_id,'set_label_id',l.set_label_id)
FROM scenario s JOIN aircraft_airline a ON a.id=s.aircraft_id
LEFT JOIN (SELECT mo.scenario_id,count(mo.id) modules_count,coalesce(sum(coalesce(mo.duration_minutes,0)),0) duration_total_minutes,count(DISTINCT d.day_index) days_count FROM module mo LEFT JOIN scenario_day_module d ON d.module_id=mo.id GROUP BY mo.scenario_id) m ON m.scenario_id=s.id
LEFT JOIN LATERAL (SELECT la.content_set_id,la.id set_label_id FROM scenario_content_set_label_scenario ls JOIN scenario_content_set_label la ON la.id=ls.label_id WHERE ls.scenario_id=s.id ORDER BY ls.id LIMIT 1) l ON true
WHERE ` + filter + ` ORDER BY ` + order + ` OFFSET $6 LIMIT $7`
	rows, err := queryRecords(r.Context(), s.Auth.DB, query, append(args, offset, limit)...)
	if err != nil {
		return err
	}
	items := []any{}
	for _, row := range rows {
		if row["title"] == nil || row["status"] == nil {
			return fmt.Errorf("invalid stored scenario summary")
		}
		items = append(items, scenarioWire(row.project("id title status aircraft_id aircraft_code engines archived_by archived_at deleted_by deleted_at updated_at created_at modules_count days_count duration_total_minutes content_set_id set_label_id")))
	}
	platform.WriteJSON(w, 200, map[string]any{"total": total, "limit": limit, "offset": offset, "items": items})
	return nil
}
