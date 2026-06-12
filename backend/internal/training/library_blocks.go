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
