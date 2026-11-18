package training

import (
	"encoding/json"
	"errors"
	"fmt"
	"mime/multipart"
	"net/http"

	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func (s *Service) registerMediaUploads(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("POST "+p+"/exercises/{exercise_id}/images/upload", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.uploadMedia(w, r, exerciseMediaWrite)
	}))
	mux.HandleFunc("POST "+p+"/scenarios/{scenario_id}/pdfs/upload", platform.Wrap(func(w http.ResponseWriter, r *http.Request) error {
		return s.uploadMedia(w, r, scenarioMediaWrite)
	}))
}

func mediaUploadMissingFiles() error {
	return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": []any{platform.Detail("missing", "Field required", []any{"body", "files"}, nil, nil)}}}
}

func mediaUploadForm(r *http.Request) ([]*multipart.FileHeader, *string, error) {
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		if errors.Is(err, http.ErrNotMultipart) {
			return nil, nil, mediaUploadMissingFiles()
		}
		return nil, nil, platform.Error(400, "There was an error parsing the body")
	}
	files := r.MultipartForm.File["files"]
	if len(files) == 0 {
		return nil, nil, mediaUploadMissingFiles()
	}
	var names *string
	if values := r.MultipartForm.Value["displayNames"]; len(values) != 0 {
		value := values[len(values)-1]
		names = &value
	}
	return files, names, nil
}

func mediaUploadNames(raw *string, count int, pdf bool) ([]any, error) {
	names := make([]any, count)
	if raw == nil {
		return names, nil
	}
	label, code := "Image", "INVALID_IMAGE_DISPLAY_NAMES"
	if pdf {
		label, code = "PDF", "INVALID_PDF_DISPLAY_NAMES"
	}
	var decoded any
	if err := json.Unmarshal([]byte(*raw), &decoded); err != nil {
		return nil, commanderError(400, code, label+" display names must be valid JSON")
	}
	items, ok := decoded.([]any)
	if !ok {
		return nil, commanderError(400, code, label+" display names must be a string array")
	}
	for _, value := range items {
		if _, ok := value.(string); !ok {
			return nil, commanderError(400, code, label+" display names must be a string array")
		}
	}
	if len(items) != count {
		return nil, commanderError(400, code, label+" display names must match uploaded files")
	}
	for index, value := range items {
		names[index] = mediaDisplayName(value)
	}
	return names, nil
}

func (s *Service) uploadMedia(w http.ResponseWriter, r *http.Request, kind mediaWriteKind) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	path, _, pathErr := libraryInput(r, nil, kind.owner)
	query, queryErr := platform.QueryObject(r.URL.Query(), platform.Field{Name: "expected_version", Alias: "expectedVersion", Kind: "integer", Nullable: true, AllowBigInteger: true})
	files, rawNames, formErr := mediaUploadForm(r)
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	if err := scenarioQueryError(pathErr, queryErr); err != nil {
		return err
	}
	if formErr != nil {
		return formErr
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
		return scenarioSnapshotError("EXPECTED_VERSION_REQUIRED", "expectedVersion query parameter is required for "+kind.name+" upload", nil)
	}
	if len(files) == 0 {
		return platform.Error(400, "No files uploaded")
	}
	pdf := kind.table == "scenario_pdf"
	names, err := mediaUploadNames(rawNames, len(files), pdf)
	if err != nil {
		return err
	}
	items, err := queryRecords(ctx, tx, "SELECT to_jsonb(m) FROM "+kind.table+" m WHERE "+kind.owner+"=$1 ORDER BY order_index,id", owner["id"])
	if err != nil {
		return err
	}
	maxFiles, maxBytes := s.Auth.Config.MediaExerciseImageMaxFiles, s.Auth.Config.MediaExerciseImageMaxFileBytes
	if pdf {
		maxFiles, maxBytes = s.Auth.Config.MediaScenarioPDFMaxFiles, s.Auth.Config.MediaScenarioPDFMaxFileBytes
	}
	if int64(len(items)+len(files)) > maxFiles {
		label, code := "Too many exercise images", "TOO_MANY_EXERCISE_IMAGES"
		if pdf {
			label, code = "Too many scenario PDFs", "TOO_MANY_SCENARIO_PDFS"
		}
		return &platform.APIError{Status: 400, Code: code, Message: fmt.Sprintf("%s (max %d)", label, maxFiles), Extra: map[string]any{"max_files": maxFiles}}
	}
	namespace := fmt.Sprintf("exercise_images/%d/%d", scenario.number("id"), owner.number("id"))
	if pdf {
		namespace = fmt.Sprintf("scenario_pdfs/%d", scenario.number("id"))
	}
	storedPaths := []string{}
	storedFiles := make([]filestorage.StoredMedia, 0, len(files))
	committed := false
	defer func() {
		if !committed {
			for _, storagePath := range storedPaths {
				_ = s.Storage.Delete(ctx, filestorage.Media, storagePath)
			}
		}
	}()
	for _, header := range files {
		file, err := header.Open()
		if err != nil {
			return err
		}
		var stored filestorage.StoredMedia
		if pdf {
			stored, err = s.Storage.SavePDFUpload(ctx, file, header.Filename, header.Header.Get("Content-Type"), namespace, maxBytes)
		} else {
			stored, err = s.Storage.SaveImageUpload(ctx, file, header.Filename, header.Header.Get("Content-Type"), namespace, maxBytes)
		}
		_ = file.Close()
		if err != nil {
			var media *filestorage.MediaError
			if errors.As(err, &media) {
				return platform.Error(media.Status, media.Message)
			}
			return err
		}
		storedPaths = append(storedPaths, stored.StoragePath)
		storedFiles = append(storedFiles, stored)
	}
	for index, header := range files {
		stored := storedFiles[index]
		filename := header.Filename
		if filename == "" {
			filename = stored.StorageKey
		}
		filename = string([]rune(filename)[:min(len([]rune(filename)), 512)])
		_, err = tx.Exec(ctx, "INSERT INTO "+kind.table+" ("+kind.owner+",storage_key,storage_path,original_filename,display_name,content_type,size_bytes,sha256,order_index) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)", owner["id"], stored.StorageKey, stored.StoragePath, filename, names[index], stored.ContentType, stored.SizeBytes, stored.SHA256, len(items)+index)
		if err != nil {
			return err
		}
	}
	version, err := scenarioBumpContentVersion(ctx, tx, scenario["id"], user.InternalID, query["expected_version"], "Scenario was modified by another request")
	if err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	committed = true
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
