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

func (s *Service) createLibraryFolder(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, libraryFolderSchema(true))
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
	kind := body["library_kind"]
	if c == blockLibrary {
		kind, err = libraryParseBlockKind(kind)
		if err != nil {
			return err
		}
	}
	aircraftRef := body["aircraft_id"]
	if body["parent_id"] != nil {
		parent, e := libraryFind(ctx, tx, c.folderTable(), body["parent_id"])
		if e != nil {
			return e
		}
		if parent == nil || parent["airline_id"] == nil || parent.number("airline_id") != airline || parent["archived_at"] != nil {
			return platform.Error(400, "Invalid parent folder")
		}
		if aircraftRef != nil {
			ids, e := libraryAircraft(ctx, tx, user, aircraftRef, true, false)
			if e != nil {
				return e
			}
			if ids[0] != parent.number("aircraft_id") {
				return platform.Error(400, "aircraft_id must match parent folder aircraft_id")
			}
		}
		if c == blockLibrary {
			if body["library_kind"] != nil && kind != libraryBlockKind(parent["library_kind"]) {
				return platform.Error(400, "Parent folder library kind mismatch")
			}
			kind = libraryBlockKind(parent["library_kind"])
		}
		aircraftRef = parent.number("aircraft_id")
	}
	aircraft, err := libraryAircraft(ctx, tx, user, aircraftRef, true, false)
	if err != nil {
		return err
	}
	order := body["order_index"]
	if order == nil {
		order, err = libraryFolderOrder(ctx, tx, c, airline, aircraft[0], body["parent_id"], kind)
		if err != nil {
			return err
		}
	}
	row := record(body).project("name color_hex parent_id")
	row["airline_id"], row["aircraft_id"], row["order_index"] = airline, aircraft[0], order
	if c == blockLibrary {
		row["library_kind"] = kind
	}
	row, err = insertTrainingRow(ctx, tx, c.folderTable(), row)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = libraryFind(ctx, s.Auth.DB, c.folderTable(), row["id"])
	if err != nil {
		return err
	}
	dto, err := libraryFolderDTO(ctx, s.Auth.DB, row, row["library_kind"])
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, dto)
	return nil
}

func (s *Service) updateLibraryFolder(w http.ResponseWriter, r *http.Request, c libraryCollection) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := libraryFolderSchema(false)
	path, body, err := libraryInput(r, &schema, "folder_id")
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
	row, err := libraryFind(ctx, tx, c.folderTable(), path["folder_id"])
	if err != nil {
		return err
	}
	if err = libraryRequired(airline, allowed, row, true, "Folder not found"); err != nil {
		return err
	}
	if body["order_index"] == nil {
		delete(body, "order_index")
	}
	if c == blockLibrary && body.Has("library_kind") {
		nextKind, e := libraryParseBlockKind(body["library_kind"])
		if e != nil {
			return e
		}
		if nextKind != libraryBlockKind(row["library_kind"]) {
			return platform.Error(400, "library_kind cannot be changed")
		}
		delete(body, "library_kind")
	}
	nextAircraft := row.number("aircraft_id")
	if body.Has("aircraft_id") {
		ids, e := libraryAircraft(ctx, tx, user, body["aircraft_id"], true, false)
		if e != nil {
			return e
		}
		nextAircraft = ids[0]
		body["aircraft_id"] = nextAircraft
	}
	nextParent := row["parent_id"]
	if body.Has("parent_id") {
		nextParent = body["parent_id"]
	}
	if nextParent != nil {
		parent, e := libraryFind(ctx, tx, c.folderTable(), nextParent)
		if e != nil {
			return e
		}
		if parent == nil || parent["airline_id"] == nil || parent.number("airline_id") != airline || parent["archived_at"] != nil {
			return platform.Error(400, "Invalid parent folder")
		}
		if parent.number("aircraft_id") != nextAircraft {
			return platform.Error(400, "Parent folder aircraft_id mismatch")
		}
		if c == blockLibrary && libraryBlockKind(parent["library_kind"]) != libraryBlockKind(row["library_kind"]) {
			return platform.Error(400, "Parent folder library kind mismatch")
		}
	}
	if body.Has("parent_id") && !body.Has("order_index") && !librarySame(nextParent, row["parent_id"]) {
		body["order_index"], err = libraryFolderOrder(ctx, tx, c, airline, nextAircraft, nextParent, libraryBlockKind(row["library_kind"]))
		if err != nil {
			return err
		}
	}
	// ElementFolder has no library_kind column. The handler retains this transient
	// attribute in the PUT response but does not persist it or change updated_at.
	kind := body["library_kind"]
	if c == blockLibrary {
		kind = row["library_kind"]
	}
	delete(body, "library_kind")
	if err = libraryUpdate(ctx, tx, c.folderTable(), row, record(body)); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = libraryFind(ctx, s.Auth.DB, c.folderTable(), row["id"])
	if err != nil {
		return err
	}
	dto, err := libraryFolderDTO(ctx, s.Auth.DB, row, kind)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, dto)
	return nil
}
