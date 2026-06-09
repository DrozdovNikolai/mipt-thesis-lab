package training

import (
	"context"
	"fmt"
	"math/big"
	"net/http"

	"north55/backend/internal/platform"
)

func libraryItemDTO(row record) any {
	item := row.project("id folder_id order_index element_id block_id")
	return commanderWire(item)
}
func libraryValidElement(row record, airline, aircraft int64) bool {
	return row != nil && row.number("airline_id") == airline && row.number("aircraft_id") == aircraft && row["archived_at"] == nil
}
func libraryReadItems(ctx context.Context, db runtimeDB, c libraryCollection, folderIDs []int64, includeArchived bool) ([]any, error) {
	items := []any{}
	if len(folderIDs) == 0 {
		return items, nil
	}
	rows, err := queryRecords(ctx, db, "SELECT to_jsonb(i) FROM "+c.itemTable()+" i JOIN "+c.entityTable()+" e ON e.id=i."+c.entityKey()+" WHERE i.folder_id=ANY($1::bigint[]) AND ($2 OR e.archived_at IS NULL) ORDER BY i.folder_id,i.order_index,i.id", folderIDs, includeArchived)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		items = append(items, libraryItemDTO(row))
	}
	return items, nil
}

func (s *Service) createLibraryItem(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, libraryItemSchema(true, c))
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	allowed, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	folder, err := libraryFind(ctx, tx, c.folderTable(), body["folder_id"])
	if err != nil {
		return err
	}
	if err = libraryRequired(airline, allowed, folder, true, "Folder not found"); err != nil {
		return err
	}
	element, err := libraryFind(ctx, tx, c.entityTable(), body[c.entityKey()])
	if err != nil {
		return err
	}
	if c == blockLibrary {
		if element == nil || element.number("airline_id") != airline || element["archived_at"] != nil {
			return platform.Error(400, "Invalid block")
		}
		if err = libraryMatchBlockFolder(ctx, tx, folder, body["block_id"]); err != nil {
			return err
		}
	} else if !libraryValidElement(element, airline, folder.number("aircraft_id")) {
		return platform.Error(400, "Invalid element")
	}
	row, err := insertTrainingRow(ctx, tx, c.itemTable(), record(body))
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = libraryFind(ctx, s.Auth.DB, c.itemTable(), row["id"])
	if err != nil {
		return err
	}
	if row == nil {
		return fmt.Errorf("folder item disappeared after commit")
	}
	platform.WriteJSON(w, 201, libraryItemDTO(row))
	return nil
}

func (s *Service) listLibraryItems(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
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
	folders, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(f) FROM "+c.folderTable()+" f WHERE f.airline_id=$1 AND f.aircraft_id=ANY($2::bigint[]) AND ($3 OR f.archived_at IS NULL)"+filter, args...)
	if err != nil {
		return err
	}
	ids := []int64{}
	for _, row := range folders {
		ids = append(ids, row.number("id"))
	}
	items, err := libraryReadItems(r.Context(), s.Auth.DB, c, ids, q.Bool("include_archived"))
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, items)
	return nil
}

func (s *Service) queryLibraryItems(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, platform.Schema{Fields: []platform.Field{{Name: "folder_ids", Alias: "folderIds", Kind: "list", Required: true, Min: 1, Item: &platform.Field{Kind: "integer", AllowBigInteger: true}}}})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	allowed, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	ids := []int64{}
	seen := map[int64]bool{}
	wide := false
	for _, raw := range body["folder_ids"].([]any) {
		if n, ok := raw.(*big.Int); ok {
			if n.Sign() <= 0 {
				return platform.Error(400, "folder_ids must contain positive integer ids")
			}
			wide = true
			continue
		}
		id := raw.(int64)
		if id <= 0 {
			return platform.Error(400, "folder_ids must contain positive integer ids")
		}
		if !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	if wide {
		return fmt.Errorf("folder id exceeds PostgreSQL bigint range")
	}

	folders, err := queryRecords(r.Context(), s.Auth.DB, "SELECT to_jsonb(f) FROM "+c.folderTable()+" f WHERE id=ANY($1::bigint[])", ids)
	if err != nil {
		return err
	}
	valid := 0
	for _, row := range folders {
		if row["airline_id"] == nil {
			return fmt.Errorf("legacy folder airline_id cannot be converted to int")
		}
		if libraryScoped(row, airline, allowed, true) {
			valid++
		}
	}
	if valid != len(ids) {
		return platform.Error(404, "Folder not found")
	}
	items, err := libraryReadItems(r.Context(), s.Auth.DB, c, ids, false)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, items)
	return nil
}
