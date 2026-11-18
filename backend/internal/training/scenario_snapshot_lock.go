package training

import (
	"context"
	"fmt"
)

// Snapshot creation holds the exclusive lock while loading and freezing the
// source graph. Content writers hold the shared lock through their commit, so
// their post-commit media cleanup cannot race a snapshot of the old graph.
// Shared writer locks retain the existing editor/editor conflict behavior.
// Callers must use a transaction; the database releases the lock on rollback.
func lockScenarioSnapshotSource(ctx context.Context, db runtimeDB, scenarioID any, contentWrite bool) error {
	query := `SELECT pg_advisory_xact_lock(hashtextextended('55north:scenario-snapshot:' || $1::text, 0))`
	if contentWrite {
		query = `SELECT pg_advisory_xact_lock_shared(hashtextextended('55north:scenario-snapshot:' || $1::text, 0))`
	}
	_, err := db.Exec(ctx, query, fmt.Sprint(scenarioID))
	return err
}
