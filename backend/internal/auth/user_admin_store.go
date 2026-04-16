package auth

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/platform"
)

type userAdminRow map[string]any

func readUserAdminRow(row pgx.Row) (userAdminRow, error) {
	var raw []byte
	if err := row.Scan(&raw); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	var out userAdminRow
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&out); err != nil {
		return nil, err
	}
	for key, value := range out {
		if number, ok := value.(json.Number); ok {
			parsed, err := number.Int64()
			if err != nil {
				return nil, err
			}
			out[key] = parsed
		}
	}
	return out, nil
}

func userAdminDBValue(value any) (any, error) {
	if wide, ok := value.(*big.Int); ok {
		if !wide.IsInt64() {
			return nil, fmt.Errorf("user integer exceeds PostgreSQL bigint range")
		}
		return wide.Int64(), nil
	}
	return value, nil
}

func userAdminWriteRow(ctx context.Context, tx pgx.Tx, table string, row userAdminRow, id any) (int64, error) {
	switch table {
	case "users", "user_info", "airline_position", "aircraft_airline":
	default:
		return 0, fmt.Errorf("unsupported user admin table %q", table)
	}
	keys := make([]string, 0, len(row))
	for key := range row {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	columns, parameters, changes, predicates := []string{}, []string{}, []string{}, []string{}
	values := []any{}
	for i, key := range keys {
		value, err := userAdminDBValue(row[key])
		if err != nil {
			return 0, err
		}
		if date, ok := value.(time.Time); ok && key == "date_of_birth" {
			value = date.Format("2006-01-02")
		}
		column, parameter := pgx.Identifier{key}.Sanitize(), "$"+strconv.Itoa(i+1)
		columns, parameters = append(columns, column), append(parameters, parameter)
		changes = append(changes, column+"="+parameter)
		predicates = append(predicates, column+" IS DISTINCT FROM "+parameter)
		values = append(values, value)
	}
	if id == nil {
		var inserted int64
		err := tx.QueryRow(ctx, "INSERT INTO "+table+"("+strings.Join(columns, ",")+") VALUES("+strings.Join(parameters, ",")+") RETURNING id", values...).Scan(&inserted)
		return inserted, err
	}
	if len(changes) == 0 {
		return 0, nil
	}
	if table == "users" {
		changes = append(changes, "updated_at=now()")
	}
	values = append(values, id)
	_, err := tx.Exec(ctx, "UPDATE "+table+" SET "+strings.Join(changes, ",")+" WHERE id=$"+strconv.Itoa(len(values))+" AND ("+strings.Join(predicates, " OR ")+")", values...)
	return 0, err
}

func userAdminFind(ctx context.Context, tx pgx.Tx, publicID string) (userAdminRow, error) {
	user, err := readUserAdminRow(tx.QueryRow(ctx, `SELECT to_jsonb(u) FROM users u WHERE u.public_id=$1`, publicID))
	if err == nil && user == nil {
		err = platform.Error(404, "User not found")
	}
	return user, err
}

func userAdminUnique(ctx context.Context, tx pgx.Tx, field string, value any) error {
	if field != "login" && field != "email" {
		return fmt.Errorf("invalid user unique column")
	}
	var found bool
	if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM users WHERE "+field+"=$1)", value).Scan(&found); err != nil {
		return err
	}
	if found {
		return platform.Error(400, "User already exists ("+field+")")
	}
	return nil
}

func userAdminAirline(ctx context.Context, tx pgx.Tx, value any) error {
	if value == nil {
		return nil
	}
	value, err := userAdminDBValue(value)
	if err != nil {
		return err
	}
	var found bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM airline WHERE id=$1)`, value).Scan(&found); err != nil {
		return err
	}
	if !found {
		return platform.Error(400, "Airline not found")
	}
	return nil
}

func userAdminPosition(ctx context.Context, tx pgx.Tx, airline, position any, name string) (any, error) {
	if position == nil && name == "" {
		return nil, nil
	}
	if position != nil {
		value, err := userAdminDBValue(position)
		if err != nil {
			return nil, err
		}
		var id int64
		err = tx.QueryRow(ctx, `SELECT id FROM airline_position WHERE id=$1 AND airline_id IS NOT DISTINCT FROM $2::bigint LIMIT 1`, value, airline).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, platform.Error(400, "Position not found for airline")
		}
		return id, err
	}
	name = strings.Join(strings.FieldsFunc(name, userPythonSpace), " ")
	if name == "" {
		return nil, nil
	}
	key := cases.Lower(language.Und).String(name)
	var id int64
	err := tx.QueryRow(ctx, `SELECT id FROM airline_position WHERE normalized_name=$1 AND airline_id IS NOT DISTINCT FROM $2::bigint LIMIT 1`, key, airline).Scan(&id)
	if !errors.Is(err, pgx.ErrNoRows) {
		return id, err
	}
	return userAdminWriteRow(ctx, tx, "airline_position", userAdminRow{"airline_id": airline, "name": name, "normalized_name": key}, nil)
}

func userAdminResolveRoles(ctx context.Context, tx pgx.Tx, items []any) ([]int64, error) {
	ids := []uuid.UUID{}
	for _, value := range items {
		ids = append(ids, value.(uuid.UUID))
	}
	if len(ids) == 0 {
		return []int64{}, nil
	}
	rows, err := tx.Query(ctx, `SELECT id,public_id FROM roles WHERE public_id=ANY($1::uuid[])`, ids)
	if err != nil {
		return nil, err
	}
	found, result := map[uuid.UUID]bool{}, []int64{}
	for rows.Next() {
		var id int64
		var public uuid.UUID
		if err := rows.Scan(&id, &public); err != nil {
			rows.Close()
			return nil, err
		}
		found[public] = true
		result = append(result, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	missing := userMissingRoleIDs(ids, found)
	if len(missing) > 0 {
		return nil, platform.Error(400, "Roles not found: "+strings.Join(missing, ", "))
	}
	return result, nil
}

func userAdminReplaceRoles(ctx context.Context, tx pgx.Tx, id int64, roles []int64) error {
	// Preserve timestamps on retained links, including a repeated identical PUT.
	if _, err := tx.Exec(ctx, `DELETE FROM user_roles WHERE user_id=$1 AND NOT(role_id=ANY($2::bigint[]))`, id, roles); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `INSERT INTO user_roles(user_id,role_id) SELECT $1,w.id FROM unnest($2::bigint[]) w(id) WHERE NOT EXISTS(SELECT 1 FROM user_roles old WHERE old.user_id=$1 AND old.role_id=w.id)`, id, roles)
	return err
}
