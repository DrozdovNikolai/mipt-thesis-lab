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
