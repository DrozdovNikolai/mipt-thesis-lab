package training

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

var trainingSyncSchema = platform.Schema{ForbidExtra: true, Fields: []platform.Field{
	{Name: "protocol_version", Alias: "protocolVersion", Kind: "literal_integer", Required: true, Choices: []string{"1"}},
	{Name: "writer_instance_id", Alias: "writerInstanceId", Kind: "uuid", Required: true},
	runtimeInt("writer_epoch", "writerEpoch", 1, false),
	{Name: "runtime", Kind: "object", Nullable: true, Schema: &runtimeSyncSchema},
	{Name: "assessment_state", Alias: "assessmentState", Kind: "object", Nullable: true, Schema: &draftSaveSchema},
}, Check: func(o platform.Object) string {
	writer := o["writer_instance_id"].(uuid.UUID)
	if writer.Version() != 7 || writer.Variant() != uuid.RFC4122 {
		return "writerInstanceId must be UUIDv7"
	}
	if o["runtime"] == nil && o["assessment_state"] == nil {
		return "sync must contain work"
	}
	if runtime, ok := o["runtime"].(platform.Object); ok {
		if runtime["writer_instance_id"] != writer || !jsonEqual(runtime["writer_epoch"], o["writer_epoch"]) {
			return "runtime writer must match envelope"
		}
		if len(runtime["crew_assignment_events"].([]any))+len(runtime["run_snapshots"].([]any)) > 200 {
			return "sync runtime prefix must contain at most 200 items"
		}
	}
	if draft, ok := o["assessment_state"].(platform.Object); ok {
		payload := draft["payload"].(map[string]any)
		if draft["writer_instance_id"] != writer || draft.Int("contract_version") != 3 || !jsonEqual(payload["syncStateVersion"], 1) && !jsonEqual(payload["syncStateVersion"], 2) {
			return "assessmentState requires compact state and matching writer"
		}
	}
	return ""
}}

// Reproduce model_dump_json(by_alias=True) for the validated runtime component.
// Unspecified nullable/defaulted fields are included in the byte limit, and
// transport aliases rather than Go's internal field names are serialized.
func schemaWireObject(o platform.Object, schema platform.Schema) map[string]any {
	out := map[string]any{}
	for _, f := range schema.Fields {
		key := f.Alias
		if key == "" {
			key = f.Name
		}
		value := o[f.Name]
		switch v := value.(type) {
		case *big.Int:
			value = json.Number(v.String())
		case uuid.UUID:
			value = v.String()
		case time.Time:
			value = apiTime(&v)
		case platform.Object:
			value = schemaWireObject(v, *f.Schema)
		case []any:
			list := make([]any, len(v))
			for i, item := range v {
				if nested, ok := item.(platform.Object); ok {
					list[i] = schemaWireObject(nested, *f.Item.Schema)
				} else {
					list[i] = item
				}
			}
			value = list
		}
		out[key] = value
	}
	return out
}

func syncReferenceError(missing bool) error {
	if missing {
		return &platform.APIError{Status: 409, Code: "SYNC_DEPENDENCIES_MISSING", Message: "Deliver the required event/run prefix before the assessment state"}
	}
	return &platform.APIError{Status: 400, Code: "SYNC_REFERENCE_INVALID", Message: "Invalid timeline reference"}
}
func validateSyncDependencies(ctx context.Context, db runtimeDB, id int64, payload map[string]any) error {
	events, runs := map[string]bool{}, map[string]bool{}
	if value := strings.ToLower(jsonText(payload["requiredRuntimeEventId"])); value != "" {
		events[value] = true
	}
	participants, _ := payload["participants"].([]any)
	for _, raw := range participants {
		p := jsonMap(raw)
		for _, key := range []string{"mistakeReports", "quickComments"} {
			reports, _ := p[key].([]any)
			for _, raw := range reports {
				r := jsonMap(raw)
				if !jsonEqual(r["timelineSource"], "TIMELINE") {
					continue
				}
				events[strings.ToLower(jsonText(r["assignmentEventIdAtObservation"]))] = true
				runs[strings.ToLower(jsonText(r["exerciseSessionKey"]))] = true
			}
		}
	}
	for _, set := range []map[string]bool{events, runs} {
		for value := range set {
			if _, err := uuid.Parse(value); err != nil {
				return syncReferenceError(false)
			}
		}
	}
	for i, wanted := range []map[string]bool{events, runs} {
		if len(wanted) == 0 {
			continue
		}
		ids := []uuid.UUID{}
		for value := range wanted {
			id, _ := uuid.Parse(value)
			ids = append(ids, id)
		}
		query := `SELECT public_id FROM training_session_crew_assignment_event WHERE training_session_id=$1 AND public_id=ANY($2)`
		if i == 1 {
			query = `SELECT exercise_session_key FROM training_session_exercise_run WHERE training_session_id=$1 AND exercise_session_key=ANY($2)`
		}
		rows, err := db.Query(ctx, query, id, ids)
		if err != nil {
			return err
		}
		found := map[string]bool{}
		for rows.Next() {
			var id uuid.UUID
			if err = rows.Scan(&id); err != nil {
				rows.Close()
				return err
			}
			found[id.String()] = true
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return err
		}
		for key := range wanted {
			if !found[key] {
				return syncReferenceError(true)
			}
		}
	}
	return nil
}

func (s *Service) syncTraining(w http.ResponseWriter, r *http.Request) (resultErr error) {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024*1024+1))
	if err != nil {
		return err
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	o, err := platform.ReadSchema(r, trainingSyncSchema)
	if err != nil {
		return err
	}
	if len(raw) > draftMaxBytes(s)+1024*1024 {
		return runtimeError("RUNTIME_BATCH_TOO_LARGE")
	}
	runtime, _ := o["runtime"].(platform.Object)
	draft, _ := o["assessment_state"].(platform.Object)
	if runtime != nil {
		encoded, err := canonical.JSON(schemaWireObject(runtime, runtimeSyncSchema))
		if err != nil {
			return err
		}
		if len(encoded) > 1024*1024 {
			return runtimeError("RUNTIME_BATCH_TOO_LARGE")
		}
	}
	if runtime != nil {
		s.Auth.Config.Metrics.Observe("north55_training_runtime_sync_batch_size", float64(len(runtime["crew_assignment_events"].([]any))), "events")
		s.Auth.Config.Metrics.Observe("north55_training_runtime_sync_batch_size", float64(len(runtime["run_snapshots"].([]any))), "runs")
	}
	started := time.Now()
	defer func() { s.observeRuntime(started, resultErr, "accepted", "unified_sync") }()
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = getRuntimeTraining(ctx, tx, id, user); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `SELECT id FROM training_session WHERE id=$1 FOR UPDATE`, id); err != nil {
		return err
	}
	state, err := loadRuntimeState(ctx, tx, id, true)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if err == nil && (state.Writer != o["writer_instance_id"].(uuid.UUID) || o.CompareInteger("writer_epoch", state.Epoch) != 0) {
		if state.Entitled && state.Version != 1 {
			return runtimeError("RUNTIME_CAPABILITY_VERSION_UNSUPPORTED")
		}
		return state.conflict(true)
	}
	var runtimeAck, assessmentAck any
	if runtime != nil {
		runtimeAck, err = s.syncRuntimeInTransaction(ctx, tx, id, runtime, user)
		if err != nil {
			return err
		}
	}
	if draft != nil {
		saved, err := s.saveDraftInTransaction(ctx, tx, id, draft, user, true)
		if err != nil {
			return err
		}
		if err = validateSyncDependencies(ctx, tx, id, draft["payload"].(map[string]any)); err != nil {
			return err
		}
		assessmentAck = map[string]any{"clientRevision": saved.number("client_revision"), "payloadSha256": saved["payload_sha256"]}
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Training sync committed", "action", "assessment.sync.committed", "training_id", id, "has_runtime", runtimeAck != nil, "has_assessment_state", assessmentAck != nil)
	platform.WriteJSON(w, 200, map[string]any{"protocolVersion": 1, "trainingId": id, "writerInstanceId": o["writer_instance_id"], "writerEpoch": o["writer_epoch"], "runtime": runtimeAck, "assessmentState": assessmentAck})
	return nil
}
