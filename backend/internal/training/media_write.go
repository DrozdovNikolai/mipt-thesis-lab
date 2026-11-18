package training

import (
	"context"
	"net/http"
	"strings"
	"unicode"

	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

type mediaWriteKind struct {
	table       string
	owner       string
	idsField    string
	missing     string
	invalidCode string
	invalidText string
	name        string
}

var exerciseMediaWrite = mediaWriteKind{
	table: "exercise_image", owner: "exercise_id", idsField: "image_ids",
	missing: "Image not found", invalidCode: "INVALID_IMAGE_ORDER",
	invalidText: "Image order must include each image exactly once", name: "exercise image",
}
var scenarioMediaWrite = mediaWriteKind{
	table: "scenario_pdf", owner: "scenario_id", idsField: "pdf_ids",
	missing: "PDF not found", invalidCode: "INVALID_PDF_ORDER",
	invalidText: "PDF order must include each PDF exactly once", name: "scenario PDF",
}

func (s *Service) registerMediaWrites(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("PUT "+p+"/exercises/{exercise_id}/images/order", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, exerciseMediaWrite, "reorder")
	}))
	mux.HandleFunc("PUT "+p+"/exercises/{exercise_id}/images/{image_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, exerciseMediaWrite, "update")
	}))
	mux.HandleFunc("DELETE "+p+"/exercises/{exercise_id}/images/{image_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, exerciseMediaWrite, "delete")
	}))
	mux.HandleFunc("PUT "+p+"/scenarios/{scenario_id}/pdfs/order", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, scenarioMediaWrite, "reorder")
	}))
	mux.HandleFunc("PUT "+p+"/scenarios/{scenario_id}/pdfs/{pdf_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, scenarioMediaWrite, "update")
	}))
	mux.HandleFunc("DELETE "+p+"/scenarios/{scenario_id}/pdfs/{pdf_id}", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.writeMedia(w, r, scenarioMediaWrite, "delete")
	}))
}

func mediaWriteInput(r *http.Request, kind mediaWriteKind, operation string) (platform.Object, platform.Object, platform.Object, error) {
	pathNames := []string{kind.owner}
	if operation == "update" || operation == "delete" {
		if kind.table == "exercise_image" {
			pathNames = append(pathNames, "image_id")
		} else {
			pathNames = append(pathNames, "pdf_id")
		}
	}
	var path, body platform.Object
	var inputErr error
	if operation == "delete" {
		path, body, inputErr = libraryInput(r, nil, pathNames...)
	} else {
		path, body, inputErr = scenarioResourceInput(r, func(_ libraryJSONOrder, _ *error) platform.Schema {
			if operation == "update" {
				return platform.Schema{Fields: []platform.Field{{Name: "display_name", Alias: "displayName", Kind: "string", Nullable: true, Max: 255}}}
			}
			return platform.Schema{Fields: []platform.Field{{Name: kind.idsField, Alias: libraryCamel(kind.idsField), Kind: "list", Min: 1, Default: []any{}, Item: &platform.Field{Kind: "integer", AllowBigInteger: true}}}}
		}, false, pathNames...)
	}
	query, queryErr := platform.QueryObject(r.URL.Query(), platform.Field{Name: "expected_version", Alias: "expectedVersion", Kind: "integer", Nullable: true, AllowBigInteger: true})
	return path, body, query, scenarioQueryError(inputErr, queryErr)
}

func mediaDisplayName(value any) any {
	text, ok := value.(string)
	if !ok {
		return nil
	}
	words := strings.FieldsFunc(text, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f })
	if len(words) == 0 {
		return nil
	}
	joined := []rune(strings.Join(words, " "))
	if len(joined) > 255 {
		joined = joined[:255]
	}
	return string(joined)
}

func mediaWriteInvalidOrder(kind mediaWriteKind) error {
	return commanderError(400, kind.invalidCode, kind.invalidText)
}

func mediaWriteFind(items []record, id any) record {
	wanted, ok := id.(int64)
	if !ok {
		return nil
	}
	for _, item := range items {
		if item.number("id") == wanted {
			return item
		}
	}
	return nil
}

func (s *Service) mediaWriteResponse(ctx context.Context, scenarioID int64, ownerID int64, version int64, kind mediaWriteKind) (record, error) {
	graph, err := loadSourceScenario(ctx, s.Auth.DB, scenarioID)
	if err != nil {
		return nil, err
	}
	snapshot, err := validatedScenarioSnapshot(graph)
	if err != nil {
		return nil, err
	}
	result := record{"scenario_id": scenarioID, "content_version": version, "snapshot": snapshot}
	if kind.table == "exercise_image" {
		images := []record{}
		for _, module := range graph.Modules {
			for _, exercise := range module.Exercises {
				if exercise.Row.number("id") == ownerID {
					for _, image := range exercise.Images {
						images = append(images, scenarioMediaDTO(image, s.Auth.Config.APIPrefix, false))
					}
				}
			}
		}
		result["images"] = images
	} else {
		pdfs := []record{}
		for _, pdf := range graph.Pdfs {
			pdfs = append(pdfs, scenarioMediaDTO(pdf, s.Auth.Config.APIPrefix, true))
		}
		result["pdfs"], result["pdf"] = pdfs, nil
		if len(pdfs) > 0 {
			result["pdf"] = pdfs[0]
		}
	}
	return result, nil
}

func (s *Service) writeMedia(w http.ResponseWriter, r *http.Request, kind mediaWriteKind, operation string) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, query, err := mediaWriteInput(r, kind, operation)
	if err != nil {
		return err
	}
	airline, err := commanderAirline(user)
	if err != nil {
		return err
	}
	aircraft, err := libraryAllowedAircraft(user)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var owner, scenario record
	if kind.table == "exercise_image" {
		owner, _, scenario, err = editorExercise(ctx, tx, path["exercise_id"], airline, aircraft)
		if err != nil {
			return err
		}
		if scenario["deleted_at"] != nil || scenario.text("status") == "ARCHIVED" {
			return platform.Error(404, "Exercise not found")
		}
	} else {
		scenario, err = scenarioGet(ctx, tx, path["scenario_id"], airline, aircraft, false, false)
		if err != nil {
			return err
		}
		owner = scenario
	}
	client := r.Header.Get("X-Client-Session-Id")
	if client == "" {
		return scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required for "+kind.name+" writes", nil)
	}
	if err = s.ensureScenarioContentLock(ctx, tx, scenario["id"], user, client); err != nil {
		return err
	}
	if query["expected_version"] == nil {
		return scenarioSnapshotError("EXPECTED_VERSION_REQUIRED", "expectedVersion query parameter is required for "+kind.name+" "+operation, nil)
	}
	items, err := queryRecords(ctx, tx, "SELECT to_jsonb(m) FROM "+kind.table+" m WHERE "+kind.owner+"=$1 ORDER BY order_index,id", owner["id"])
	if err != nil {
		return err
	}
	var deleted record
	switch operation {
	case "update":
		key := "image_id"
		if kind.table == "scenario_pdf" {
			key = "pdf_id"
		}
		row := mediaWriteFind(items, path[key])
		if row == nil {
			return platform.Error(404, kind.missing)
		}
		if err = libraryUpdate(ctx, tx, kind.table, row, record{"display_name": mediaDisplayName(body["display_name"])}); err != nil {
			return err
		}
	case "reorder":
		ids, _ := body[kind.idsField].([]any)
		if len(ids) != len(items) {
			return mediaWriteInvalidOrder(kind)
		}
		seen := map[int64]bool{}
		for index, raw := range ids {
			id, ok := raw.(int64)
			if !ok || seen[id] {
				return mediaWriteInvalidOrder(kind)
			}
			row := mediaWriteFind(items, id)
			if row == nil {
				return mediaWriteInvalidOrder(kind)
			}
			seen[id] = true
			if err = libraryUpdate(ctx, tx, kind.table, row, record{"order_index": int64(index)}); err != nil {
				return err
			}
		}
	case "delete":
		key := "image_id"
		if kind.table == "scenario_pdf" {
			key = "pdf_id"
		}
		deleted = mediaWriteFind(items, path[key])
		if deleted == nil {
			return platform.Error(404, kind.missing)
		}
		if _, err = tx.Exec(ctx, "DELETE FROM "+kind.table+" WHERE id=$1", deleted["id"]); err != nil {
			return err
		}
		order := int64(0)
		for _, row := range items {
			if row["id"] == deleted["id"] {
				continue
			}
			if err = libraryUpdate(ctx, tx, kind.table, row, record{"order_index": order}); err != nil {
				return err
			}
			order++
		}
	}
	version, err := scenarioBumpContentVersion(ctx, tx, scenario["id"], user.InternalID, query["expected_version"], "Scenario was modified by another request")
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if deleted != nil {
		var snapshotTable string
		if kind.table == "exercise_image" {
			snapshotTable = "training_session_exercise_image"
		} else {
			snapshotTable = "training_session_scenario_pdf"
		}
		var referenced bool
		if err = s.Auth.DB.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM "+snapshotTable+" WHERE storage_key=$1)", deleted["storage_key"]).Scan(&referenced); err != nil {
			return err
		}
		if !referenced {
			if err = s.Storage.Delete(ctx, filestorage.Media, deleted.text("storage_path")); err != nil {
				return err
			}
		}
	}
	if _, err = scenarioGet(ctx, s.Auth.DB, scenario["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	response, err := s.mediaWriteResponse(ctx, scenario.number("id"), owner.number("id"), version, kind)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, commanderWire(response))
	return nil
}
