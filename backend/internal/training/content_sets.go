package training

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"north55/backend/internal/platform"
)

func (s *Service) registerContentSets(mux *platform.Router) {
	s.registerContentMatrix(mux)
	p := s.Auth.Config.APIPrefix + "/training/content-sets"
	mux.HandleFunc("GET "+p, platform.Wrap(s.listContentSets))
	mux.HandleFunc("POST "+p, platform.Wrap(s.createContentSet))
	mux.HandleFunc("GET "+p+"/summary", platform.Wrap(s.listContentSetSummary))
	mux.HandleFunc("POST "+p+"/{content_set_id}/duplicate", platform.Wrap(s.duplicateContentSet))
	mux.HandleFunc("GET "+p+"/{content_set_id}", platform.Wrap(s.readContentSetMatrix))
	mux.HandleFunc("PUT "+p+"/{content_set_id}", platform.Wrap(s.updateContentSet))
	mux.HandleFunc("DELETE "+p+"/{content_set_id}", platform.Wrap(s.deleteContentSet))
	for _, label := range []bool{false, true} {
		relation, parameter := "subcolumns", "subcolumn_id"
		if label {
			relation, parameter = "labels", "label_id"
		}
		mux.HandleFunc("POST "+p+"/{content_set_id}/"+relation, platform.Wrap(s.writeContentSetDimension(label, true)))
		mux.HandleFunc("PUT "+p+"/{content_set_id}/"+relation+"/{"+parameter+"}", platform.Wrap(s.writeContentSetDimension(label, false)))
		mux.HandleFunc("DELETE "+p+"/{content_set_id}/"+relation+"/{"+parameter+"}", platform.Wrap(s.deleteContentSetDimension(label)))
	}
}

func contentSetSchema(create bool) platform.Schema {
	return platform.Schema{Fields: []platform.Field{
		libraryAircraftField(),
		{Name: "name", Kind: "string", Required: create, Nullable: !create, Max: 255},
		{Name: "valid_from", Alias: "validFrom", Kind: "datetime", Nullable: true},
		{Name: "valid_to", Alias: "validTo", Kind: "datetime", Nullable: true},
	}}
}

func contentSetDates(row record) {
	for _, field := range []string{"valid_from", "valid_to"} {
		if stamp, ok := row[field].(time.Time); ok {
			row[field] = stamp.UTC().Truncate(time.Microsecond)
		}
	}
}

func contentSetDTO(ctx context.Context, db runtimeDB, row record) (record, error) {
	aircraft, err := libraryFind(ctx, db, "aircraft_airline", row["aircraft_id"])
	if err != nil {
		return nil, err
	}
	out := row.project("id airline_id aircraft_id name valid_from valid_to created_by updated_by created_at updated_at")
	out["aircraft_code"] = aircraft["code"]
	for _, field := range []string{"valid_from", "valid_to"} {
		if value, ok := out[field].(string); ok {
			if stamp, err := time.Parse(time.RFC3339Nano, value); err == nil {
				out[field] = apiTime(&stamp)
			}
		}
	}
	return out, nil
}

func scopedContentSet(ctx context.Context, db runtimeDB, id any, airline int64, aircraft []int64) (record, error) {
	row, err := libraryFind(ctx, db, "scenario_content_set", id)
	if err != nil {
		return nil, err
	}
	if row == nil || row.number("airline_id") != airline || !libraryContains(aircraft, row.number("aircraft_id")) {
		return nil, platform.Error(404, "Content set not found")
	}
	return row, nil
}

func (s *Service) listContentSets(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	query, err := platform.QueryObject(r.URL.Query(), libraryAircraftField())
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aircraft, err := libraryAircraft(r.Context(), s.Auth.DB, user, query["aircraft_id"], false, false)
	if err != nil {
		return err
	}
	rows, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(c) FROM scenario_content_set c WHERE airline_id=$1 AND aircraft_id=ANY($2::bigint[]) ORDER BY aircraft_id,name,id`, airline, aircraft)
	if err != nil {
		return err
	}
	out := []record{}
	for _, row := range rows {
		value, err := contentSetDTO(r.Context(), s.Auth.DB, row)
		if err != nil {
			return err
		}
		out = append(out, value)
	}
	platform.WriteJSON(w, 200, commanderWire(out))
	return nil
}

func (s *Service) createContentSet(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, contentSetSchema(true))
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	aircraft, err := libraryAircraft(ctx, s.Auth.DB, user, body["aircraft_id"], body["aircraft_id"] != nil, body["aircraft_id"] == nil)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	data := record(body).project("name valid_from valid_to")
	data["airline_id"], data["aircraft_id"], data["created_by"], data["updated_by"] = airline, aircraft[0], user.InternalID, user.InternalID
	contentSetDates(data)
	row, err := insertTrainingRow(ctx, tx, "scenario_content_set", data)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	value, err := contentSetDTO(ctx, s.Auth.DB, row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, commanderWire(value))
	return nil
}

func (s *Service) updateContentSet(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	model := contentSetSchema(false)
	path, body, err := libraryInput(r, &model, "content_set_id")
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
	row, err := scopedContentSet(ctx, tx, path["content_set_id"], airline, allowed)
	if err != nil {
		return err
	}
	data := record(body)
	if value, exists := data["aircraft_id"]; exists {
		aircraft, err := libraryAircraft(ctx, tx, user, value, true, false)
		if err != nil {
			return err
		}
		data["aircraft_id"] = aircraft[0]
	}
	data["updated_by"] = user.InternalID
	contentSetDates(data)
	for _, field := range []string{"valid_from", "valid_to"} {
		if stamp, ok := data[field].(time.Time); ok {
			if previous, err := time.Parse(time.RFC3339Nano, row.text(field)); err == nil && stamp.Equal(previous) {
				delete(data, field)
			}
		}
	}
	if err = libraryUpdate(ctx, tx, "scenario_content_set", row, data); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	row, err = libraryFind(ctx, s.Auth.DB, "scenario_content_set", row["id"])
	if err != nil {
		return err
	}
	value, err := contentSetDTO(ctx, s.Auth.DB, row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(value))
	return nil
}

func (s *Service) deleteContentSet(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, err := libraryInput(r, nil, "content_set_id")
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
	row, err := scopedContentSet(ctx, tx, path["content_set_id"], airline, allowed)
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM scenario_content_set WHERE id=$1`, row["id"]); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
