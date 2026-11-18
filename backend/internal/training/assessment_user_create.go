package training

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

var assessmentUserCreateSchema = platform.Schema{
	Fields: []platform.Field{
		{Name: "first_name", Alias: "firstName", Kind: "string", Required: true},
		{Name: "last_name", Alias: "lastName", Kind: "string", Required: true},
		{Name: "airline", Kind: "string", Nullable: true},
		{Name: "ac_type", Alias: "acType", Kind: "string", Nullable: true},
		{Name: "position_id", Alias: "positionId", Kind: "integer", Min: 1, Nullable: true},
		{Name: "position", Kind: "string", Nullable: true},
		{Name: "license", Kind: "string", Nullable: true},
		{Name: "email", Kind: "string", Nullable: true},
		{Name: "role", Kind: "string", Nullable: true},
	},
	Check: func(o platform.Object) string {
		if o["position_id"] != nil && pythonTrim(o.String("position")) != "" {
			return "Provide either position_id or position"
		}
		return ""
	},
}

func resolveAssessmentPosition(ctx context.Context, tx pgx.Tx, airline any, body platform.Object) (record, error) {
	var query string
	var args []any
	if body["position_id"] != nil {
		query = "SELECT to_jsonb(p) FROM airline_position p WHERE id=$1 AND airline_id IS NOT DISTINCT FROM $2::bigint LIMIT 1"
		args = []any{body["position_id"], airline}
	} else {
		name := assessmentUserWords(body.String("position"))
		if name == "" {
			return nil, nil
		}
		query = "SELECT to_jsonb(p) FROM airline_position p WHERE normalized_name=$1 AND airline_id IS NOT DISTINCT FROM $2::bigint LIMIT 1"
		args = []any{cases.Lower(language.Und).String(name), airline}
	}
	position, err := queryRecord(ctx, tx, query, args...)
	if !errors.Is(err, pgx.ErrNoRows) {
		return position, err
	}
	if body["position_id"] != nil {
		return nil, fmt.Errorf("Position not found for airline")
	}
	name := assessmentUserWords(body.String("position"))
	return queryRecord(ctx, tx, "INSERT INTO airline_position(airline_id,name,normalized_name) VALUES($1,$2,$3) RETURNING to_jsonb(airline_position)", airline, name, cases.Lower(language.Und).String(name))
}

func (s *Service) createAssessmentUser(w http.ResponseWriter, r *http.Request) error {
	author, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	body, err := platform.ReadSchema(r, assessmentUserCreateSchema)
	if err != nil {
		return err
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var airline any
	if author.AirlineID != nil {
		airline = *author.AirlineID
	}
	if body.String("airline") != "" {
		matches, err := queryRecords(ctx, tx, "SELECT to_jsonb(a) FROM airline a WHERE lower(name)=$1", cases.Lower(language.Und).String(body.String("airline")))
		if err != nil {
			return err
		}
		if len(matches) > 1 {
			return fmt.Errorf("multiple airlines match the supplied name")
		}
		if len(matches) == 1 {
			airline = matches[0].number("id")
		}
	}
	lower := cases.Lower(language.Und)
	base := strings.ReplaceAll(lower.String(body.String("first_name"))+"."+lower.String(body.String("last_name")), " ", "_")
	if body.String("email") != "" {
		local, _, _ := strings.Cut(body.String("email"), "@")
		base = strings.ReplaceAll(lower.String(local), ".", "_")
	}
	exists := func(column, value string) (bool, error) {
		var found bool
		err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM users WHERE "+column+"=$1)", value).Scan(&found)
		return found, err
	}
	login := base
	for counter := 1; ; counter++ {
		found, err := exists("login", login)
		if err != nil {
			return err
		}
		if !found {
			break
		}
		login = fmt.Sprintf("%s_%d", base, counter)
	}
	email := body.String("email")
	if email == "" {
		email = login + "@placeholder.local"
	} else {
		found, err := exists("email", email)
		if err != nil {
			return err
		}
		if found {
			local, domain, _ := strings.Cut(email, "@")
			if domain == "" {
				domain = "placeholder.local"
			}
			for counter := 1; ; counter++ {
				email = fmt.Sprintf("%s+%d@%s", local, counter, domain)
				found, err = exists("email", email)
				if err != nil {
					return err
				}
				if !found {
					break
				}
			}
		}
	}
	secret := make([]byte, 16)
	if _, err = rand.Read(secret); err != nil {
		return err
	}
	temporaryPassword := base64.RawURLEncoding.EncodeToString(secret)
	position, err := resolveAssessmentPosition(ctx, tx, airline, body)
	if err != nil {
		return err
	}
	if body.String("ac_type") != "" && airline == nil {
		return platform.Error(400, "airline is required when ac_type is provided")
	}
	hash, err := auth.HashPassword(temporaryPassword)
	if err != nil {
		return err
	}
	publicID, err := uuid.NewRandom()
	if err != nil {
		return err
	}
	var id int64
	err = tx.QueryRow(ctx, "INSERT INTO users(public_id,login,email,hashed_password,must_change_password,airline_id,is_active) VALUES($1,$2,$3,$4,true,$5,true) RETURNING id", publicID, login, email, hash, airline).Scan(&id)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, "INSERT INTO user_info(id,first_name,last_name,position_id,license_number) VALUES($1,$2,$3,$4,$5)", id, body["first_name"], body["last_name"], position["id"], body["license"])
	if err != nil {
		return err
	}
	var aircraftCode any
	if body.String("ac_type") != "" {
		code := assessmentUpper(pythonTrim(body.String("ac_type")))
		aircraft, err := queryRecord(ctx, tx, "SELECT to_jsonb(a) FROM aircraft_airline a WHERE airline_id=$1 AND lower(code)=$2 LIMIT 1", airline, lower.String(code))
		if errors.Is(err, pgx.ErrNoRows) {
			aircraft, err = queryRecord(ctx, tx, "INSERT INTO aircraft_airline(airline_id,code,name,active,color_hex) VALUES($1,$2,$2,true,'#284692') RETURNING to_jsonb(aircraft_airline)", airline, code)
		}
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO user_aircraft(user_id,aircraft_id) VALUES($1,$2)", id, aircraft["id"]); err != nil {
			return err
		}
		aircraftCode = aircraft["code"]
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Assessment user created", "user_id", author.ID, "action", "assessment.create_user", "target_user_id", id)
	var airlineName *string
	if airline != nil && airline.(int64) != 0 {
		err = s.Auth.DB.QueryRow(ctx, "SELECT name FROM airline WHERE id=$1 LIMIT 1", airline).Scan(&airlineName)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
	}
	var positionName any
	if name := assessmentUserWords(position.text("name")); name != "" {
		positionName = name
	}
	platform.WriteJSON(w, 201, commanderWire(record{"id": id, "first_name": body["first_name"], "last_name": body["last_name"], "airline": airlineName, "aircraft_code": aircraftCode, "position_id": position["id"], "position": positionName, "license": body["license"], "email": email, "role": body["role"], "temporary_password": temporaryPassword}))
	return nil
}
