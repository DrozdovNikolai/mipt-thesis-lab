package training

import (
	"net/http"

	"north55/backend/internal/platform"
)

func (s *Service) listContentSetSummary(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), libraryAircraftField(),
		platform.Field{Name: "q", Kind: "string", Nullable: true},
		platform.Field{Name: "sort", Kind: "string", Default: "updated_at_desc"},
		platform.Field{Name: "limit", Kind: "integer", AllowBigInteger: true, Default: int64(10)},
		platform.Field{Name: "offset", Kind: "integer", AllowBigInteger: true, Default: int64(0)})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	aircraft, err := libraryAircraft(ctx, s.Auth.DB, user, q["aircraft_id"], false, false)
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
	filter := `c.airline_id=$1 AND c.aircraft_id=ANY($2::bigint[]) AND ($3::text='' OR c.name ILIKE ('%'||$3||'%'))`
	args := []any{airline, aircraft, pythonTrim(q.String("q"))}
	var total int64
	if err = s.Auth.DB.QueryRow(ctx, `SELECT count(c.id) FROM scenario_content_set c WHERE `+filter, args...).Scan(&total); err != nil {
		return err
	}
	orders := map[string]string{"updated_at_desc": "c.updated_at DESC,c.id DESC", "updated_at_asc": "c.updated_at,c.id", "created_at_desc": "c.created_at DESC,c.id DESC", "created_at_asc": "c.created_at,c.id", "name_asc": "c.name,c.id", "name_desc": "c.name DESC,c.id DESC"}
	aliases := map[string]string{"updatedAtDesc": "updated_at_desc", "updatedAtAsc": "updated_at_asc", "createdAtDesc": "created_at_desc", "createdAtAsc": "created_at_asc", "nameAsc": "name_asc", "nameDesc": "name_desc"}
	sortKey := q.String("sort")
	if alias, ok := aliases[sortKey]; ok {
		sortKey = alias
	}
	order, ok := orders[sortKey]
	if !ok {
		return &platform.APIError{Status: 400, Code: "INVALID_SORT", Message: "Unsupported sort option", Extra: map[string]any{"sort": q["sort"]}}
	}
	// The legacy scenarios_count counts labels, including unlinked labels.
	query := `SELECT to_jsonb(c)||jsonb_build_object(
'scenarios_count',(SELECT count(*) FROM scenario_content_set_label l WHERE l.content_set_id=c.id),
'subcolumns_count',(SELECT count(*) FROM scenario_content_subcolumn sc WHERE sc.content_set_id=c.id),
'folders_count',(SELECT count(*) FROM scenario_content_folder f WHERE f.content_set_id=c.id),
'requirements_count',(SELECT count(*) FROM scenario_content_requirement re WHERE re.content_set_id=c.id))
FROM scenario_content_set c WHERE ` + filter + ` ORDER BY ` + order + ` OFFSET $4 LIMIT $5`
	rows, err := queryRecords(ctx, s.Auth.DB, query, append(args, offset, limit)...)
	if err != nil {
		return err
	}
	items := []record{}
	for _, row := range rows {
		value, err := contentSetDTO(ctx, s.Auth.DB, row)
		if err != nil {
			return err
		}
		for _, field := range []string{"scenarios_count", "subcolumns_count", "folders_count", "requirements_count"} {
			value[field] = row[field]
		}
		items = append(items, value)
	}
	platform.WriteJSON(w, 200, commanderWire(record{"total": total, "limit": limit, "offset": offset, "items": items}))
	return nil
}
