package training

import (
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func (s *Service) registerAssessmentSignatures(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/assessments"
	mux.HandleFunc("POST "+p+"/{assessment_id}/signature/upload", platform.Wrap(s.uploadAssessmentSignature))
	mux.HandleFunc("POST "+p+"/{assessment_id}/signature/use-profile", platform.Wrap(s.useProfileAssessmentSignature))
	mux.HandleFunc("GET "+p+"/signatures/{storage_key}", platform.Wrap(s.readAssessmentSignature))
	mux.HandleFunc("PATCH "+p+"/{assessment_id}/signature", platform.Wrap(s.updateAssessmentSignature))
}

func signatureURL(r *http.Request, prefix, key string) string {
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	if forwarded := r.Header.Get("X-Forwarded-Proto"); forwarded != "" {
		scheme = strings.TrimSpace(strings.Split(forwarded, ",")[0])
	}
	return scheme + "://" + r.Host + prefix + "/training/assessments/signatures/" + key
}

func signatureAssessmentPath(r *http.Request) (int64, error) {
	path, _, err := libraryInput(r, nil, "assessment_id")
	if err != nil {
		return 0, err
	}
	id, _ := path["assessment_id"].(int64)
	return id, nil
}

func (s *Service) signatureAssessment(id int64, r *http.Request) (record, error) {
	row, err := queryRecord(r.Context(), s.Auth.DB, `SELECT to_jsonb(a) FROM crew_member_assessment a WHERE id=$1`, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, platform.Error(404, "Assessment not found")
	}
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, platform.Error(404, "Assessment not found")
	}
	return row, nil
}

func signatureReply(w http.ResponseWriter, id int64, url string) {
	platform.WriteJSON(w, 200, record{"assessmentId": id, "signatureUrl": url})
}

func (s *Service) setStoredAssessmentSignature(r *http.Request, id int64, oldPath string, stored filestorage.StoredMedia, errorText string) (string, error) {
	url := signatureURL(r, s.Auth.Config.APIPrefix, stored.StorageKey)
	_, err := s.Auth.DB.Exec(r.Context(), `UPDATE crew_member_assessment SET signature=$2,signature_storage_path=$3,signature_storage_key=$4,signature_content_type=$5,signature_size_bytes=$6,signature_sha256=$7,signed_at=now(),updated_at=now() WHERE id=$1`, id, url, stored.StoragePath, stored.StorageKey, stored.ContentType, stored.SizeBytes, stored.SHA256)
	if err != nil {
		_ = s.Storage.Delete(r.Context(), filestorage.Media, stored.StoragePath)
		return "", platform.Error(500, errorText)
	}
	if oldPath != "" && oldPath != stored.StoragePath {
		if err = s.Storage.Delete(r.Context(), filestorage.Media, oldPath); err != nil {
			return "", err
		}
	}
	return url, nil
}

func (s *Service) uploadAssessmentSignature(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := signatureAssessmentPath(r)
	if err != nil {
		return err
	}
	if err = r.ParseMultipartForm(1 << 20); err != nil {
		return platform.Error(400, "There was an error parsing the body")
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	file, header, err := r.FormFile("file")
	if errors.Is(err, http.ErrMissingFile) {
		return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": []any{platform.Detail("missing", "Field required", []any{"body", "file"}, nil, nil)}}}
	}
	if err != nil {
		return platform.Error(400, "There was an error parsing the body")
	}
	defer file.Close()
	assessment, err := s.signatureAssessment(id, r)
	if err != nil {
		return err
	}
	stored, err := s.Storage.SaveImageUpload(r.Context(), file, header.Filename, header.Header.Get("Content-Type"), fmt.Sprintf("assessment_signatures/%d", id), s.Auth.Config.MediaSignatureMaxFileBytes)
	if err != nil {
		var media *filestorage.MediaError
		if errors.As(err, &media) {
			return platform.Error(media.Status, media.Message)
		}
		return err
	}
	url, err := s.setStoredAssessmentSignature(r, id, assessment.text("signature_storage_path"), stored, "Failed to upload signature")
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Assessment signature uploaded", "action", "assessment.upload_signature", "user_id", user.ID.String(), "assessment_id", id)
	signatureReply(w, id, url)
	return nil
}

func (s *Service) useProfileAssessmentSignature(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := signatureAssessmentPath(r)
	if err != nil {
		return err
	}
	assessment, err := s.signatureAssessment(id, r)
	if err != nil {
		return err
	}
	var sourcePath *string
	err = s.Auth.DB.QueryRow(r.Context(), `SELECT signature_storage_path FROM user_info WHERE id=$1`, user.InternalID).Scan(&sourcePath)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && (sourcePath == nil || *sourcePath == "") {
		return platform.Error(400, "Current user signature is not configured")
	}
	if err != nil {
		return err
	}
	stored, err := s.Storage.CloneImage(r.Context(), *sourcePath, fmt.Sprintf("assessment_signatures/%d", id), s.Auth.Config.MediaSignatureMaxFileBytes)
	if err != nil {
		var media *filestorage.MediaError
		if errors.As(err, &media) {
			return platform.Error(media.Status, media.Message)
		}
		return err
	}
	url, err := s.setStoredAssessmentSignature(r, id, assessment.text("signature_storage_path"), stored, "Failed to apply profile signature")
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Assessment signature copied from profile", "action", "assessment.apply_profile_signature", "user_id", user.ID.String(), "assessment_id", id)
	signatureReply(w, id, url)
	return nil
}

func (s *Service) readAssessmentSignature(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "training:read"); err != nil {
		return err
	}
	key := strings.ToLower(pythonTrim(r.PathValue("storage_key")))
	if !exerciseImageKey.MatchString(key) {
		return platform.Error(404, "Signature not found")
	}
	var storagePath, mediaType *string
	err := s.Auth.DB.QueryRow(r.Context(), `SELECT signature_storage_path,signature_content_type FROM crew_member_assessment WHERE signature_storage_key=$1`, key).Scan(&storagePath, &mediaType)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && storagePath == nil {
		return platform.Error(404, "Signature not found")
	}
	if err != nil {
		return err
	}
	mime := "application/octet-stream"
	if mediaType != nil && *mediaType != "" {
		mime = *mediaType
	}
	err = s.Storage.ServeMediaResponse(w, r, filestorage.Media, *storagePath, key, mime)
	if errors.Is(err, filestorage.ErrInvalidPath) || errors.Is(err, filestorage.ErrNotFound) {
		return platform.Error(404, "Signature not found")
	}
	return err
}

func (s *Service) updateAssessmentSignature(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	schema := platform.Schema{Fields: []platform.Field{
		{Name: "signature", Kind: "string", Nullable: true},
		{Name: "url", Kind: "string", Nullable: true},
	}}
	path, body, err := libraryInput(r, &schema, "assessment_id")
	if err != nil {
		return err
	}
	id, _ := path["assessment_id"].(int64)
	signature := ""
	if value, ok := body["signature"].(string); ok && value != "" {
		signature = value
	} else if value, ok := body["url"].(string); ok {
		signature = value
	}
	signature = pythonTrim(signature)
	if signature == "" {
		return platform.Error(400, "signature is required")
	}
	assessment, err := s.signatureAssessment(id, r)
	if err != nil {
		return err
	}
	_, err = s.Auth.DB.Exec(r.Context(), `UPDATE crew_member_assessment SET signature=$2,signature_storage_path=NULL,signature_storage_key=NULL,signature_content_type=NULL,signature_size_bytes=NULL,signature_sha256=NULL,signed_at=now(),updated_at=now() WHERE id=$1`, id, signature)
	if err != nil {
		return err
	}
	if oldPath := assessment.text("signature_storage_path"); oldPath != "" {
		if err = s.Storage.Delete(r.Context(), filestorage.Media, oldPath); err != nil {
			return err
		}
	}
	platform.LogModule("app.audit", r.Context()).Info("Assessment signature updated", "action", "assessment.update_signature", "user_id", user.ID.String(), "assessment_id", id)
	signatureReply(w, id, signature)
	return nil
}
