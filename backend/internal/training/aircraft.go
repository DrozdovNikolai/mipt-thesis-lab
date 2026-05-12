package training

import (
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

type Service struct {
	Auth    *auth.Service
	Storage *filestorage.Store
}
type Aircraft struct {
	ID        int64     `json:"id"`
	AirlineID int64     `json:"airlineId"`
	Code      string    `json:"code"`
	Name      *string   `json:"name"`
	Active    bool      `json:"active"`
	ColorHex  string    `json:"colorHex"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

const aircraftColumns = "id,airline_id,code,name,active,color_hex,created_at,updated_at"

func scanAircraft(row pgx.Row) (Aircraft, error) {
	var a Aircraft
	err := row.Scan(&a.ID, &a.AirlineID, &a.Code, &a.Name, &a.Active, &a.ColorHex, &a.CreatedAt, &a.UpdatedAt)
	return a, err
}
func (s *Service) Register(mux *platform.Router) {
	if s.Storage == nil {
		s.Storage = filestorage.New(s.Auth.Config.Storage)
	}
	s.registerPositions(mux)
	s.registerGrading(mux)
	s.registerCompetencies(mux)
	s.registerAssessmentUsers(mux)
	s.registerAssessmentScenarios(mux)
	s.registerContentSets(mux)
	s.registerMediaReads(mux)
	s.registerMediaWrites(mux)
	s.registerMediaUploads(mux)
	s.registerAssessmentSignatures(mux)
	s.registerAssessmentReports(mux)
	s.registerAirlines(mux)
	s.registerLibrary(mux)
	s.registerScenarioEditor(mux)
	s.registerCommanderTrainings(mux)
	s.registerCommanderCatalogs(mux)
	s.registerCommanderPilots(mux)
	s.registerCommanderAnalytics(mux)
	s.registerRuntime(mux)
	s.registerTrainings(mux)
	s.registerDrafts(mux)
	mux.HandleFunc("POST "+s.Auth.Config.APIPrefix+"/training/assessments/finalize", platform.Wrap(s.finalizeAssessments))
	mux.HandleFunc("GET "+s.Auth.Config.APIPrefix+"/training/trainings/{training_id}/submit-status", platform.Wrap(s.readSubmitStatus))
	mux.HandleFunc("POST "+s.Auth.Config.APIPrefix+"/training/trainings/{training_id}/submit", platform.Wrap(s.submitTraining))
	mux.HandleFunc("POST "+s.Auth.Config.APIPrefix+"/training/trainings/{training_id}/sync", platform.Wrap(s.syncTraining))
	p := s.Auth.Config.APIPrefix + "/training/aircraft"
	mux.HandleFunc("GET "+p, platform.Wrap(s.listAircraft))
	mux.HandleFunc("POST "+p, platform.Wrap(s.createAircraft))
	mux.HandleFunc("PUT "+p+"/{aircraft_id}", platform.Wrap(s.updateAircraft))
	mux.HandleFunc("DELETE "+p+"/{aircraft_id}", platform.Wrap(s.deleteAircraft))
}
func (s *Service) listAircraft(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	airlineID := u.AirlineID
	if values, present := r.URL.Query()["airlineId"]; present {
		raw := values[len(values)-1]
		id, e := strconv.ParseInt(raw, 10, 64)
		if e != nil {
			return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": []any{platform.Detail("int_parsing", "Input should be a valid integer, unable to parse string as an integer", []any{"query", "airlineId"}, raw, nil)}}}
		}
		airlineID = &id
	}
	output := []Aircraft{}
	if airlineID != nil {
		rows, err := s.Auth.DB.Query(r.Context(), "SELECT "+aircraftColumns+" FROM aircraft_airline WHERE airline_id=$1 ORDER BY code,id", airlineID)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			a, err := scanAircraft(rows)
			if err != nil {
				return err
			}
			output = append(output, a)
		}
		if err = rows.Err(); err != nil {
			return err
		}
	}
	platform.WriteJSON(w, 200, output)
	return nil
}
func aircraftFields(create bool) []platform.Field {
	fields := []platform.Field{{Name: "code", Kind: "string", Required: create, Nullable: !create, Min: 1, Max: 100}, {Name: "name", Kind: "string", Nullable: true, Max: 255}, {Name: "active", Kind: "boolean", Nullable: !create}, {Name: "color_hex", Alias: "colorHex", Kind: "string", Nullable: true, Pattern: "^#[0-9A-Fa-f]{6}$"}}
	if create {
		fields[2].Default = true
		fields[3].Default = "#284692"
		fields = append(fields, platform.Field{Name: "airline_id", Alias: "airlineId", Kind: "integer", Required: true})
	}
	return fields
}
func (s *Service) createAircraft(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	b, err := platform.ReadObject(r, aircraftFields(true)...)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	var exists bool
	if err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM airline WHERE id=$1)`, b.Int("airline_id")).Scan(&exists); err != nil {
		return err
	}
	if !exists {
		return platform.Error(404, "Airline not found")
	}
	code := cases.Upper(language.Und).String(strings.TrimSpace(b.String("code")))
	if code == "" {
		return platform.Error(400, "Aircraft code is required")
	}
	if err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM aircraft_airline WHERE airline_id=$1 AND lower(code)=lower($2))`, b.Int("airline_id"), code).Scan(&exists); err != nil {
		return err
	}
	if exists {
		return platform.Error(400, "Aircraft code already exists")
	}
	name := b.StringPtr("name")
	if name != nil {
		trimmed := strings.TrimSpace(*name)
		name = &trimmed
	}
	color := strings.ToUpper(b.String("color_hex"))
	if color == "" {
		color = "#284692"
	}
	a, err := scanAircraft(tx.QueryRow(r.Context(), "INSERT INTO aircraft_airline(airline_id,code,name,active,color_hex) VALUES($1,$2,$3,$4,$5) RETURNING "+aircraftColumns, b.Int("airline_id"), code, name, b.Bool("active"), color))
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	platform.WriteJSON(w, 201, a)
	return nil
}
func (s *Service) updateAircraft(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	id, err := platform.PathInt(r, "aircraft_id")
	if err != nil {
		return err
	}
	b, err := platform.ReadObject(r, aircraftFields(false)...)
	if err != nil {
		return err
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	a, err := scanAircraft(tx.QueryRow(r.Context(), "SELECT "+aircraftColumns+" FROM aircraft_airline WHERE id=$1 FOR UPDATE", id))
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Aircraft not found")
	}
	if err != nil {
		return err
	}
	original := a
	if b.Has("code") && b["code"] != nil {
		code := cases.Upper(language.Und).String(strings.TrimSpace(b.String("code")))
		if code == "" {
			return platform.Error(400, "Aircraft code is required")
		}
		var exists bool
		if err = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM aircraft_airline WHERE airline_id=$1 AND lower(code)=lower($2) AND id<>$3)`, a.AirlineID, code, id).Scan(&exists); err != nil {
			return err
		}
		if exists {
			return platform.Error(400, "Aircraft code already exists")
		}
		a.Code = code
	}
	if b.Has("name") {
		a.Name = b.StringPtr("name")
		if a.Name != nil {
			v := strings.TrimSpace(*a.Name)
			if v == "" {
				a.Name = nil
			} else {
				a.Name = &v
			}
		}
	}
	if b.Has("active") {
		a.Active = b.Bool("active")
	}
	if b.Has("color_hex") {
		a.ColorHex = strings.ToUpper(b.String("color_hex"))
		if a.ColorHex == "" {
			a.ColorHex = "#284692"
		}
	}
	namesEqual := a.Name == nil && original.Name == nil || a.Name != nil && original.Name != nil && *a.Name == *original.Name
	if a.Code != original.Code || !namesEqual || a.Active != original.Active || a.ColorHex != original.ColorHex {
		a, err = scanAircraft(tx.QueryRow(r.Context(), "UPDATE aircraft_airline SET code=$1,name=$2,active=$3,color_hex=$4,updated_at=now() WHERE id=$5 RETURNING "+aircraftColumns, a.Code, a.Name, a.Active, a.ColorHex, id))
		if err != nil {
			return err
		}
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, a)
	return nil
}
func (s *Service) deleteAircraft(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r, "users:write"); err != nil {
		return err
	}
	id, err := platform.PathInt(r, "aircraft_id")
	if err != nil {
		return err
	}
	tag, err := s.Auth.DB.Exec(r.Context(), `DELETE FROM aircraft_airline WHERE id=$1`, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return platform.Error(404, "Aircraft not found")
	}
	w.WriteHeader(204)
	return nil
}
