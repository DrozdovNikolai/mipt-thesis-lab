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

func (s *Service) readContentSetMatrix(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
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
	row, err := scopedContentSet(r.Context(), s.Auth.DB, path["content_set_id"], airline, allowed)
	if err != nil {
		return err
	}
	value, err := contentSetMatrix(r.Context(), s.Auth.DB, row)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(value))
	return nil
}

func contentSetMatrix(ctx context.Context, db runtimeDB, set record) (record, error) {
	value, err := contentSetDTO(ctx, db, set)
	if err != nil {
		return nil, err
	}
	out := record{"content_set": value}
	for _, relation := range []struct{ name, table, order, fields string }{
		{"labels", "scenario_content_set_label", "order_index,id", "order_index label"},
		{"folders", "scenario_content_folder", "coalesce(parent_id,0),order_index,id", "parent_id name order_index"},
		{"requirements", "scenario_content_requirement", "folder_id,order_index,id", "folder_id topic_name order_index"},
		{"subcolumns", "scenario_content_subcolumn", "order_index,id", "name order_index"},
		{"cells", "scenario_content_cell", "", "requirement_id set_label_id subcolumn_id value"},
	} {
		query := "SELECT to_jsonb(t) FROM " + relation.table + " t WHERE content_set_id=$1"
		if relation.order != "" {
			query += " ORDER BY " + relation.order
		}
		rows, err := queryRecords(ctx, db, query, set["id"])
		if err != nil {
			return nil, err
		}
		for i, source := range rows {
			if relation.name != "cells" && source["order_index"] == nil {
				return nil, fmt.Errorf("invalid stored content order")
			}
			row := source.project("id content_set_id created_at updated_at " + relation.fields)
			rows[i] = row
			if relation.name == "labels" {
				links, err := queryRecords(ctx, db, `SELECT to_jsonb(x)||jsonb_build_object('scenario',to_jsonb(s)||jsonb_build_object('aircraft_code',a.code))
FROM scenario_content_set_label_scenario x LEFT JOIN scenario s ON s.id=x.scenario_id
LEFT JOIN aircraft_airline a ON a.id=s.aircraft_id WHERE x.label_id=$1 AND s.deleted_at IS NULL ORDER BY x.id`, row["id"])
				if err != nil {
					return nil, err
				}
				for j, sourceLink := range links {
					link := sourceLink.project("id label_id scenario_id created_at scenario")
					links[j] = link
					if scenario := link.object("scenario"); scenario != nil {
						link["scenario"] = scenarioWire(scenario.project("id aircraft_id aircraft_code code title status archived_by archived_at deleted_by deleted_at"))
					}
				}
				row["scenarios"] = links
			}
			if relation.name == "requirements" {
				links, err := queryRecords(ctx, db, `SELECT to_jsonb(x)||jsonb_build_object('element',to_jsonb(e)) FROM scenario_content_requirement_element x
LEFT JOIN element e ON e.id=x.element_id WHERE x.requirement_id=$1 ORDER BY x.order_index,x.id`, row["id"])
				if err != nil {
					return nil, err
				}
				for j, sourceLink := range links {
					link := sourceLink.project("id requirement_id element_id order_index element created_at updated_at")
					if link["order_index"] == nil {
						return nil, fmt.Errorf("invalid stored requirement element order")
					}
					links[j] = link
					link["element"], err = libraryElementDTO(link.object("element"))
					if err != nil {
						return nil, err
					}
				}
				row["elements"] = links
			}
		}
		out[relation.name] = rows
	}
	return out, nil
}
