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
