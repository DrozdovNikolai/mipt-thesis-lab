package training

import (
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func (s *Service) upsertContentCell(w http.ResponseWriter, r *http.Request) error {
	model := platform.Schema{Fields: []platform.Field{
		{Name: "requirement_id", Alias: "requirementId", Kind: "integer", AllowBigInteger: true, Required: true},
		{Name: "subcolumn_id", Alias: "subcolumnId", Kind: "integer", AllowBigInteger: true, Required: true},
		{Name: "set_label_id", Alias: "setLabelId", Kind: "integer", AllowBigInteger: true, Required: true},
		{Name: "value", Kind: "boolean", Default: false},
	}}
	input, err := s.contentMatrixInput(r, &model)
	if err != nil {
		return err
	}
	ctx := r.Context()
	defer input.tx.Rollback(ctx)
	for _, item := range []struct{ table, field string }{{"scenario_content_requirement", "requirement_id"}, {"scenario_content_subcolumn", "subcolumn_id"}, {"scenario_content_set_label", "set_label_id"}} {
		if _, err = contentMatrixRow(ctx, input.tx, item.table, input.body[item.field], input.set, "Invalid "+item.field, 400); err != nil {
			return err
		}
	}
	row, err := queryRecord(ctx, input.tx, `SELECT to_jsonb(c) FROM scenario_content_cell c WHERE content_set_id=$1 AND requirement_id=$2 AND set_label_id=$3 AND subcolumn_id=$4 FOR UPDATE`, input.set["id"], input.body["requirement_id"], input.body["set_label_id"], input.body["subcolumn_id"])
	if errors.Is(err, pgx.ErrNoRows) {
		// The initial lookup cannot lock a missing row. Concurrent creators
		// therefore arbitrate through the existing named unique constraint.
		// Keep no-op timestamps unchanged and never update a corrupt cell
		// whose content_set_id disagrees with the validated dimensions.
		row, err = queryRecord(ctx, input.tx, `INSERT INTO scenario_content_cell AS c
(content_set_id,requirement_id,set_label_id,subcolumn_id,value) VALUES($1,$2,$3,$4,$5)
ON CONFLICT ON CONSTRAINT uq_content_cell DO UPDATE
SET value=EXCLUDED.value,updated_at=CASE WHEN c.value IS DISTINCT FROM EXCLUDED.value THEN now() ELSE c.updated_at END
WHERE c.content_set_id=EXCLUDED.content_set_id RETURNING to_jsonb(c)`,
			input.set["id"], input.body["requirement_id"], input.body["set_label_id"], input.body["subcolumn_id"], input.body["value"])
	} else if err == nil {
		err = libraryUpdate(ctx, input.tx, "scenario_content_cell", row, record{"value": input.body["value"]})
	}
	if err != nil {
		return err
	}
	// Read the response while holding the row lock, so a later successful
	// PUT cannot replace this request's value before it is acknowledged.
	row, err = libraryFind(ctx, input.tx, "scenario_content_cell", row["id"])
	if err != nil {
		return err
	}
	if err = input.tx.Commit(ctx); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(row.project("id content_set_id requirement_id set_label_id subcolumn_id value created_at updated_at")))
	return nil
}

func (s *Service) deleteContentCell(byLabel bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		field := "scenario_id"
		if byLabel {
			field = "set_label_id"
		}
		input, err := s.contentMatrixInput(r, nil, "requirement_id", "subcolumn_id", field)
		if err != nil {
			return err
		}
		ctx := r.Context()
		defer input.tx.Rollback(ctx)
		var labelID any
		if byLabel {
			label, err := contentMatrixRow(ctx, input.tx, "scenario_content_set_label", input.path[field], input.set, "Cell not found", 404)
			if err != nil {
				return err
			}
			labelID = label["id"]
		} else {
			labels, err := queryRecords(ctx, input.tx, `SELECT jsonb_build_object('id',l.id) FROM scenario_content_set_label l
JOIN scenario_content_set_label_scenario x ON x.label_id=l.id JOIN scenario s ON s.id=x.scenario_id
WHERE l.content_set_id=$1 AND x.scenario_id=$2 AND s.deleted_at IS NULL`, input.set["id"], input.path[field])
			if err != nil {
				return err
			}
			if len(labels) == 0 {
				return platform.Error(404, "Cell not found")
			}
			if len(labels) > 1 {
				return platform.Error(400, "Scenario is linked to multiple labels")
			}
			labelID = labels[0]["id"]
		}
		subcolumn, err := contentMatrixRow(ctx, input.tx, "scenario_content_subcolumn", input.path["subcolumn_id"], input.set, "Cell not found", 404)
		if err != nil {
			return err
		}
		cell, err := queryRecord(ctx, input.tx, `SELECT to_jsonb(c) FROM scenario_content_cell c WHERE content_set_id=$1 AND requirement_id=$2 AND set_label_id=$3 AND subcolumn_id=$4`, input.set["id"], input.path["requirement_id"], labelID, subcolumn["id"])
		if errors.Is(err, pgx.ErrNoRows) {
			return platform.Error(404, "Cell not found")
		}
		if err != nil {
			return err
		}
		if _, err = input.tx.Exec(ctx, `DELETE FROM scenario_content_cell WHERE id=$1`, cell["id"]); err != nil {
			return err
		}
		if err = input.tx.Commit(ctx); err != nil {
			return err
		}
		w.WriteHeader(204)
		return nil
	}
}
