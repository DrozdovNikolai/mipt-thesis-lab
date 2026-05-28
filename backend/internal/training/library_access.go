package training

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
)

func libraryAllowedAircraft(user *auth.User) ([]int64, error) {
	allowed := []int64{}
	for _, id := range user.AircraftIDs {
		if id > 0 {
			allowed = append(allowed, id)
		}
	}
	if len(allowed) == 0 {
		return nil, commanderError(400, "AIRCRAFT_REQUIRED", "User is not assigned to any aircraft")
	}
	return allowed, nil
}
func libraryContains(ids []int64, id int64) bool {
	for _, value := range ids {
		if value == id {
			return true
		}
	}
	return false
}

func libraryAircraft(ctx context.Context, db runtimeDB, user *auth.User, raw any, single, defaultFirst bool) ([]int64, error) {
	allowed, err := libraryAllowedAircraft(user)
	if err != nil {
		return nil, err
	}
	var candidate *big.Int
	code := ""
	switch value := raw.(type) {
	case int64:
		candidate = big.NewInt(value)
	case *big.Int:
		candidate = value
	case string:
		code = pythonTrim(value)
		if decimal, valid, digits := libraryDigits(code); digits {
			if !valid || len(decimal) > 4300 {
				return nil, fmt.Errorf("aircraft reference isdigit cannot be parsed as int")
			}
			candidate, _ = new(big.Int).SetString(decimal, 10)
			code = ""
		}
	}
	if candidate != nil && candidate.Sign() <= 0 {
		candidate = nil
	}
	if candidate != nil || code != "" {
		var resolved int64
		if candidate != nil {
			if candidate.IsInt64() {
				resolved = candidate.Int64()
			}
		} else {
			rows, e := queryRecords(ctx, db, `SELECT jsonb_build_object('id',a.id,'code',a.code) FROM user_aircraft ua JOIN aircraft_airline a ON a.id=ua.aircraft_id WHERE ua.user_id=$1 ORDER BY ua.id`, user.InternalID)
			if e != nil {
				return nil, e
			}
			lower := cases.Lower(language.Und)
			for _, row := range rows {
				if row.number("id") > 0 && pythonTrim(row.text("code")) != "" && lower.String(pythonTrim(row.text("code"))) == lower.String(code) {
					resolved = row.number("id")
				}
			}
		}
		if !libraryContains(allowed, resolved) {
			return nil, commanderError(403, "AIRCRAFT_FORBIDDEN", "User is not assigned to this aircraft")
		}
		return []int64{resolved}, nil
	}
	if defaultFirst {
		return allowed[:1], nil
	}
	if single && len(allowed) != 1 {
		return nil, commanderError(400, "AIRCRAFT_REQUIRED", "aircraft_id is required")
	}
	return allowed, nil
}

func libraryFind(ctx context.Context, db runtimeDB, table string, id any) (record, error) {
	if id == nil {
		return nil, nil
	}
	row, err := queryRecord(ctx, db, "SELECT to_jsonb(t) FROM "+table+" t WHERE id=$1", id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return row, err
}
func libraryScoped(row record, airline int64, aircraft []int64, active bool) bool {
	return row != nil && row["airline_id"] != nil && row.number("airline_id") == airline && libraryContains(aircraft, row.number("aircraft_id")) && (!active || row["archived_at"] == nil)
}
func librarySame(a, b any) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

func libraryUpdate(ctx context.Context, db runtimeDB, table string, old, changes record) error {
	keys := []string{}
	for key, value := range changes {
		if !librarySame(old[key], value) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	if len(keys) == 0 {
		return nil
	}
	sets, args := []string{}, []any{}
	for _, key := range keys {
		args = append(args, changes[key])
		sets = append(sets, fmt.Sprintf("%s=$%d", pgx.Identifier{key}.Sanitize(), len(args)))
	}
	if _, stamped := old["updated_at"]; stamped {
		sets = append(sets, "updated_at=now()")
	}
	args = append(args, old["id"])
	_, err := db.Exec(ctx, "UPDATE "+table+" SET "+strings.Join(sets, ",")+fmt.Sprintf(" WHERE id=$%d", len(args)), args...)
	return err
}

func libraryRequired(airline int64, aircraft []int64, row record, active bool, message string) error {
	if !libraryScoped(row, airline, aircraft, active) {
		return platform.Error(404, message)
	}
	return nil
}
