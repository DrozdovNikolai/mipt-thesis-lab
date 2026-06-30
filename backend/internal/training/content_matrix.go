package training

import (
	"context"
	"fmt"
	"net/http"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

// Registered separately so the metadata/dimension and editing contracts can be
// brought through the migration harness as two bounded packets.
func (s *Service) registerContentMatrix(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/content-sets/{content_set_id}"
	for _, folder := range []bool{true, false} {
		_, parameter, relation, _, _ := contentMatrixResource(folder)
		mux.HandleFunc("POST "+p+"/"+relation, platform.Wrap(s.writeContentMatrixResource(folder, true)))
		mux.HandleFunc("PUT "+p+"/"+relation+"/{"+parameter+"}", platform.Wrap(s.writeContentMatrixResource(folder, false)))
		mux.HandleFunc("DELETE "+p+"/"+relation+"/{"+parameter+"}", platform.Wrap(s.deleteContentMatrixResource(folder)))
	}
	q := p + "/requirements/{requirement_id}/elements"
	mux.HandleFunc("POST "+q, platform.Wrap(s.writeContentRequirementElement(true)))
	mux.HandleFunc("PUT "+q+"/{requirement_element_id}", platform.Wrap(s.writeContentRequirementElement(false)))
	mux.HandleFunc("DELETE "+q+"/{requirement_element_id}", platform.Wrap(s.deleteContentRequirementElement))
	mux.HandleFunc("PUT "+p+"/cells", platform.Wrap(s.upsertContentCell))
	mux.HandleFunc("DELETE "+p+"/cells/{requirement_id}/{subcolumn_id}/{scenario_id}", platform.Wrap(s.deleteContentCell(false)))
	mux.HandleFunc("DELETE "+p+"/cells/by-label/{requirement_id}/{subcolumn_id}/{set_label_id}", platform.Wrap(s.deleteContentCell(true)))
}

type contentMatrixRequest struct {
	tx         pgx.Tx
	set        record
	path, body platform.Object
}

func (s *Service) contentMatrixInput(r *http.Request, model *platform.Schema, parameters ...string) (contentMatrixRequest, error) {
	var input contentMatrixRequest
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return input, err
	}
	input.path, input.body, err = libraryInput(r, model, append([]string{"content_set_id"}, parameters...)...)
	if err != nil {
		return input, err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return input, err
	}
	allowed, err := libraryAllowedAircraft(user)
	if err != nil {
		return input, err
	}
	input.tx, err = s.Auth.DB.Begin(r.Context())
	if err != nil {
		return input, err
	}
	input.set, err = scopedContentSet(r.Context(), input.tx, input.path["content_set_id"], airline, allowed)
	if err != nil {
		input.tx.Rollback(r.Context())
	}
	return input, err
}

func contentMatrixResource(folder bool) (table, parameter, relation, name, fields string) {
	if folder {
		return "scenario_content_folder", "folder_id", "folders", "Folder", "parent_id name order_index"
	}
	return "scenario_content_requirement", "requirement_id", "requirements", "Requirement", "folder_id topic_name order_index"
}

func contentMatrixRow(ctx context.Context, db runtimeDB, table string, id any, set record, message string, status int) (record, error) {
	row, err := libraryFind(ctx, db, table, id)
	if err != nil {
		return nil, err
	}
	if row == nil || row.number("content_set_id") != set.number("id") {
		return nil, platform.Error(status, message)
	}
	return row, nil
}

func contentRequirementElementDTO(ctx context.Context, db runtimeDB, row record) (record, error) {
	if row["order_index"] == nil {
		return nil, fmt.Errorf("invalid stored requirement element order")
	}
	element, err := libraryFind(ctx, db, "element", row["element_id"])
	if err != nil {
		return nil, err
	}
	value := row.project("id requirement_id element_id order_index created_at updated_at")
	value["element"], err = libraryElementDTO(element)
	return value, err
}

func (s *Service) writeContentMatrixResource(folder, create bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		table, parameter, _, name, fields := contentMatrixResource(folder)
		parent, title := "folder_id", "topic_name"
		if folder {
			parent, title = "parent_id", "name"
		}
		model := platform.Schema{Fields: []platform.Field{
			{Name: title, Alias: camelKey(title), Kind: "string", Required: create, Nullable: !create, Max: 255},
			{Name: parent, Alias: camelKey(parent), Kind: "integer", AllowBigInteger: true, Required: !folder && create, Nullable: folder || !create},
			{Name: "order_index", Alias: "orderIndex", Kind: "integer", AllowBigInteger: true, Nullable: true, NonNegative: true},
		}}
		// Requirement schemas declare folder_id before topic_name; preserve the
		// order of simultaneous validation errors in the HTTP response.
		if !folder {
			model.Fields[0], model.Fields[1] = model.Fields[1], model.Fields[0]
		}
		parameters := []string{}
		if !create {
			parameters = append(parameters, parameter)
		}
		input, err := s.contentMatrixInput(r, &model, parameters...)
		if err != nil {
			return err
		}
		ctx := r.Context()
		defer input.tx.Rollback(ctx)
		data := record(input.body)
		var row record
		if !create {
			row, err = contentMatrixRow(ctx, input.tx, table, input.path[parameter], input.set, name+" not found", 404)
			if err != nil {
				return err
			}
		}
		if create || input.body.Has(parent) {
			parentID := data[parent]
			if folder && parentID != nil && row != nil && librarySame(row["id"], parentID) {
				return platform.Error(400, "Invalid parent_id")
			}
			if !folder || parentID != nil {
				if _, err = contentMatrixRow(ctx, input.tx, "scenario_content_folder", parentID, input.set, "Invalid "+parent, 400); err != nil {
					return err
				}
			}
		}
		if !folder && (create || input.body.Has(title)) {
			data[title] = pythonTrim(input.body.String(title))
			if data[title] == "" {
				return platform.Error(400, "Topic name is required")
			}
		}
		if create {
			data["content_set_id"] = input.set["id"]
			if data["order_index"] == nil {
				var next int64
				if err = input.tx.QueryRow(ctx, "SELECT coalesce(max(order_index),-1)+1 FROM "+table+" WHERE content_set_id=$1 AND "+parent+" IS NOT DISTINCT FROM $2::bigint", input.set["id"], data[parent]).Scan(&next); err != nil {
					return err
				}
				data["order_index"] = next
			}
			row, err = insertTrainingRow(ctx, input.tx, table, data)
		} else {
			err = libraryUpdate(ctx, input.tx, table, row, data)
		}
		if err != nil {
			return err
		}
		if err = input.tx.Commit(ctx); err != nil {
			return err
		}
		row, err = libraryFind(ctx, s.Auth.DB, table, row["id"])
		if err != nil {
			return err
		}
		if row["order_index"] == nil {
			return fmt.Errorf("invalid stored content order")
		}
		value := row.project("id content_set_id created_at updated_at " + fields)
		if !folder {
			links := []record{}
			if !create {
				rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(l) FROM scenario_content_requirement_element l WHERE requirement_id=$1 ORDER BY order_index,id`, row["id"])
				if err != nil {
					return err
				}
				for _, link := range rows {
					item, err := contentRequirementElementDTO(ctx, s.Auth.DB, link)
					if err != nil {
						return err
					}
					links = append(links, item)
				}
			}
			value["elements"] = links
		}
		status := 200
		if create {
			status = 201
		}
		platform.WriteJSON(w, status, commanderWire(value))
		return nil
	}
}

func (s *Service) deleteContentMatrixResource(folder bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		table, parameter, _, name, _ := contentMatrixResource(folder)
		input, err := s.contentMatrixInput(r, nil, parameter)
		if err != nil {
			return err
		}
		ctx := r.Context()
		defer input.tx.Rollback(ctx)
		row, err := contentMatrixRow(ctx, input.tx, table, input.path[parameter], input.set, name+" not found", 404)
		if err != nil {
			return err
		}
		if _, err = input.tx.Exec(ctx, "DELETE FROM "+table+" WHERE id=$1", row["id"]); err != nil {
			return err
		}
		if err = input.tx.Commit(ctx); err != nil {
			return err
		}
		w.WriteHeader(204)
		return nil
	}
}
