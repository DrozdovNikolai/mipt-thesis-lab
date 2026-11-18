package training

import (
	"errors"
	"net/http"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

var exerciseImageKey = regexp.MustCompile(`^[a-f0-9]{32}\.(png|jpg|jpeg|webp)$`)
var scenarioPDFKey = regexp.MustCompile(`^[a-f0-9]{32}\.pdf$`)

func (s *Service) registerMediaReads(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("GET "+p+"/exercise-images/{storage_key}", platform.Wrap(s.readExerciseImage))
	mux.HandleFunc("GET "+p+"/scenario-pdfs/{storage_key}", platform.Wrap(s.readScenarioPDF))
}

func (s *Service) readExerciseImage(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	key := strings.ToLower(pythonTrim(r.PathValue("storage_key")))
	if !exerciseImageKey.MatchString(key) {
		return platform.Error(404, "Image not found")
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
	var storagePath, mediaType *string
	err = s.Auth.DB.QueryRow(ctx, `SELECT i.storage_path,i.content_type FROM exercise_image i
JOIN exercise e ON e.id=i.exercise_id JOIN module m ON m.id=e.module_id JOIN scenario sc ON sc.id=m.scenario_id
WHERE i.storage_key=$1 AND sc.airline_id=$2 AND sc.aircraft_id=ANY($3::bigint[]) AND sc.deleted_at IS NULL`, key, airline, aircraft).Scan(&storagePath, &mediaType)
	if errors.Is(err, pgx.ErrNoRows) {
		err = s.Auth.DB.QueryRow(ctx, `SELECT i.storage_path,i.content_type FROM training_session_exercise_image i
JOIN training_session_exercise e ON e.id=i.training_session_exercise_id
JOIN training_session t ON t.id=e.training_session_id
LEFT JOIN scenario sc ON sc.id=t.scenario_id_snapshot
WHERE i.storage_key=$1 AND (t.instructor_id=$2 OR sc.airline_id=$3)
AND (t.aircraft_id_snapshot=ANY($4::bigint[]) OR sc.aircraft_id=ANY($4::bigint[]))
ORDER BY i.created_at DESC,i.id DESC LIMIT 1`, key, user.InternalID, airline, aircraft).Scan(&storagePath, &mediaType)
	}
	if errors.Is(err, pgx.ErrNoRows) || err == nil && storagePath == nil {
		return platform.Error(404, "Image not found")
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
		return platform.Error(404, "Image not found")
	}
	return err
}

func (s *Service) readScenarioPDF(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	key := strings.ToLower(pythonTrim(r.PathValue("storage_key")))
	if !scenarioPDFKey.MatchString(key) {
		return platform.Error(404, "PDF not found")
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
	var storagePath, mediaType, originalFilename *string
	err = s.Auth.DB.QueryRow(ctx, `SELECT p.storage_path,p.content_type,p.original_filename FROM scenario_pdf p
JOIN scenario sc ON sc.id=p.scenario_id
WHERE p.storage_key=$1 AND sc.airline_id=$2 AND sc.aircraft_id=ANY($3::bigint[]) AND sc.deleted_at IS NULL`, key, airline, aircraft).Scan(&storagePath, &mediaType, &originalFilename)
	if errors.Is(err, pgx.ErrNoRows) {
		err = s.Auth.DB.QueryRow(ctx, `SELECT p.storage_path,p.content_type,p.original_filename FROM training_session_scenario_pdf p
JOIN training_session t ON t.id=p.training_session_id
LEFT JOIN scenario sc ON sc.id=t.scenario_id_snapshot
WHERE p.storage_key=$1 AND (t.instructor_id=$2 OR sc.airline_id=$3)
AND (t.aircraft_id_snapshot=ANY($4::bigint[]) OR sc.aircraft_id=ANY($4::bigint[]))
ORDER BY p.created_at DESC,p.id DESC LIMIT 1`, key, user.InternalID, airline, aircraft).Scan(&storagePath, &mediaType, &originalFilename)
	}
	if errors.Is(err, pgx.ErrNoRows) || err == nil && storagePath == nil {
		return platform.Error(404, "PDF not found")
	}
	if err != nil {
		return err
	}
	mime := "application/pdf"
	if mediaType != nil && *mediaType != "" {
		mime = *mediaType
	}
	filename := key
	if originalFilename != nil && *originalFilename != "" {
		filename = *originalFilename
	}
	err = s.Storage.ServeMediaResponse(w, r, filestorage.Media, *storagePath, filename, mime)
	if errors.Is(err, filestorage.ErrInvalidPath) || errors.Is(err, filestorage.ErrNotFound) {
		return platform.Error(404, "PDF not found")
	}
	return err
}
