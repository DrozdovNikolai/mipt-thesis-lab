package training

import (
	"fmt"
	"net/http"
	"time"

	"north55/backend/internal/platform"
)

func (s *Service) registerLibrary(mux *platform.Router) {
	s.registerLibraryBlocks(mux)
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("GET "+p+"/elements", platform.Wrap(s.listLibraryElements))
	mux.HandleFunc("POST "+p+"/elements", platform.Wrap(s.createLibraryElement))
	mux.HandleFunc("PUT "+p+"/elements/{element_id}", platform.Wrap(s.updateLibraryElement))
	mux.HandleFunc("DELETE "+p+"/elements/{element_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.archiveLibraryElement(w, r, false) }))
	mux.HandleFunc("POST "+p+"/elements/{element_id}/restore", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.archiveLibraryElement(w, r, true) }))
	for _, collection := range []libraryCollection{elementLibrary, blockLibrary} {
		folderPath, itemPath := "/folders", "/folder-items"
		if collection == blockLibrary {
			folderPath, itemPath = "/block-folders", "/block-folder-items"
		}
		mux.HandleFunc("GET "+p+folderPath, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.listLibraryFolders(w, r, collection) }))
		mux.HandleFunc("POST "+p+folderPath, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.createLibraryFolder(w, r, collection) }))
		mux.HandleFunc("PUT "+p+folderPath+"/{folder_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.updateLibraryFolder(w, r, collection) }))
		mux.HandleFunc("DELETE "+p+folderPath+"/{folder_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			return s.archiveLibraryFolder(w, r, collection, false)
		}))
		mux.HandleFunc("POST "+p+folderPath+"/{folder_id}/restore", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
			return s.archiveLibraryFolder(w, r, collection, true)
		}))
		mux.HandleFunc("GET "+p+itemPath, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.listLibraryItems(w, r, collection) }))
		mux.HandleFunc("POST "+p+itemPath, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.createLibraryItem(w, r, collection) }))
		mux.HandleFunc("POST "+p+itemPath+"/query", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.queryLibraryItems(w, r, collection) }))
		mux.HandleFunc("PUT "+p+itemPath+"/{item_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.updateLibraryItem(w, r, collection) }))
		mux.HandleFunc("DELETE "+p+itemPath+"/{item_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.deleteLibraryItem(w, r, collection) }))
	}
}

func libraryWire(row record) any {
	if raw, ok := row["archived_at"].(string); ok {
		if stamp, err := time.Parse(time.RFC3339Nano, raw); err == nil {
			row["archived_at"] = apiTime(&stamp)
		}
	}
	return commanderWire(row)
}

func libraryElementDTO(row record) (any, error) {
	if row == nil {
		return nil, fmt.Errorf("element disappeared after commit")
	}
	if row["default_duration_minutes"] != nil && row.number("default_duration_minutes") < 0 {
		return nil, fmt.Errorf("invalid stored element duration")
	}
	return libraryWire(row.project("id name default_duration_minutes severity airline_id aircraft_id archived_by archived_at created_at updated_at")), nil
}

func libraryQuery(r *http.Request) (platform.Object, error) {
	return platform.QueryObject(r.URL.Query(), libraryAircraftField(), platform.Field{Name: "include_archived", Alias: "includeArchived", Kind: "boolean", Default: false})
}

func (s *Service) listLibraryElements(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := libraryQuery(r)
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
	rows, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(e) FROM element e WHERE airline_id=$1 AND aircraft_id=ANY($2::bigint[]) AND ($3 OR archived_at IS NULL) ORDER BY id`, airline, aircraft, q.Bool("include_archived"))
	if err != nil {
		return err
	}
	items := []any{}
	for _, row := range rows {
		item, e := libraryElementDTO(row)
		if e != nil {
			return e
		}
		items = append(items, item)
	}
	platform.WriteJSON(w, 200, items)
	return nil
}

func (s *Service) createLibraryElement(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, libraryElementSchema(true))
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
	aircraft, err := libraryAircraft(ctx, tx, user, body["aircraft_id"], true, body["aircraft_id"] == nil)
	if err != nil {
		return err
	}
	row := record(body).project("name default_duration_minutes severity")
	row["airline_id"], row["aircraft_id"] = airline, aircraft[0]
	created, err := insertTrainingRow(ctx, tx, "element", row)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	created, err = libraryFind(ctx, s.Auth.DB, "element", created["id"])
	if err != nil {
		return err
	}
	dto, err := libraryElementDTO(created)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, dto)
	return nil
}

func (s *Service) updateLibraryElement(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := libraryElementSchema(false)
	path, body, err := libraryInput(r, &schema, "element_id")
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
	row, err := libraryFind(ctx, tx, "element", path["element_id"])
	if err != nil {
		return err
	}
	if err = libraryRequired(airline, allowed, row, true, "Element not found"); err != nil {
		return err
	}
	if body.Has("aircraft_id") {
		ids, e := libraryAircraft(ctx, tx, user, body["aircraft_id"], true, false)
		if e != nil {
			return e
		}
		body["aircraft_id"] = ids[0]
	}
	if err = libraryUpdate(ctx, tx, "element", row, record(body)); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = libraryFind(ctx, s.Auth.DB, "element", row["id"])
	if err != nil {
		return err
	}
	dto, err := libraryElementDTO(row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, dto)
	return nil
}

func (s *Service) archiveLibraryElement(w http.ResponseWriter, r *http.Request, restore bool) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "element_id")
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
	row, err := libraryFind(ctx, tx, "element", path["element_id"])
	if err != nil {
		return err
	}
	if err = libraryRequired(airline, allowed, row, false, "Element not found"); err != nil {
		return err
	}
	if restore || row["archived_at"] == nil {
		changes := record{"archived_at": nil, "archived_by": nil}
		if !restore {
			changes["archived_at"], changes["archived_by"] = time.Now().UTC(), user.InternalID
		}
		if err = libraryUpdate(ctx, tx, "element", row, changes); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if !restore {
		w.WriteHeader(204)
		return nil
	}
	row, err = libraryFind(ctx, s.Auth.DB, "element", row["id"])
	if err != nil {
		return err
	}
	dto, err := libraryElementDTO(row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, dto)
	return nil
}
