package training

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func duplicateScenarioTitle(source, requested string) string {
	if title := pythonTrim(requested); title != "" {
		return title
	}
	base := pythonTrim(source)
	if base == "" {
		base = "Scenario"
	}
	const suffix = " (copy)"
	runes := []rune(base)
	if len(runes)+len(suffix) <= 255 {
		return base + suffix
	}
	return pythonTrim(string(runes[:255-len(suffix)])) + suffix
}

func duplicateScenarioSnapshot(source sourceScenario, targetID int64, clearColumns bool) (record, map[int64]string, error) {
	days := map[int64]int64{}
	for _, day := range source.Days {
		days[day.number("module_id")] = max(1, day.number("day_index"))
	}
	modules, originalIDs := []record{}, map[int64]string{}
	previous, exerciseID := int64(1), int64(-1)
	for i, module := range source.Modules {
		moduleID := -int64(i + 1)
		day := max(previous, days[module.Row.number("id")])
		if i == 0 {
			day = 1
		}
		m := module.Row.project("order_index duration_minutes content_subcolumn_id")
		m["id"], m["client_uid"], m["scenario_id"] = moduleID, uuid.NewString(), targetID
		m["day_index"], m["day_start"] = day, i > 0 && day > previous
		previous = day
		if clearColumns {
			m["content_subcolumn_id"] = nil
		}
		exercises := []record{}
		for _, exercise := range module.Exercises {
			e := exercise.Row.project("kind order_index duration_minutes crew_member_number")
			e["id"], e["client_uid"], e["module_id"] = exerciseID, uuid.NewString(), moduleID
			originalIDs[exercise.Row.number("id")] = fmt.Sprint(exerciseID)
			exerciseID--
			if e.text("kind") == "" {
				e["kind"] = "standard"
			}
			competences := []int64{}
			for _, c := range exercise.Competences {
				competences = append(competences, c.number("id"))
			}
			e["competence_ids"] = competences
			elements := []record{}
			for _, element := range exercise.Elements {
				elements = append(elements, element.project("element_id order_index details starting_height ending_height profile_type"))
			}
			e["elements"], e["params"] = elements, editorSourceParams(exercise.Param)
			exercises = append(exercises, e)
		}
		m["exercises"] = exercises
		modules = append(modules, m)
	}
	// This model is built inside the source service. Invalid persisted content
	// raises a server error after the empty destination scenario was committed.
	raw, err := json.Marshal(record{"modules": modules})
	if err != nil {
		return nil, nil, err
	}
	var input any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err = decoder.Decode(&input); err != nil {
		return nil, nil, err
	}
	var fatal error
	model := scenarioSnapshotSchema(nil, &fatal)
	value, err := platform.ValidateObject(input, nil, model)
	if err != nil || fatal != nil {
		return nil, nil, fmt.Errorf("invalid duplicate source snapshot: %v %v", err, fatal)
	}
	return record(scenarioModelDefaults(value, model)), originalIDs, nil
}

func (s *Service) duplicateEditorScenario(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	model := platform.Schema{Fields: []platform.Field{
		{Name: "title", Kind: "string", Nullable: true, Max: 255},
		{Name: "content_set_id", Alias: "contentSetId", Kind: "integer", Min: 1, Nullable: true, AllowBigInteger: true},
		{Name: "set_label_id", Alias: "setLabelId", Kind: "integer", Min: 1, Nullable: true, AllowBigInteger: true},
	}}
	path, body, err := libraryInput(r, &model, "scenario_id")
	if err != nil {
		return err
	}
	client := r.Header.Get("X-Client-Session-Id")
	if client == "" {
		return scenarioSnapshotError("CLIENT_SESSION_REQUIRED", "X-Client-Session-Id header is required for scenario duplication", nil)
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
	sourceRow, err := scenarioGet(ctx, s.Auth.DB, path["scenario_id"], airline, aircraft, false, false)
	if err != nil {
		return err
	}
	source, err := loadSourceScenarioMode(ctx, s.Auth.DB, sourceRow.number("id"), true)
	if err != nil {
		return err
	}
	if err = loadDuplicateScenarioCompetences(ctx, s.Auth.DB, &source); err != nil {
		return err
	}
	var targetSet, targetLabel record
	if body["content_set_id"] != nil || body["set_label_id"] != nil {
		if body["content_set_id"] == nil || body["set_label_id"] == nil {
			return scenarioSnapshotError("INVALID_DUPLICATE_TARGET", "content_set_id and set_label_id must be provided together", nil)
		}
		targetSet, err = libraryFind(ctx, s.Auth.DB, "scenario_content_set", body["content_set_id"])
		if err != nil {
			return err
		}
		if targetSet == nil || targetSet.number("airline_id") != airline || !libraryContains(aircraft, targetSet.number("aircraft_id")) {
			return platform.Error(404, "Content set not found")
		}
		targetLabel, err = libraryFind(ctx, s.Auth.DB, "scenario_content_set_label", body["set_label_id"])
		if err != nil {
			return err
		}
		if targetLabel == nil || targetLabel.number("content_set_id") != targetSet.number("id") {
			return platform.Error(404, "Content set label not found")
		}
		if sourceRow.number("aircraft_id") != targetSet.number("aircraft_id") {
			return scenarioSnapshotError("INVALID_CONTENT_SET", "Scenario aircraft_id does not match the selected content set", nil)
		}
	}
	links, err := queryRecords(ctx, s.Auth.DB, `SELECT jsonb_build_object('content_set_id',l.content_set_id) FROM scenario_content_set_label l JOIN scenario_content_set_label_scenario x ON x.label_id=l.id WHERE x.scenario_id=$1 ORDER BY x.id LIMIT 1`, sourceRow["id"])
	if err != nil {
		return err
	}
	clearColumns := targetSet != nil && len(links) > 0 && links[0].number("content_set_id") != targetSet.number("id")
	data := sourceRow.project("airline_id aircraft_id code engines comments valid_until")
	data["title"], data["status"], data["published_at"] = duplicateScenarioTitle(sourceRow.text("title"), body.String("title")), "DRAFT", nil
	data["created_by"], data["updated_by"] = user.InternalID, user.InternalID
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	target, err := insertTrainingRow(ctx, tx, "scenario", data)
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	contentTx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer contentTx.Rollback(ctx)
	if targetLabel != nil {
		if _, err = insertTrainingRow(ctx, contentTx, "scenario_content_set_label_scenario", record{"label_id": targetLabel["id"], "scenario_id": target["id"]}); err != nil {
			return err
		}
	}
	snapshot, originalIDs, err := duplicateScenarioSnapshot(source, target.number("id"), clearColumns)
	if err != nil {
		return err
	}
	result, err := s.saveScenarioSnapshot(ctx, contentTx, user, scenarioSnapshotCommand{ScenarioID: target["id"], Snapshot: snapshot, ExpectedVersion: target["content_version"], ClientSessionID: client})
	if err != nil {
		return err
	}
	mapping := map[int64]int64{}
	for original, temporary := range originalIDs {
		if id, ok := result["exercise_id_map"].(map[string]int64)[temporary]; ok {
			mapping[original] = id
		}
	}
	if _, err = scenarioGet(ctx, s.Auth.DB, sourceRow["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	mediaSource, err := loadSourceScenarioMode(ctx, s.Auth.DB, sourceRow.number("id"), true)
	if err != nil {
		return err
	}
	if err = s.copyScenarioDuplicateMedia(ctx, mediaSource, target.number("id"), mapping, false); err != nil {
		return err
	}
	if err = s.copyScenarioDuplicateMedia(ctx, mediaSource, target.number("id"), mapping, true); err != nil {
		return err
	}
	if _, err = scenarioGet(ctx, s.Auth.DB, target["id"], airline, aircraft, false, false); err != nil {
		return err
	}
	return s.writeEditorScenario(ctx, w, target.number("id"), 201)
}

func loadDuplicateScenarioCompetences(ctx context.Context, db runtimeDB, source *sourceScenario) error {
	ids, byID := []int64{}, map[int64]*sourceExercise{}
	for _, module := range source.Modules {
		for _, exercise := range module.Exercises {
			id := exercise.Row.number("id")
			ids = append(ids, id)
			byID[id] = exercise
			exercise.Competences = nil
		}
	}
	// Whole-scenario selectinload reads this relationship in batches. A query
	// for a single exercise can use a different join order, which changes new
	// association IDs even though the editor's sorted response stays identical.
	for start := 0; start < len(ids); start += 500 {
		rows, err := queryRecords(ctx, db, `SELECT to_jsonb(c)||jsonb_build_object('owner_id',e.id)
FROM exercise e JOIN exercise_competence l ON l.exercise_id=e.id JOIN competence c ON c.id=l.competence_id
WHERE e.id=ANY($1::bigint[])`, ids[start:min(start+500, len(ids))])
		if err != nil {
			return err
		}
		for _, row := range rows {
			exercise := byID[row.number("owner_id")]
			exercise.Competences = append(exercise.Competences, row)
		}
	}
	return nil
}

// Each media stage has its own commit. A failed PDF stage retains copied images
// and scenario content, while failed-stage files and rows are removed together.
func (s *Service) copyScenarioDuplicateMedia(ctx context.Context, source sourceScenario, targetID int64, mapping map[int64]int64, pdf bool) (err error) {
	if pdf && len(source.Pdfs) == 0 {
		return nil
	}
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	copied, committed := []string{}, false
	defer func() {
		if committed {
			return
		}
		_ = tx.Rollback(ctx)
		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
		defer cancel()
		for _, path := range copied {
			if e := s.Storage.Delete(cleanup, filestorage.Media, path); e != nil {
				err = e
				break
			}
		}
	}()
	table, ownerField, maximum, spelling := "exercise_image", "exercise_id", s.Auth.Config.MediaExerciseImageMaxFileBytes, s.Auth.Config.MediaExerciseImageMaxFileBytesText
	type item struct {
		row       record
		owner     int64
		namespace string
	}
	items := []item{}
	count := int64(0)
	if pdf {
		if err = tx.QueryRow(ctx, `SELECT count(*) FROM scenario_pdf WHERE scenario_id=$1`, targetID).Scan(&count); err != nil {
			return err
		}
		if count+int64(len(source.Pdfs)) > s.Auth.Config.MediaScenarioPDFMaxFiles {
			label := s.Auth.Config.MediaScenarioPDFMaxFilesText
			if label == "" {
				label = fmt.Sprint(s.Auth.Config.MediaScenarioPDFMaxFiles)
			}
			return scenarioSnapshotError("TOO_MANY_SCENARIO_PDFS", fmt.Sprintf("Too many scenario PDFs (max %s)", label), nil)
		}
		table, ownerField, maximum, spelling = "scenario_pdf", "scenario_id", s.Auth.Config.MediaScenarioPDFMaxFileBytes, s.Auth.Config.MediaScenarioPDFMaxFileBytesText
		for _, row := range source.Pdfs {
			items = append(items, item{row, targetID, fmt.Sprintf("scenario_pdfs/%d", targetID)})
		}
	} else {
		for _, module := range source.Modules {
			for _, exercise := range module.Exercises {
				id := mapping[exercise.Row.number("id")]
				if id == 0 {
					continue
				}
				for _, row := range exercise.Images {
					items = append(items, item{row, id, fmt.Sprintf("exercise_images/%d/%d", targetID, id)})
				}
			}
		}
	}
	rows := []record{}
	for _, item := range items {
		clone := s.Storage.CloneImage
		if pdf {
			clone = s.Storage.ClonePDF
		}
		stored, e := clone(ctx, item.row.text("storage_path"), item.namespace, maximum)
		if e != nil {
			var media *filestorage.MediaError
			if errors.As(e, &media) {
				if media.Status == 404 {
					continue
				}
				if media.Status == 413 && spelling != "" {
					return platform.Error(413, fmt.Sprintf("File too large (max %s bytes)", spelling))
				}
				return platform.Error(media.Status, media.Message)
			}
			return e
		}
		copied = append(copied, stored.StoragePath)
		row := item.row.project("original_filename display_name order_index")
		row[ownerField], row["storage_key"], row["storage_path"] = item.owner, stored.StorageKey, stored.StoragePath
		row["content_type"], row["size_bytes"], row["sha256"] = stored.ContentType, stored.SizeBytes, stored.SHA256
		if pdf {
			row["order_index"] = count
			count++
		}
		rows = append(rows, row)
	}
	for _, row := range rows {
		if _, err = insertTrainingRow(ctx, tx, table, row); err != nil {
			return err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	committed = true
	return nil
}
