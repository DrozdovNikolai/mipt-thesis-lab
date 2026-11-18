package training

import (
	"context"
	"fmt"
	"net/http"
	"sort"

	"north55/backend/internal/platform"
)

func libraryBlockElementDTO(row record) (any, error) {
	if row == nil {
		return nil, fmt.Errorf("block element disappeared after commit")
	}
	if !libraryContainsString([]string{"FLAT", "UP", "DOWN", "LINKED"}, row.text("profile_type")) {
		return nil, fmt.Errorf("invalid stored block element profile")
	}
	return commanderWire(row.project("id " + libraryBlockElementFields)), nil
}
func libraryContainsString(values []string, needle string) bool {
	for _, value := range values {
		if value == needle {
			return true
		}
	}
	return false
}
func libraryBlockElementsDTO(ctx context.Context, db runtimeDB, blockID any) ([]any, error) {
	rows, err := queryRecords(ctx, db, "SELECT to_jsonb(e) FROM element_block_element e WHERE block_id=$1", blockID)
	if err != nil {
		return nil, err
	}
	items := []any{}
	for _, row := range rows {
		value, err := libraryBlockElementDTO(row)
		if err != nil {
			return nil, err
		}
		items = append(items, value)
	}
	return items, nil
}
func libraryInsertBlockElement(ctx context.Context, db runtimeDB, blockID any, data record, explicitID bool) (record, error) {
	row := data.project(libraryBlockElementFields)
	row["block_id"] = blockID
	if row["order_index"] == nil {
		row["order_index"] = int64(0)
	}
	if row["profile_type"] == nil {
		row["profile_type"] = "FLAT"
	}
	if explicitID {
		row["id"] = data["id"]
	}
	return insertTrainingRow(ctx, db, "element_block_element", row)
}
func libraryReplaceBlockElements(ctx context.Context, db runtimeDB, blockID any, airline int64, allowed []int64, raw any, rows []record) error {
	items, _ := raw.([]any)
	ids := []any{}
	seen := map[string]bool{}
	full := true
	for _, item := range items {
		row := libraryRecord(item)
		ids = append(ids, row["element_id"])
		key := fmt.Sprint(row["id"])
		if row["id"] == nil || seen[key] {
			full = false
		}
		seen[key] = true
	}
	if err := libraryValidateBlockElementIDs(ctx, db, airline, allowed, ids); err != nil {
		return err
	}
	if !full {
		if _, err := db.Exec(ctx, "DELETE FROM element_block_element WHERE block_id=$1", blockID); err != nil {
			return err
		}
		for _, item := range items {
			if _, err := libraryInsertBlockElement(ctx, db, blockID, libraryRecord(item), false); err != nil {
				return err
			}
		}
		return nil
	}
	var err error
	old := map[string]record{}
	for _, row := range rows {
		old[fmt.Sprint(row["id"])] = row
	}
	type update struct{ old, changes record }
	updates := []update{}
	inserts := []record{}
	for _, item := range items {
		row := libraryRecord(item)
		prior := old[fmt.Sprint(row["id"])]
		if prior == nil {
			inserts = append(inserts, row)
			continue
		}
		changes := record{}
		for key, value := range row {
			if key != "id" {
				changes[key] = value
			}
		}
		updates = append(updates, update{prior, changes})
	}
	// SQLAlchemy flushes dirty existing rows in primary-key order, then new
	// rows in payload order, before the bulk removal of omitted IDs.
	sort.Slice(updates, func(i, j int) bool { return updates[i].old.number("id") < updates[j].old.number("id") })
	for _, change := range updates {
		if err = libraryUpdate(ctx, db, "element_block_element", change.old, change.changes); err != nil {
			return err
		}
		for key, value := range change.changes {
			change.old[key] = value
		}
	}
	for _, row := range inserts {
		if _, err = libraryInsertBlockElement(ctx, db, blockID, row, true); err != nil {
			return err
		}
	}
	if len(old) > 0 {
		remove := []int64{}
		for key, row := range old {
			if !seen[key] {
				remove = append(remove, row.number("id"))
			}
		}
		if _, err = db.Exec(ctx, "DELETE FROM element_block_element WHERE block_id=$1 AND id=ANY($2::bigint[])", blockID, remove); err != nil {
			return err
		}
	}
	return nil
}
func (s *Service) listLibraryBlockElements(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "block_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	block, err := libraryFind(r.Context(), s.Auth.DB, "element_block", path["block_id"])
	if err != nil {
		return err
	}
	if !libraryOwnBlock(block, airline, false) {
		return platform.Error(404, "Block not found")
	}
	items, err := libraryBlockElementsDTO(r.Context(), s.Auth.DB, block["id"])
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, items)
	return nil
}
func (s *Service) createLibraryBlockElement(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := libraryBlockElementModel(true, true)
	path, body, err := libraryInput(r, &schema, "block_id")
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
	block, err := libraryFind(ctx, tx, "element_block", path["block_id"])
	if err != nil {
		return err
	}
	if !libraryOwnBlock(block, airline, false) {
		return platform.Error(404, "Block not found")
	}
	if err = libraryValidateBlockElementIDs(ctx, tx, airline, allowed, []any{body["element_id"]}); err != nil {
		return err
	}
	row, err := libraryInsertBlockElement(ctx, tx, block["id"], record(body), false)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return s.libraryWriteBlockElementResponse(ctx, w, row["id"], 201)
}
func (s *Service) libraryWriteBlockElementResponse(ctx context.Context, w http.ResponseWriter, id any, status int) error {
	row, err := libraryFind(ctx, s.Auth.DB, "element_block_element", id)
	if err != nil {
		return err
	}
	value, err := libraryBlockElementDTO(row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, status, value)
	return nil
}
func (s *Service) updateLibraryBlockElement(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := libraryBlockElementModel(false, false)
	path, body, err := libraryInput(r, &schema, "block_id", "ebe_id")
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
	row, err := libraryFind(ctx, tx, "element_block_element", path["ebe_id"])
	if err != nil {
		return err
	}
	if row == nil || !librarySame(row["block_id"], path["block_id"]) {
		return platform.Error(404, "Block element not found")
	}
	block, err := libraryFind(ctx, tx, "element_block", path["block_id"])
	if err != nil {
		return err
	}
	if !libraryOwnBlock(block, airline, true) {
		return platform.Error(404, "Block element not found")
	}
	if body["element_id"] != nil {
		if err = libraryValidateBlockElementIDs(ctx, tx, airline, allowed, []any{body["element_id"]}); err != nil {
			return err
		}
	}
	if err = libraryUpdate(ctx, tx, "element_block_element", row, record(body)); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return s.libraryWriteBlockElementResponse(ctx, w, row["id"], 200)
}
func (s *Service) deleteLibraryBlockElement(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "block_id", "ebe_id")
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	row, err := libraryFind(ctx, tx, "element_block_element", path["ebe_id"])
	if err != nil {
		return err
	}
	if row == nil || !librarySame(row["block_id"], path["block_id"]) {
		return platform.Error(404, "Block element not found")
	}
	block, err := libraryFind(ctx, tx, "element_block", path["block_id"])
	if err != nil {
		return err
	}
	if !libraryOwnBlock(block, airline, true) {
		return platform.Error(404, "Block element not found")
	}
	if _, err = tx.Exec(ctx, "DELETE FROM element_block_element WHERE id=$1", row["id"]); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
