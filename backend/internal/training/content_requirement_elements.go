package training

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/platform"
)

func contentRequirementLink(ctx context.Context, db runtimeDB, input contentMatrixRequest) (record, error) {
	link, err := libraryFind(ctx, db, "scenario_content_requirement_element", input.path["requirement_element_id"])
	if err != nil {
		return nil, err
	}
	if link == nil {
		return nil, platform.Error(404, "Requirement element not found")
	}
	requirement, err := libraryFind(ctx, db, "scenario_content_requirement", link["requirement_id"])
	if err != nil {
		return nil, err
	}
	if requirement == nil || requirement.number("content_set_id") != input.set.number("id") || !librarySame(requirement["id"], input.path["requirement_id"]) {
		return nil, platform.Error(404, "Requirement element not found")
	}
	return link, nil
}

func (s *Service) writeContentRequirementElement(create bool) func(http.ResponseWriter, *http.Request) error {
	return func(w http.ResponseWriter, r *http.Request) error {
		fields := []platform.Field{{Name: "order_index", Alias: "orderIndex", Kind: "integer", AllowBigInteger: true, Nullable: true, NonNegative: true}}
		parameters := []string{"requirement_id"}
		if create {
			fields = append([]platform.Field{{Name: "element_id", Alias: "elementId", Kind: "integer", AllowBigInteger: true, Required: true}}, fields...)
		} else {
			parameters = append(parameters, "requirement_element_id")
		}
		input, err := s.contentMatrixInput(r, &platform.Schema{Fields: fields}, parameters...)
		if err != nil {
			return err
		}
		ctx := r.Context()
		defer input.tx.Rollback(ctx)
		var row record
		if create {
			requirement, err := contentMatrixRow(ctx, input.tx, "scenario_content_requirement", input.path["requirement_id"], input.set, "Requirement not found", 404)
			if err != nil {
				return err
			}
			if err = libraryValidateBlockElementIDs(ctx, input.tx, input.set.number("airline_id"), []int64{input.set.number("aircraft_id")}, []any{input.body["element_id"]}); err != nil {
				return err
			}
			element, err := libraryFind(ctx, input.tx, "element", input.body["element_id"])
			if err != nil {
				return err
			}
			if element == nil {
				return platform.Error(400, "Invalid element_id")
			}
			data := record(input.body)
			data["requirement_id"] = requirement["id"]
			if data["order_index"] == nil {
				var next int64
				if err = input.tx.QueryRow(ctx, `SELECT coalesce(max(order_index),-1)+1 FROM scenario_content_requirement_element WHERE requirement_id=$1`, requirement["id"]).Scan(&next); err != nil {
					return err
				}
				data["order_index"] = next
			}
			row, err = insertTrainingRow(ctx, input.tx, "scenario_content_requirement_element", data)
			if err != nil {
				return contentRequirementInsertError(err)
			}
		} else {
			row, err = contentRequirementLink(ctx, input.tx, input)
			if err != nil {
				return err
			}
			if err = libraryUpdate(ctx, input.tx, "scenario_content_requirement_element", row, record(input.body)); err != nil {
				return err
			}
		}
		if err = input.tx.Commit(ctx); err != nil {
			if create {
				return contentRequirementInsertError(err)
			}
			return err
		}
		row, err = libraryFind(ctx, s.Auth.DB, "scenario_content_requirement_element", row["id"])
		if err != nil {
			return err
		}
		value, err := contentRequirementElementDTO(ctx, s.Auth.DB, row)
		if err != nil {
			return err
		}
		status := 200
		if create {
			status = 201
		}
		platform.WriteJSON(w, status, commanderWire(value))
		return nil
	}
}

func contentRequirementInsertError(err error) error {
	var dbErr *pgconn.PgError
	if errors.As(err, &dbErr) && strings.HasPrefix(dbErr.Code, "23") {
		return platform.Error(400, "Element already in topic")
	}
	return err
}

func (s *Service) deleteContentRequirementElement(w http.ResponseWriter, r *http.Request) error {
	input, err := s.contentMatrixInput(r, nil, "requirement_id", "requirement_element_id")
	if err != nil {
		return err
	}
	ctx := r.Context()
	defer input.tx.Rollback(ctx)
	row, err := contentRequirementLink(ctx, input.tx, input)
	if err != nil {
		return err
	}
	if _, err = input.tx.Exec(ctx, `DELETE FROM scenario_content_requirement_element WHERE id=$1`, row["id"]); err != nil {
		return err
	}
	if err = input.tx.Commit(ctx); err != nil {
		return err
	}
	w.WriteHeader(204)
	return nil
}
