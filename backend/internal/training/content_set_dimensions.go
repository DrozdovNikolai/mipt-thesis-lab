package training

import (
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/platform"
)

func contentSetDimension(label bool) (table, parameter, field, name string) {
	if label {
		return "scenario_content_set_label", "label_id", "label", "Label"
	}
	return "scenario_content_subcolumn", "subcolumn_id", "name", "Subcolumn"
}

func contentSetDimensionError(err error, name string) error {
	var dbErr *pgconn.PgError
	if errors.As(err, &dbErr) && strings.HasPrefix(dbErr.Code, "23") {
		return platform.Error(400, name+" already exists")
	}
	return err
}

func (s *Service) writeContentSetDimension(label, create bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		user, err := s.Auth.Authenticate(r, "training:write")
		if err != nil {
			return err
		}
		table, parameter, field, name := contentSetDimension(label)
		model := platform.Schema{Fields: []platform.Field{
			{Name: field, Kind: "string", Required: !label && create, Nullable: label || !create, Max: 255},
			{Name: "order_index", Alias: "orderIndex", Kind: "integer", AllowBigInteger: true, Nullable: true, NonNegative: true},
		}}
		params := []string{"content_set_id"}
		if !create {
			params = append(params, parameter)
		}
		path, body, err := libraryInput(r, &model, params...)
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
		set, err := scopedContentSet(ctx, tx, path["content_set_id"], airline, allowed)
		if err != nil {
			return err
		}
		var row record
		if create {
			order := body["order_index"]
			if order == nil {
				var next int64
				if err = tx.QueryRow(ctx, "SELECT coalesce(max(order_index),-1)+1 FROM "+table+" WHERE content_set_id=$1", set["id"]).Scan(&next); err != nil {
					return err
				}
				order = next
			}
			row, err = insertTrainingRow(ctx, tx, table, record{"content_set_id": set["id"], field: body[field], "order_index": order})
		} else {
			row, err = libraryFind(ctx, tx, table, path[parameter])
			if err != nil {
				return err
			}
			if row == nil || row.number("content_set_id") != set.number("id") {
				return platform.Error(404, name+" not found")
			}
			data := record(body)
			if data["order_index"] == nil {
				delete(data, "order_index")
			}
			err = libraryUpdate(ctx, tx, table, row, data)
		}
		if err != nil {
			return contentSetDimensionError(err, name)
		}
		if err = tx.Commit(ctx); err != nil {
			return contentSetDimensionError(err, name)
		}
		row, err = libraryFind(ctx, s.Auth.DB, table, row["id"])
		if err != nil {
			return err
		}
		value := row.project("id content_set_id order_index created_at updated_at " + field)
		if value["order_index"] == nil {
			return fmt.Errorf("invalid stored content order")
		}
		if label {
			value["scenarios"] = []record{}
		}
		status := 200
		if create {
			status = 201
		}
		platform.WriteJSON(w, status, commanderWire(value))
		return nil
	}
}

func (s *Service) deleteContentSetDimension(label bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		user, err := s.Auth.Authenticate(r, "training:write")
		if err != nil {
			return err
		}
		table, parameter, _, name := contentSetDimension(label)
		path, _, err := libraryInput(r, nil, "content_set_id", parameter)
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
		set, err := scopedContentSet(ctx, tx, path["content_set_id"], airline, allowed)
		if err != nil {
			return err
		}
		row, err := libraryFind(ctx, tx, table, path[parameter])
		if err != nil {
			return err
		}
		if row == nil || row.number("content_set_id") != set.number("id") {
			return platform.Error(404, name+" not found")
		}
		if _, err = tx.Exec(ctx, "DELETE FROM "+table+" WHERE id=$1", row["id"]); err != nil {
			return err
		}
		if err = tx.Commit(ctx); err != nil {
			return err
		}
		w.WriteHeader(204)
		return nil
	}
}
