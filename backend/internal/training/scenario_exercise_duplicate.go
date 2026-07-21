package training

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func editorSourceParams(params record) record {
	if params == nil {
		return nil
	}
	out := params.project("intensity zfw_t guidance_doc guidance_plain_text")
	for _, key := range []string{"original_tl", "destination_tl"} {
		out[key] = nil
		if row := params.object(key); row != nil {
			data := row.project(libraryTLFields)
			for _, field := range strings.Fields(libraryTakeoffFields) {
				data[field] = row.object("takeoff_details")[field]
			}
			out[key] = data
		}
	}
	return out
}

func (s *Service) copyEditorExerciseImages(ctx context.Context, db runtimeDB, source *sourceExercise, target, scenarioID any, copied *[]string) error {
	if len(source.Images) == 0 {
		return nil
	}
	var count int64
	if err := db.QueryRow(ctx, `SELECT count(*) FROM exercise_image WHERE exercise_id=$1`, target).Scan(&count); err != nil {
		return err
	}
	maximum := s.Auth.Config.MediaExerciseImageMaxFiles
	if count+int64(len(source.Images)) > maximum {
		label := s.Auth.Config.MediaExerciseImageMaxFilesText
		if label == "" {
			label = fmt.Sprint(maximum)
		}
		return scenarioSnapshotError("TOO_MANY_EXERCISE_IMAGES", fmt.Sprintf("Too many exercise images (max %s)", label), nil)
	}
	for _, row := range source.Images {
		stored, err := s.Storage.CloneImage(ctx, row.text("storage_path"), fmt.Sprintf("exercise_images/%v/%v", scenarioID, target), s.Auth.Config.MediaExerciseImageMaxFileBytes)
		if err != nil {
			var mediaErr *filestorage.MediaError
			if errors.As(err, &mediaErr) {
				if mediaErr.Status == 404 {
					continue
				}
				if mediaErr.Status == 413 && s.Auth.Config.MediaExerciseImageMaxFileBytesText != "" {
					return platform.Error(413, fmt.Sprintf("File too large (max %s bytes)", s.Auth.Config.MediaExerciseImageMaxFileBytesText))
				}
				return platform.Error(mediaErr.Status, mediaErr.Message)
			}
			return err
		}
		*copied = append(*copied, stored.StoragePath)
		data := row.project("original_filename display_name")
		data["exercise_id"], data["storage_key"], data["storage_path"] = target, stored.StorageKey, stored.StoragePath
		data["content_type"], data["size_bytes"], data["sha256"], data["order_index"] = stored.ContentType, stored.SizeBytes, stored.SHA256, count
		if _, err = insertTrainingRow(ctx, db, "exercise_image", data); err != nil {
			return err
		}
		count++
	}
	return nil
}

func (s *Service) duplicateEditorExercise(w http.ResponseWriter, r *http.Request) (err error) {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, body, query, err := editorInput(r, "exercise", "duplicate")
	if err != nil {
		return err
	}
	client := r.Header.Get("X-Client-Session-Id")
	if client == "" {
		return scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required for exercise duplication", nil)
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
	row, module, scenario, err := editorExercise(ctx, tx, path["exercise_id"], airline, aircraft)
	if err != nil {
		return err
	}
	if scenario["deleted_at"] != nil || strings.ToUpper(pythonTrim(scenario.text("status"))) == "ARCHIVED" {
		return platform.Error(404, "Exercise not found")
	}
	source := &sourceExercise{Row: row}
	if err = loadExerciseAssetsMode(ctx, tx, []*sourceExercise{source}, false, true); err != nil {
		return err
	}
	// The source copies the ORM relationship's query order, before the editor
	// DTO sorts competences for display. That order determines new link IDs.
	source.Competences, err = queryRecords(ctx, tx, `SELECT to_jsonb(c) FROM exercise e JOIN exercise_competence l ON l.exercise_id=e.id JOIN competence c ON c.id=l.competence_id WHERE e.id=$1`, row["id"])
	if err != nil {
		return err
	}
	siblings, err := queryRecords(ctx, tx, `SELECT to_jsonb(e) FROM exercise e WHERE module_id=$1`, module["id"])
	if err != nil {
		return err
	}
	if query["expected_version"] == nil {
		return scenarioSnapshotError("EXPECTED_VERSION_REQUIRED", "expectedVersion query parameter is required for exercise duplication", nil)
	}
	if err = s.ensureScenarioContentLock(ctx, tx, scenario["id"], user, client); err != nil {
		return err
	}
	insertAt := row.number("order_index") + 1
	for _, sibling := range siblings {
		if sibling.number("id") != row.number("id") && sibling.number("order_index") >= insertAt {
			if err = scenarioUpdateRow(ctx, tx, "exercise", sibling, record{"order_index": sibling.number("order_index") + 1}); err != nil {
				return err
			}
		}
	}
	data := row.project("module_id kind duration_minutes crew_member_number")
	data["order_index"], data["client_uid"] = insertAt, body.String("client_uid")
	if data.text("kind") == "" {
		data["kind"] = "standard"
	}
	if data.text("client_uid") == "" {
		data["client_uid"] = uuid.NewString()
	}
	duplicate, err := insertTrainingRow(ctx, tx, "exercise", data)
	if err != nil {
		return err
	}
	copied := []string{}
	committed := false
	defer func() {
		if !committed {
			_ = tx.Rollback(ctx)
			cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
			defer cancel()
			for _, path := range copied {
				if cleanupErr := s.Storage.Delete(cleanup, filestorage.Media, path); cleanupErr != nil {
					err = cleanupErr
					break
				}
			}
		}
	}()
	if data.text("kind") == "standard" {
		elements := []any{}
		for _, element := range source.Elements {
			entry := element.project("element_id order_index details starting_height ending_height profile_type")
			entry["element_id"] = element.number("element_id")
			elements = append(elements, entry)
		}
		if err = scenarioReplaceElements(ctx, tx, duplicate["id"], airline, scenario.number("aircraft_id"), elements); err != nil {
			return err
		}
		if err = scenarioReplaceParams(ctx, tx, duplicate, editorSourceParams(source.Param)); err != nil {
			return err
		}
		competences := []any{}
		for _, competence := range source.Competences {
			competences = append(competences, competence.number("id"))
		}
		if err = scenarioReplaceCompetences(ctx, tx, duplicate["id"], airline, competences); err != nil {
			return err
		}
	}
	if err = s.copyEditorExerciseImages(ctx, tx, source, duplicate["id"], scenario["id"], &copied); err != nil {
		return err
	}
	version, err := scenarioBumpContentVersion(ctx, tx, scenario["id"], user.InternalID, query["expected_version"], "Scenario was modified by another request")
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	committed = true
	exercise, err := s.editorExerciseResponse(ctx, duplicate["id"])
	if err != nil {
		return err
	}
	if _, err = scenarioGet(ctx, s.Auth.DB, scenario["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	graph, err := loadSourceScenario(ctx, s.Auth.DB, scenario.number("id"))
	if err != nil {
		return err
	}
	snapshot, err := validatedScenarioSnapshot(graph)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, commanderWire(record{"scenario_id": scenario["id"], "content_version": version, "snapshot": snapshot, "exercise": exercise}))
	return nil
}
