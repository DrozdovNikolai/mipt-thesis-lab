package training

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/training/canonical"
)

const scenarioRevisionMetadata = "created_by kind label client_entry_id client_created_at_ms action branch_id parent_client_entry_id base_client_entry_id restored_from_client_entry_id"
const scenarioRevisionOrder = "client_created_at_ms DESC NULLS LAST,created_at DESC,id DESC"

func scenarioRevisionByClient(ctx context.Context, db runtimeDB, scenarioID int64, clientID string) (record, error) {
	row, err := queryRecord(ctx, db, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 AND client_entry_id=$2`, scenarioID, clientID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return row, err
}

func createScenarioRevision(ctx context.Context, db runtimeDB, scenarioID int64, metadata record, snapshot map[string]any, resolveParents bool) (record, error) {
	client := metadata.text("client_entry_id")
	if client != "" {
		if row, err := scenarioRevisionByClient(ctx, db, scenarioID, client); err != nil || row != nil {
			return row, err
		}
	}
	signature, err := canonical.SHA256(snapshot)
	if err != nil {
		return nil, err
	}
	lookup := func() (record, error) {
		if client != "" {
			return scenarioRevisionByClient(ctx, db, scenarioID, client)
		}
		row, err := queryRecord(ctx, db, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 AND signature=$2 ORDER BY revision_number DESC,id DESC LIMIT 1`, scenarioID, signature)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return row, err
	}
	if client == "" {
		if row, err := lookup(); err != nil || row != nil {
			return row, err
		}
	}
	if _, err = db.Exec(ctx, `SELECT id FROM scenario WHERE id=$1 FOR UPDATE`, scenarioID); err != nil {
		return nil, err
	}
	if row, err := lookup(); err != nil || row != nil {
		return row, err
	}
	var next int64
	if err = db.QueryRow(ctx, `SELECT coalesce(max(revision_number),0)+1 FROM scenario_revision WHERE scenario_id=$1`, scenarioID).Scan(&next); err != nil {
		return nil, err
	}
	data := metadata.project(scenarioRevisionMetadata)
	data["scenario_id"], data["revision_number"], data["signature"], data["snapshot_json"] = scenarioID, next, signature, snapshot
	data["parent_revision_id"] = nil
	if parent := metadata.text("parent_client_entry_id"); parent != "" {
		row, err := scenarioRevisionByClient(ctx, db, scenarioID, parent)
		if err != nil {
			return nil, err
		}
		if row != nil {
			data["parent_revision_id"] = row["id"]
		}
	}
	row, err := insertTrainingRow(ctx, db, "scenario_revision", data)
	if err != nil {
		return nil, err
	}
	if resolveParents && (metadata["client_entry_id"] != nil || (metadata["parent_client_entry_id"] != nil && data["parent_revision_id"] == nil)) {
		if err = resolveScenarioRevisionParents(ctx, db, scenarioID); err != nil {
			return nil, err
		}
		return libraryFind(ctx, db, "scenario_revision", row["id"])
	}
	return row, nil
}

func resolveScenarioRevisionParents(ctx context.Context, db runtimeDB, scenarioID int64) error {
	_, err := db.Exec(ctx, `UPDATE scenario_revision child SET parent_revision_id=parent.id FROM scenario_revision parent WHERE child.scenario_id=$1 AND child.parent_revision_id IS NULL AND child.parent_client_entry_id IS NOT NULL AND parent.scenario_id=child.scenario_id AND parent.client_entry_id=child.parent_client_entry_id`, scenarioID)
	return err
}

func pruneScenarioRevisions(ctx context.Context, db runtimeDB, scenarioID int64, keep int) error {
	if keep <= 0 {
		return nil
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(r) FROM scenario_revision r WHERE scenario_id=$1 ORDER BY `+scenarioRevisionOrder, scenarioID)
	if err != nil || len(rows) <= keep {
		return err
	}
	byID, byClient := map[int64]record{}, map[string]record{}
	protected := map[int64]bool{}
	pending := []int64{}
	protect := func(id int64) {
		if !protected[id] {
			protected[id] = true
			pending = append(pending, id)
		}
	}
	for i, row := range rows {
		byID[row.number("id")] = row
		if row.text("client_entry_id") != "" {
			byClient[row.text("client_entry_id")] = row
		}
		if i < keep {
			protect(row.number("id"))
		}
	}
	referenced, err := queryRecords(ctx, db, `SELECT jsonb_build_object('id',t.scenario_revision_id) FROM training_session t JOIN scenario_revision r ON r.id=t.scenario_revision_id WHERE r.scenario_id=$1`, scenarioID)
	if err != nil {
		return err
	}
	for _, row := range referenced {
		protect(row.number("id"))
	}
	for len(pending) > 0 {
		id := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		row := byID[id]
		if row == nil {
			continue
		}
		if row["parent_revision_id"] != nil {
			protect(row.number("parent_revision_id"))
		}
		for _, field := range []string{"parent_client_entry_id", "base_client_entry_id", "restored_from_client_entry_id"} {
			if parent := byClient[row.text(field)]; parent != nil {
				protect(parent.number("id"))
			}
		}
	}
	remove := []int64{}
	for _, row := range rows {
		if !protected[row.number("id")] {
			remove = append(remove, row.number("id"))
		}
	}
	_, err = db.Exec(ctx, `DELETE FROM scenario_revision r WHERE r.scenario_id=$1 AND r.id=ANY($2::bigint[]) AND NOT EXISTS(SELECT 1 FROM training_session t WHERE t.scenario_revision_id=r.id)`, scenarioID, remove)
	return err
}
