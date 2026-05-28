package training

import (
	"errors"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func indicatorSchema(create bool) platform.Schema {
	fields := []platform.Field{
		{Name: "code", Kind: "string", Required: create, Nullable: !create, Max: 50},
		{Name: "short_name", Alias: "shortName", Kind: "string", Nullable: true, Max: 255},
		{Name: "name", Kind: "string", Required: create, Nullable: !create, Max: 255},
	}
	if !create {
		fields = append(fields, platform.Field{Name: "order_index", Alias: "orderIndex", Kind: "integer", NonNegative: true, Nullable: true})
	}
	return platform.Schema{Fields: fields}
}

func (s *Service) manageIndicators(w http.ResponseWriter, r *http.Request) error {
	privilege := "training:write"
	if r.Method == "GET" {
		privilege = "training:read"
	}
	user, err := s.Auth.Authenticate(r, privilege)
	if err != nil {
		return err
	}
	names := []string{"competence_id"}
	var schema *platform.Schema
	if r.Method == "POST" || r.Method == "PUT" {
		value := indicatorSchema(r.Method == "POST")
		schema = &value
	}
	if r.Method == "PUT" || r.Method == "DELETE" {
		names = append(names, "indicator_id")
	}
	path, body, err := catalogInput(r, schema, names...)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	compID, indicatorID := path.Int("competence_id"), path.Int("indicator_id")
	if _, err = activeCompetence(r.Context(), tx, airline, compID); err != nil {
		return err
	}
	if r.Method == "GET" {
		rows, err := queryRecords(r.Context(), tx, "SELECT to_jsonb(b) FROM behavioural_indicator b WHERE competence_id=$1 AND retired_at IS NULL ORDER BY order_index,id", compID)
		if err != nil {
			return err
		}
		items := []record{}
		for _, row := range rows {
			if !helperPositive(row.text("code")) {
				items = append(items, row.project("id code short_name name order_index created_at updated_at"))
			}
		}
		platform.WriteJSON(w, 200, commanderWire(items))
		return nil
	}
	var row record
	status := 200
	if r.Method != "POST" {
		row, err = queryRecord(r.Context(), tx, "SELECT to_jsonb(b) FROM behavioural_indicator b WHERE competence_id=$1 AND id=$2 AND retired_at IS NULL", compID, indicatorID)
		if errors.Is(err, pgx.ErrNoRows) {
			return platform.Error(404, "Behavioural indicator not found")
		}
		if err != nil {
			return err
		}
	}
	if r.Method == "DELETE" {
		_, err = tx.Exec(r.Context(), "UPDATE behavioural_indicator SET retired_at=$1,updated_at=now() WHERE id=$2", time.Now().UTC(), indicatorID)
	} else {
		code := row.text("code")
		if body.Has("code") {
			code = body.String("code")
		}
		if helperPositive(code) {
			return platform.Error(400, "Positive comment is a report-level sentiment, not a behavioural indicator")
		}
		if r.Method == "POST" {
			status = 201
			if err = catalogUniqueCode(r.Context(), tx, true, compID, nil, code); err != nil {
				return err
			}
			var order int64
			if err = tx.QueryRow(r.Context(), "SELECT coalesce(max(order_index),-1)::bigint+1 FROM behavioural_indicator WHERE competence_id=$1", compID).Scan(&order); err != nil {
				return err
			}
			row, err = queryRecord(r.Context(), tx, `INSERT INTO behavioural_indicator(competence_id,code,short_name,name,order_index) VALUES($1,$2,$3,$4,$5) RETURNING to_jsonb(behavioural_indicator)`, compID, body["code"], body["short_name"], body["name"], order)
		} else {
			if body["code"] != nil && body["code"] != row["code"] {
				if err = catalogUniqueCode(r.Context(), tx, true, compID, indicatorID, code); err != nil {
					return err
				}
			}
			row, err = updateCatalogRow(r.Context(), tx, "behavioural_indicator", row, body, []string{"code", "short_name", "name", "order_index"})
		}
	}
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	if r.Method == "DELETE" {
		w.WriteHeader(204)
	} else {
		platform.WriteJSON(w, status, commanderWire(row.project("id code short_name name order_index created_at updated_at")))
	}
	return nil
}
