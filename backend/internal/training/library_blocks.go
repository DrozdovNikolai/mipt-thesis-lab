package training

import (
	"context"
	"fmt"
	"math/big"
	"net/http"
	"sort"
	"time"

	"north55/backend/internal/platform"
)

func (s *Service) registerLibraryBlocks(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/element-blocks"
	mux.HandleFunc("GET "+p, platform.Wrap(s.listLibraryBlocks))
	mux.HandleFunc("POST "+p, platform.Wrap(s.createLibraryBlock))
	mux.HandleFunc("PUT "+p+"/{block_id}", platform.Wrap(s.updateLibraryBlock))
	mux.HandleFunc("DELETE "+p+"/{block_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.archiveLibraryBlock(w, r, false) }))
	mux.HandleFunc("POST "+p+"/{block_id}/restore", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.archiveLibraryBlock(w, r, true) }))
	mux.HandleFunc("GET "+p+"/{block_id}/elements", platform.Wrap(s.listLibraryBlockElements))
	mux.HandleFunc("POST "+p+"/{block_id}/elements", platform.Wrap(s.createLibraryBlockElement))
	mux.HandleFunc("PUT "+p+"/{block_id}/elements/{ebe_id}", platform.Wrap(s.updateLibraryBlockElement))
	mux.HandleFunc("DELETE "+p+"/{block_id}/elements/{ebe_id}", platform.Wrap(s.deleteLibraryBlockElement))
}
func libraryOwnBlock(block record, airline int64, active bool) bool {
	return block != nil && block.number("airline_id") == airline && (!active || block["archived_at"] == nil)
}

type libraryBlockRelations struct {
	elements      []record
	competenceIDs []any
}

func libraryReadBlockRelations(ctx context.Context, db runtimeDB, id any) (*libraryBlockRelations, error) {
	elements, err := queryRecords(ctx, db, "SELECT to_jsonb(e) FROM element_block_element e WHERE block_id=$1", id)
	if err != nil {
		return nil, err
	}
	// The source relationships have no ORDER BY; keep database order.
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM element_block b JOIN element_block_competence bc ON b.id=bc.block_id JOIN competence c ON c.id=bc.competence_id WHERE b.id IN ($1)`, id)
	if err != nil {
		return nil, err
	}
	ids := []any{}
	for _, row := range rows {
		ids = append(ids, row["id"])
	}
	return &libraryBlockRelations{elements, ids}, nil
}
func libraryBlockDTO(ctx context.Context, db runtimeDB, block record, relations *libraryBlockRelations) (any, error) {
	if block == nil {
		return nil, fmt.Errorf("block disappeared after commit")
	}
	result := block.project("id airline_id archived_by archived_at created_at updated_at")
	var err error
	result["params"], err = libraryBlockParamDTO(ctx, db, block["element_block_param_id"])
	if err != nil {
		return nil, err
	}
	if relations == nil {
		relations, err = libraryReadBlockRelations(ctx, db, block["id"])
		if err != nil {
			return nil, err
		}
	}
	elements := []any{}
	for _, row := range relations.elements {
		value, err := libraryBlockElementDTO(row)
		if err != nil {
			return nil, err
		}
		elements = append(elements, value)
	}
	result["elements"], result["competence_ids"] = elements, relations.competenceIDs
	return libraryWire(result), nil
}
func (s *Service) libraryWriteBlockResponse(ctx context.Context, w http.ResponseWriter, id any, status int, relations *libraryBlockRelations) error {
	block, err := libraryFind(ctx, s.Auth.DB, "element_block", id)
	if err != nil {
		return err
	}
	value, err := libraryBlockDTO(ctx, s.Auth.DB, block, relations)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, status, value)
	return nil
}
func libraryValidateBlockElementIDs(ctx context.Context, db runtimeDB, airline int64, allowed []int64, ids []any) error {
	unique := map[int64]bool{}
	ordered := []int64{}
	for _, raw := range ids {
		if wide, ok := raw.(*big.Int); ok {
			if wide.Sign() > 0 {
				return fmt.Errorf("element id exceeds PostgreSQL bigint range")
			}
			continue
		}
		id, _ := raw.(int64)
		if id > 0 && !unique[id] {
			unique[id] = true
			ordered = append(ordered, id)
		}
	}
	if len(ordered) == 0 {
		return nil
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i] < ordered[j] })
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM element e WHERE airline_id=$1 AND id=ANY($2::bigint[]) AND aircraft_id=ANY($3::bigint[]) AND archived_at IS NULL`, airline, ordered, allowed)
	if err != nil {
		return err
	}
	for _, row := range rows {
		delete(unique, row.number("id"))
	}
	invalid := []int64{}
	for _, id := range ordered {
		if unique[id] {
			invalid = append(invalid, id)
		}
	}
	if len(invalid) > 0 {
		return &platform.APIError{Status: 400, Code: "INVALID_ELEMENT_IDS", Message: "Invalid element_id(s)", Extra: map[string]any{"element_ids": invalid}}
	}
	return nil
}
func libraryReplaceBlockCompetences(ctx context.Context, db runtimeDB, blockID any, airline int64, raw any, checkFolders bool) error {
	values, _ := raw.([]any)
	if checkFolders {
		kind := "exercise"
		if len(values) > 0 {
			kind = "competence"
		}
		var conflict bool
		if err := db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM block_folder f JOIN block_folder_item i ON i.folder_id=f.id WHERE i.block_id=$1 AND f.library_kind<>$2)`, blockID, kind).Scan(&conflict); err != nil {
			return err
		}
		if conflict {
			return platform.Error(400, "Block library kind does not match its saved folders")
		}
	}
	if _, err := db.Exec(ctx, "DELETE FROM element_block_competence WHERE block_id=$1", blockID); err != nil {
		return err
	}
	ids := []int64{}
	seen := map[int64]bool{}
	for _, raw := range values {
		id, ok := raw.(int64)
		if !ok {
			return fmt.Errorf("competence id exceeds PostgreSQL bigint range")
		}
		if !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	var count int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM competence WHERE airline_id=$1 AND id=ANY($2::bigint[])`, airline, ids).Scan(&count); err != nil {
		return err
	}
	if count != len(ids) {
		return platform.Error(400, "Invalid competence_ids")
	}
	for _, id := range ids {
		if _, err := insertTrainingRow(ctx, db, "element_block_competence", record{"block_id": blockID, "competence_id": id}); err != nil {
			return err
		}
	}
	return nil
}
func (s *Service) listLibraryBlocks(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), platform.Field{Name: "include_archived", Alias: "includeArchived", Kind: "boolean", Default: false})
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	rows, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(b) FROM element_block b WHERE airline_id=$1 AND ($2 OR archived_at IS NULL)`, airline, q.Bool("include_archived"))
	if err != nil {
		return err
	}
	items := []any{}
	for _, row := range rows {
		value, e := libraryBlockDTO(r.Context(), s.Auth.DB, row, nil)
		if e != nil {
			return e
		}
		items = append(items, value)
	}
	platform.WriteJSON(w, 200, items)
	return nil
}
func (s *Service) createLibraryBlock(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	_, body, err := libraryBlockInput(r, true)
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
	ids := []any{}
	for _, item := range body["elements"].([]any) {
		ids = append(ids, libraryRecord(item)["element_id"])
	}
	if err = libraryValidateBlockElementIDs(ctx, tx, airline, allowed, ids); err != nil {
		return err
	}
	params, err := libraryNewBlockParams(ctx, tx, libraryRecord(body["params"]))
	if err != nil {
		return err
	}
	params, err = insertTrainingRow(ctx, tx, "element_block_param", params)
	if err != nil {
		return err
	}
	block, err := insertTrainingRow(ctx, tx, "element_block", record{"airline_id": airline, "element_block_param_id": params["id"]})
	if err != nil {
		return err
	}
	for _, item := range body["elements"].([]any) {
		if _, err = libraryInsertBlockElement(ctx, tx, block["id"], libraryRecord(item), false); err != nil {
			return err
		}
	}
	if err = libraryReplaceBlockCompetences(ctx, tx, block["id"], airline, body["competence_ids"], false); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return s.libraryWriteBlockResponse(ctx, w, block["id"], 201, nil)
}
func (s *Service) updateLibraryBlock(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, err := libraryBlockInput(r, false)
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
	if !libraryOwnBlock(block, airline, true) {
		return platform.Error(404, "Block not found")
	}
	// Keep the relationships loaded before bulk writes in the PUT
	// response. Existing mapped rows reflect assignments, removed rows remain,
	// new rows and replaced competence links appear only on a subsequent GET.
	relations, err := libraryReadBlockRelations(ctx, tx, block["id"])
	if err != nil {
		return err
	}
	if body.Has("elements") {
		if err = libraryReplaceBlockElements(ctx, tx, block["id"], airline, allowed, body["elements"], relations.elements); err != nil {
			return err
		}
	}
	if body.Has("competence_ids") {
		if err = libraryReplaceBlockCompetences(ctx, tx, block["id"], airline, body["competence_ids"], true); err != nil {
			return err
		}
	}
	if body.Has("params") {
		if err = libraryReplaceBlockParams(ctx, tx, block, libraryRecord(body["params"])); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return s.libraryWriteBlockResponse(ctx, w, block["id"], 200, relations)
}
func (s *Service) archiveLibraryBlock(w http.ResponseWriter, r *http.Request, restore bool) error {
	user, err := s.Auth.Authenticate(r, "training:write")
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
	// Restore is allowed for archived rows; the source accidentally rejects
	// them. This bounded correction has its own expected-difference scenario.
	if !libraryOwnBlock(block, airline, !restore) {
		return platform.Error(404, "Block not found")
	}
	data := record{"archived_at": nil, "archived_by": nil}
	if !restore {
		data["archived_at"], data["archived_by"] = time.Now().UTC(), user.InternalID
	}
	if err = libraryUpdate(ctx, tx, "element_block", block, data); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if !restore {
		w.WriteHeader(204)
		return nil
	}
	return s.libraryWriteBlockResponse(ctx, w, block["id"], 200, nil)
}
