package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"north55/backend/internal/datamigration"
)

func run() error {
	action := flag.String("action", "plan", "plan, apply or rollback")
	runID := flag.String("run-id", "", "UUID identifying one reviewed migration run")
	expected := flag.String("expected-plan-sha256", "", "reviewed plan fingerprint required by apply")
	trainingIDs := flag.String("training-ids", "", "optional comma-separated reviewed training IDs; omit to audit all pending rows")
	flag.Parse()
	dsn := os.Getenv("NORTH55_MIGRATION_DATABASE_URL")
	if dsn == "" {
		return errors.New("NORTH55_MIGRATION_DATABASE_URL must explicitly name the migration target")
	}
	if *action != "plan" && *action != "apply" && *action != "rollback" {
		return errors.New("action must be plan, apply or rollback")
	}
	var scope []int64
	if *trainingIDs != "" {
		if *action == "rollback" {
			return errors.New("rollback uses the stored run scope; do not pass --training-ids")
		}
		for _, value := range strings.Split(*trainingIDs, ",") {
			id, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64)
			if err != nil || id <= 0 {
				return errors.New("training IDs must be positive integers separated by commas")
			}
			scope = append(scope, id)
		}
	}
	var id uuid.UUID
	var err error
	if *action != "plan" {
		id, err = uuid.Parse(*runID)
		if err != nil || id == uuid.Nil {
			return errors.New("a nonzero --run-id UUID is required")
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return errors.New("invalid migration database configuration")
	}
	cfg.ConnConfig.RuntimeParams["application_name"] = "north55-submission-status-migration"
	cfg.ConnConfig.RuntimeParams["lock_timeout"] = "10s"
	db, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return err
	}
	defer db.Close()
	var result any
	switch *action {
	case "plan":
		result, err = datamigration.PlanForTrainings(ctx, db, scope)
	case "apply":
		result, err = datamigration.ApplyForTrainings(ctx, db, id, *expected, scope)
	case "rollback":
		result, err = datamigration.Rollback(ctx, db, id)
	}
	if err != nil {
		return err
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	return encoder.Encode(result)
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
