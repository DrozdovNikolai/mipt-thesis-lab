package auth

import (
	"errors"
	"mime/multipart"
	"net/http"
	"regexp"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

var userMediaKeyPattern = regexp.MustCompile(`^[a-f0-9]{32}\.(png|jpg|jpeg|webp)$`)

func (s *Service) registerUserMedia(mux *platform.Router) {
	p := s.Config.APIPrefix + "/users"
	mux.HandleFunc("POST "+p+"/me/photo/upload", platform.Wrap(s.uploadMyPhoto))
	mux.HandleFunc("POST "+p+"/{user_id}/photo/upload", platform.Wrap(s.uploadUserPhoto))
	mux.HandleFunc("POST "+p+"/me/signature/upload", platform.Wrap(s.uploadMySignature))
	mux.HandleFunc("GET "+p+"/photos/{storage_key}", platform.Wrap(s.readUserPhoto))
	mux.HandleFunc("GET "+p+"/signatures/{storage_key}", platform.Wrap(s.readUserSignature))
}

func userMediaFile(r *http.Request) (multipart.File, *multipart.FileHeader, error) {
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		if errors.Is(err, http.ErrNotMultipart) {
			return nil, nil, userMediaMissingFile()
		}
		if r.MultipartForm != nil {
			_ = r.MultipartForm.RemoveAll()
		}
		return nil, nil, platform.Error(400, "There was an error parsing the body")
	}
	file, header, err := r.FormFile("file")
	if err == nil {
		return file, header, nil
	}
	if r.MultipartForm != nil {
		_ = r.MultipartForm.RemoveAll()
	}
	if errors.Is(err, http.ErrMissingFile) || errors.Is(err, http.ErrNotMultipart) {
		return nil, nil, userMediaMissingFile()
	}
	return nil, nil, platform.Error(400, "There was an error parsing the body")
}

func userMediaMissingFile() error {
	return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": []any{platform.Detail("missing", "Field required", []any{"body", "file"}, nil, nil)}}}
}

func userMediaURL(r *http.Request, prefix, kind, key string) string {
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	if forwarded := r.Header.Get("X-Forwarded-Proto"); forwarded != "" {
		scheme = strings.TrimSpace(strings.Split(forwarded, ",")[0])
	}
	return scheme + "://" + r.Host + prefix + "/users/" + kind + "/" + key
}

func (s *Service) uploadMyPhoto(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	file, header, err := userMediaFile(r)
	if err != nil {
		return err
	}
	defer file.Close()
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	return s.uploadUserMedia(w, r, user, file, header, false)
}

func (s *Service) uploadUserPhoto(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Authenticate(r, "users:write"); err != nil {
		return err
	}
	file, header, err := userMediaFile(r)
	if err != nil {
		return err
	}
	defer file.Close()
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	user, err := readUserAdminRow(s.DB.QueryRow(r.Context(), `SELECT to_jsonb(u) FROM users u WHERE u.public_id=$1`, r.PathValue("user_id")))
	if err != nil {
		return err
	}
	if user == nil {
		return platform.Error(404, "User not found")
	}
	publicID, err := uuid.Parse(user["public_id"].(string))
	if err != nil {
		return err
	}
	return s.uploadUserMedia(w, r, &User{InternalID: user["id"].(int64), ID: publicID}, file, header, false)
}

func (s *Service) uploadMySignature(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	file, header, err := userMediaFile(r)
	if err != nil {
		return err
	}
	defer file.Close()
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	return s.uploadUserMedia(w, r, user, file, header, true)
}

func (s *Service) uploadUserMedia(w http.ResponseWriter, r *http.Request, user *User, file multipart.File, header *multipart.FileHeader, signature bool) error {
	field, name, folder, limit := "photo", "photoUrl", "photos", s.Config.MediaPhotoMaxFileBytes
	if signature {
		field, name, folder, limit = "signature", "signatureUrl", "signatures", s.Config.MediaSignatureMaxFileBytes
	}
	storage := filestorage.New(s.Config.Storage)
	stored, err := storage.SaveImageUpload(r.Context(), file, header.Filename, header.Header.Get("Content-Type"), "user_"+folder+"/"+user.ID.String(), limit)
	if err != nil {
		var media *filestorage.MediaError
		if errors.As(err, &media) {
			return platform.Error(media.Status, media.Message)
		}
		return err
	}
	url := userMediaURL(r, s.Config.APIPrefix, folder, stored.StorageKey)
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		_ = storage.Delete(r.Context(), filestorage.Media, stored.StoragePath)
		return platform.Error(500, "Failed to upload "+field)
	}
	defer tx.Rollback(r.Context())
	var oldPath *string
	selectSQL := "SELECT " + field + "_storage_path FROM user_info WHERE id=$1"
	err = tx.QueryRow(r.Context(), selectSQL, user.InternalID).Scan(&oldPath)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		_ = storage.Delete(r.Context(), filestorage.Media, stored.StoragePath)
		return platform.Error(500, "Failed to upload "+field)
	}
	insertSQL := "INSERT INTO user_info (id," + field + "_storage_path," + field + "_storage_key," + field + "_content_type," + field + "_size_bytes," + field + "_sha256," + field + "_url) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO UPDATE SET " + field + "_storage_path=EXCLUDED." + field + "_storage_path," + field + "_storage_key=EXCLUDED." + field + "_storage_key," + field + "_content_type=EXCLUDED." + field + "_content_type," + field + "_size_bytes=EXCLUDED." + field + "_size_bytes," + field + "_sha256=EXCLUDED." + field + "_sha256," + field + "_url=EXCLUDED." + field + "_url"
	_, err = tx.Exec(r.Context(), insertSQL, user.InternalID, stored.StoragePath, stored.StorageKey, stored.ContentType, stored.SizeBytes, stored.SHA256, url)
	if err == nil {
		err = tx.Commit(r.Context())
	}
	if err != nil {
		_ = storage.Delete(r.Context(), filestorage.Media, stored.StoragePath)
		return platform.Error(500, "Failed to upload "+field)
	}
	if oldPath != nil && *oldPath != stored.StoragePath {
		if err := storage.Delete(r.Context(), filestorage.Media, *oldPath); err != nil {
			return err
		}
	}
	platform.WriteJSON(w, 200, map[string]any{name: url})
	return nil
}

func (s *Service) readUserPhoto(w http.ResponseWriter, r *http.Request) error {
	return s.readUserMedia(w, r, false)
}

func (s *Service) readUserSignature(w http.ResponseWriter, r *http.Request) error {
	return s.readUserMedia(w, r, true)
}

func (s *Service) readUserMedia(w http.ResponseWriter, r *http.Request, signature bool) error {
	if _, err := s.Authenticate(r); err != nil {
		return err
	}
	field, label := "photo", "Photo"
	if signature {
		field, label = "signature", "Signature"
	}
	key := strings.ToLower(strings.TrimSpace(r.PathValue("storage_key")))
	if !userMediaKeyPattern.MatchString(key) {
		return platform.Error(404, label+" not found")
	}
	var storagePath, contentType *string
	query := "SELECT " + field + "_storage_path," + field + "_content_type FROM user_info WHERE " + field + "_storage_key=$1"
	err := s.DB.QueryRow(r.Context(), query, key).Scan(&storagePath, &contentType)
	if errors.Is(err, pgx.ErrNoRows) || storagePath == nil {
		return platform.Error(404, label+" not found")
	}
	if err != nil {
		return err
	}
	storage := filestorage.New(s.Config.Storage)
	mime := "application/octet-stream"
	if contentType != nil && *contentType != "" {
		mime = *contentType
	}
	err = storage.ServeMediaResponse(w, r, filestorage.Media, *storagePath, key, mime)
	if errors.Is(err, filestorage.ErrNotFound) || errors.Is(err, filestorage.ErrInvalidPath) {
		return platform.Error(404, label+" not found")
	}
	return err
}
