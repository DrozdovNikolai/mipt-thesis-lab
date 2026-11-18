package auth

import (
	"context"
	"fmt"
	"math/big"
	"strings"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/platform"
)

type userAircraftRef struct {
	ID   *big.Int
	Code string
}

func userAircraftReference(value any) (userAircraftRef, error) {
	var id *big.Int
	switch value := value.(type) {
	case int64:
		id = big.NewInt(value)
	case *big.Int:
		id = value
	case string:
		value = userPythonTrim(value)
		if value == "" {
			return userAircraftRef{}, nil
		}
		digits, decimal := []byte{}, true
		for _, r := range value {
			if !userEmailRange(r, userEmailUnicode.Digits) {
				return userAircraftRef{Code: value}, nil
			}
			found := false
			for _, zero := range userEmailUnicode.DecimalZeroes {
				if r >= zero && r < zero+10 {
					digits = append(digits, byte(r-zero)+'0')
					found = true
					break
				}
			}
			decimal = decimal && found
		}
		if !decimal {
			return userAircraftRef{}, platform.Error(400, "invalid literal for int() with base 10: "+userEmailQuote(value))
		}
		if len(digits) > 4300 {
			return userAircraftRef{}, platform.Error(400, fmt.Sprintf("Exceeds the limit (4300 digits) for integer string conversion: value has %d digits; use sys.set_int_max_str_digits() to increase the limit", utf8.RuneCountInString(value)))
		}
		id, _ = new(big.Int).SetString(string(digits), 10)
	default:
		return userAircraftRef{}, fmt.Errorf("invalid normalized aircraft reference type %T", value)
	}
	if id.Sign() <= 0 {
		return userAircraftRef{}, nil
	}
	return userAircraftRef{ID: id}, nil
}

func userAdminAircraft(ctx context.Context, tx pgx.Tx, airline any, raw []any, flush func() error) ([]int64, error) {
	refs, seen := []userAircraftRef{}, map[string]bool{}
	for _, value := range raw {
		ref, err := userAircraftReference(value)
		if err != nil {
			return nil, err
		}
		key := "code:" + ref.Code
		if ref.ID != nil {
			key = "id:" + ref.ID.String()
		} else if ref.Code == "" {
			continue
		}
		if !seen[key] {
			refs = append(refs, ref)
			seen[key] = true
		}
	}
	if len(refs) == 0 {
		return []int64{}, nil
	}
	if airline == nil {
		return nil, platform.Error(400, "airline_id is required when aircraft_ids are provided")
	}
	if err := flush(); err != nil {
		return nil, err
	}
	ids, codes := []int64{}, []string{}
	lower, upper := cases.Lower(language.Und), cases.Upper(language.Und)
	for _, ref := range refs {
		if ref.ID != nil {
			if !ref.ID.IsInt64() {
				return nil, fmt.Errorf("aircraft id exceeds PostgreSQL bigint range")
			}
			ids = append(ids, ref.ID.Int64())
		} else {
			codes = append(codes, lower.String(ref.Code))
		}
	}
	rows, err := tx.Query(ctx, `SELECT id,code FROM aircraft_airline WHERE airline_id=$1 AND (id=ANY($2::bigint[]) OR lower(code)=ANY($3::text[]))`, airline, ids, codes)
	if err != nil {
		return nil, err
	}
	byID, byCode := map[int64]bool{}, map[string]int64{}
	for rows.Next() {
		var id int64
		var code string
		if err := rows.Scan(&id, &code); err != nil {
			rows.Close()
			return nil, err
		}
		byID[id], byCode[lower.String(code)] = true, id
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	missingCodes, seenCodes := []string{}, map[string]bool{}
	for _, ref := range refs {
		if ref.ID == nil && byCode[lower.String(ref.Code)] == 0 {
			code := upper.String(ref.Code)
			if !seenCodes[code] {
				missingCodes, seenCodes[code] = append(missingCodes, code), true
			}
		}
	}
	for _, code := range missingCodes {
		id, err := userAdminWriteRow(ctx, tx, "aircraft_airline", userAdminRow{"airline_id": airline, "code": code, "name": code, "active": true, "color_hex": "#284692"}, nil)
		if err != nil {
			return nil, err
		}
		byID[id], byCode[lower.String(code)] = true, id
	}
	result, missing, assigned := []int64{}, []string{}, map[int64]bool{}
	for _, ref := range refs {
		id, text := int64(0), ref.Code
		if ref.ID != nil {
			text = ref.ID.String()
			if byID[ref.ID.Int64()] {
				id = ref.ID.Int64()
			}
		} else {
			id = byCode[lower.String(ref.Code)]
		}
		if id == 0 {
			missing = append(missing, text)
		} else if !assigned[id] {
			assigned[id] = true
			result = append(result, id)
		}
	}
	if len(missing) > 0 {
		suffix := ""
		if len(missing) > 10 {
			suffix = "..."
		}
		return nil, platform.Error(400, "Aircraft not found for airline: "+strings.Join(missing[:min(10, len(missing))], ", ")+suffix)
	}
	return result, nil
}

func userAdminAssignAircraft(ctx context.Context, tx pgx.Tx, user int64, ids []int64) error {
	if len(ids) == 0 {
		return nil
	}
	_, err := tx.Exec(ctx, `INSERT INTO user_aircraft(user_id,aircraft_id) SELECT $1,unnest($2::bigint[])`, user, ids)
	return err
}
