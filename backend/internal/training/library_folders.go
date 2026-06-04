package training

import (
	"context"
	"fmt"
	"net/http"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func libraryFolderDTO(ctx context.Context, db runtimeDB, row record, kind any) (any, error) {
	if row == nil {
		return nil, fmt.Errorf("folder disappeared after commit")
	}
	aircraft, err := libraryFind(ctx, db, "aircraft_airline", row["aircraft_id"])
	if err != nil {
		return nil, err
	}
	result := row.project("id name color_hex parent_id aircraft_id order_index airline_id archived_by archived_at created_at updated_at")
	result["aircraft_code"], result["library_kind"] = aircraft["code"], kind
	return libraryWire(result), nil
}
func libraryFolderOrder(ctx context.Context, db runtimeDB, c libraryCollection, airline, aircraft int64, parent, kind any) (int64, error) {
	var next int64
	query := "SELECT coalesce(max(order_index),-1)::bigint+1 FROM " + c.folderTable() + " WHERE airline_id=$1 AND aircraft_id=$2 AND parent_id IS NOT DISTINCT FROM $3::bigint AND archived_at IS NULL"
	args := []any{airline, aircraft, parent}
	if c == blockLibrary {
		query += " AND library_kind=$4"
		args = append(args, kind)
	}
	err := db.QueryRow(ctx, query, args...).Scan(&next)
	return next, err
}

func (s *Service) listLibraryFolders(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := c.query(r)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aircraft, err := libraryAircraft(r.Context(), s.Auth.DB, user, q["aircraft_id"], false, false)
	if err != nil {
		return err
	}
	filter, extra, err := c.kindFilter(q)
	if err != nil {
		return err
	}
	args := append([]any{airline, aircraft, q.Bool("include_archived")}, extra...)
	rows, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(f)||jsonb_build_object('aircraft_code',a.code) FROM "+c.folderTable()+" f LEFT JOIN aircraft_airline a ON a.id=f.aircraft_id WHERE f.airline_id=$1 AND f.aircraft_id=ANY($2::bigint[]) AND ($3 OR f.archived_at IS NULL)"+filter+" ORDER BY f.parent_id NULLS FIRST,f.order_index,f.id", args...)
	if err != nil {
		return err
	}
	items := []any{}
	for _, row := range rows {
		item := row.project("id name color_hex parent_id aircraft_id aircraft_code order_index airline_id archived_by archived_at created_at updated_at")
		item["library_kind"] = row["library_kind"]
		items = append(items, libraryWire(item))
	}
	platform.WriteJSON(w, 200, items)
	return nil
}
