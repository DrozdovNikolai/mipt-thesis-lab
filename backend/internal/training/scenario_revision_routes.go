package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func (s *Service) registerScenarioRevisions(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/scenarios/{scenario_id}/revisions"
	mux.HandleFunc("GET "+p, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.readScenarioRevisions(w, r, false, false) }))
	mux.HandleFunc("GET "+p+"/snapshots", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.readScenarioRevisions(w, r, true, false) }))
	mux.HandleFunc("GET "+p+"/{revision_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.readScenarioRevisions(w, r, true, true) }))
	mux.HandleFunc("POST "+p, platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.writeScenarioRevision(w, r, false) }))
	mux.HandleFunc("POST "+p+"/batch", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error { return s.writeScenarioRevision(w, r, true) }))
}

func (s *Service) revisionScenario(ctx context.Context, db runtimeDB, user *auth.User, id any, archived bool) (record, error) {
	airline, err := commanderAirline(user)
	if err != nil {
		return nil, err
	}
	aircraft, err := libraryAllowedAircraft(user)
	if err != nil {
		return nil, err
	}
	return scenarioGet(ctx, db, id, airline, aircraft, archived, false)
}

func scenarioRevisionDTO(row record, snapshot bool) (any, error) {
	if row == nil || !libraryContainsString(scenarioRevisionKinds, row.text("kind")) || (row["action"] != nil && !libraryContainsString(scenarioRevisionActions, row.text("action"))) {
		return nil, fmt.Errorf("invalid stored scenario revision metadata")
	}
	value := row.project("id scenario_id revision_number " + scenarioRevisionMetadata + " signature parent_revision_id created_at")
	if snapshot {
		var fatal error
		model := scenarioSnapshotSchema(nil, &fatal)
		payload, err := platform.ValidateObject(row["snapshot_json"], nil, model)
		if err != nil || fatal != nil {
			// Stored payload validation is an internal response failure, not a
			// request validation error with a public Pydantic location.
			return nil, fmt.Errorf("invalid stored scenario revision snapshot: %v %v", err, fatal)
		}
		value["snapshot"] = scenarioModelDefaults(payload, model)
	}
	return commanderWire(value), nil
}

func (s *Service) readScenarioRevisions(w http.ResponseWriter, r *http.Request, snapshots, single bool) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	names := []string{"scenario_id"}
	if single {
		names = append(names, "revision_id")
	}
	path, _, pathErr := libraryInput(r, nil, names...)
	limit := int64(200)
	if snapshots {
		limit = 220
	}
	if !single {
		q, queryErr := platform.QueryObject(r.URL.Query(), platform.Field{Name: "limit", Kind: "integer", Default: limit, AllowBigInteger: true})
		if pathErr != nil && queryErr != nil {
			var p, q *platform.APIError
			if errors.As(pathErr, &p) && errors.As(queryErr, &q) && p.Code == "VALIDATION_ERROR" && q.Code == "VALIDATION_ERROR" {
				p.Extra["details"] = append(p.Extra["details"].([]any), q.Extra["details"].([]any)...)
			}
		}
		if pathErr != nil {
			return pathErr
		}
		if queryErr != nil {
			return queryErr
		}
		limit = q.Int("limit")
		if q.CompareInteger("limit", 1) < 0 {
			limit = 1
		} else if q.CompareInteger("limit", 500) > 0 {
			limit = 500
		}
	} else if pathErr != nil {
		return pathErr
	}
	ctx := r.Context()
	scenario, err := s.revisionScenario(ctx, s.Auth.DB, user, path["scenario_id"], true)
	if err != nil {
		return err
	}
	if single {
		row, err := libraryFind(ctx, s.Auth.DB, "scenario_revision", path["revision_id"])
		if err != nil {
			return err
		}
		if row == nil || row.number("scenario_id") != scenario.number("id") {
			return platform.Error(404, "Scenario revision not found")
		}
		value, err := scenarioRevisionDTO(row, true)
		if err != nil {
			return err
		}
		platform.WriteJSON(w, 200, value)
		return nil
	}
	rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 ORDER BY `+scenarioRevisionOrder+` LIMIT $2`, scenario["id"], limit)
	if err != nil {
		return err
	}
	values := []any{}
	for _, row := range rows {
		value, err := scenarioRevisionDTO(row, snapshots)
		if err != nil {
			return err
		}
		values = append(values, value)
	}
	platform.WriteJSON(w, 200, values)
	return nil
}

func scenarioRevisionIntegrityError(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && strings.HasPrefix(pg.Code, "23")
}

func (s *Service) writeScenarioRevision(w http.ResponseWriter, r *http.Request, batch bool) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, err := scenarioContentInput(r, func(order libraryJSONOrder, fatal *error) platform.Schema {
		return scenarioRevisionSchema(batch, order, fatal)
	})
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	scenario, err := s.revisionScenario(ctx, tx, user, path["scenario_id"], false)
	if err != nil {
		return err
	}
	id := scenario.number("id")
	if !batch {
		if client := body.String("client_entry_id"); client != "" {
			row, err := scenarioRevisionByClient(ctx, tx, id, client)
			if err != nil {
				return err
			}
			if row != nil {
				value, err := scenarioRevisionDTO(row, false)
				if err != nil {
					return err
				}
				platform.WriteJSON(w, 201, value)
				return nil
			}
		}
		metadata := record(body)
		metadata["created_by"] = user.InternalID
		row, err := createScenarioRevision(ctx, tx, id, metadata, body["snapshot"].(map[string]any), true)
		if err != nil {
			return err
		}
		err = pruneScenarioRevisions(ctx, tx, id, 500)
		if err == nil {
			err = tx.Commit(ctx)
		}
		if err != nil {
			_ = tx.Rollback(ctx)
			if scenarioRevisionIntegrityError(err) && body.String("client_entry_id") != "" {
				if existing, lookupErr := scenarioRevisionByClient(ctx, s.Auth.DB, id, body.String("client_entry_id")); lookupErr == nil && existing != nil {
					row, err = existing, nil
				}
			}
			if err != nil {
				return err
			}
		}
		row, err = libraryFind(ctx, s.Auth.DB, "scenario_revision", row["id"])
		if err != nil {
			return err
		}
		value, err := scenarioRevisionDTO(row, false)
		if err != nil {
			return err
		}
		platform.WriteJSON(w, 201, value)
		return nil
	}
	items := body["items"].([]any)
	clients := []string{}
	for _, item := range items {
		clients = append(clients, libraryRecord(item).text("client_entry_id"))
	}
	existing, err := queryRecords(ctx, tx, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 AND client_entry_id=ANY($2::text[])`, id, clients)
	if err != nil {
		return err
	}
	prior, processed, created := map[string]record{}, map[string]bool{}, map[string]bool{}
	for _, row := range existing {
		prior[row.text("client_entry_id")] = row
		processed[row.text("client_entry_id")] = true
	}
	for _, item := range items {
		metadata := libraryRecord(item)
		client := metadata.text("client_entry_id")
		if processed[client] {
			continue
		}
		metadata["created_by"] = user.InternalID
		if _, err = createScenarioRevision(ctx, tx, id, metadata, metadata["snapshot"].(map[string]any), false); err != nil {
			return err
		}
		processed[client], created[client] = true, true
	}
	commitFailed := false
	if len(created) > 0 {
		err = resolveScenarioRevisionParents(ctx, tx, id)
		if err == nil {
			err = pruneScenarioRevisions(ctx, tx, id, 500)
		}
		if err == nil {
			err = tx.Commit(ctx)
		}
		if err != nil {
			_ = tx.Rollback(ctx)
			if !scenarioRevisionIntegrityError(err) {
				return err
			}
			commitFailed = true
		}
	}
	rows, err := queryRecords(ctx, s.Auth.DB, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 AND client_entry_id=ANY($2::text[])`, id, clients)
	if err != nil {
		return err
	}
	final := map[string]record{}
	for _, row := range rows {
		final[row.text("client_entry_id")] = row
	}
	seen, results := map[string]bool{}, []any{}
	for _, client := range clients {
		row := final[client]
		if row == nil {
			row = prior[client]
		}
		result := map[string]any{"clientEntryId": client, "revisionId": nil, "status": "failed", "reason": "revision was not created", "revision": nil}
		if row != nil {
			value, err := scenarioRevisionDTO(row, false)
			if err != nil {
				return err
			}
			result["revisionId"], result["revision"], result["reason"], result["status"] = row["id"], value, nil, "existing"
			if created[client] && !seen[client] && !commitFailed {
				result["status"] = "created"
			}
			seen[client] = true
		}
		results = append(results, result)
	}
	platform.WriteJSON(w, 201, map[string]any{"scenarioId": id, "results": results})
	return nil
}
