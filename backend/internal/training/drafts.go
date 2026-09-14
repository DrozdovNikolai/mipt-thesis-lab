package training

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func (s *Service) registerDrafts(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training"
	mux.HandleFunc("POST "+p+"/trainings/{training_id}/draft", platform.Wrap(s.saveDraft))
	mux.HandleFunc("GET "+p+"/trainings/{training_id}/draft", platform.Wrap(s.readDraft))
	mux.HandleFunc("PATCH "+p+"/trainings/{training_id}/draft/reports/{report_id}", platform.Wrap(s.patchDraft))
	mux.HandleFunc("GET "+p+"/drafts/active", platform.Wrap(s.activeDrafts))
}

func loadDraft(ctx context.Context, db runtimeDB, id, userID int64, lock bool) (record, error) {
	query := `SELECT to_jsonb(d) FROM training_session_draft d WHERE training_session_id=$1 AND user_id=$2`
	if lock {
		query += " FOR UPDATE"
	}
	return queryRecord(ctx, db, query, id, userID)
}
func draftResponse(d record) (map[string]any, error) {
	updated, err := time.Parse(time.RFC3339Nano, d.text("updated_at"))
	if err != nil {
		return nil, err
	}
	var submittedAt any
	if d["submitted_at"] != nil {
		t, err := time.Parse(time.RFC3339Nano, d.text("submitted_at"))
		if err != nil {
			return nil, err
		}
		submittedAt = apiTime(&t)
	}
	payload := jsonMap(d["payload"])
	if payload == nil {
		payload = map[string]any{}
	}
	return map[string]any{"trainingId": d.number("training_session_id"), "contractVersion": d.number("contract_version"), "writerInstanceId": d["writer_instance_id"], "clientRevision": d.number("client_revision"), "payloadSha256": d["payload_sha256"], "payload": payload, "submitted": d["submitted"], "submittedAt": submittedAt, "updatedAt": apiTime(&updated), "recoveryContext": nil}, nil
}
func draftMaxBytes(s *Service) int {
	if s.Auth.Config.DraftMaxPayloadBytes > 0 {
		return s.Auth.Config.DraftMaxPayloadBytes
	}
	return 2 * 1024 * 1024
}

// The caller owns the transaction. The training lock also serializes the first
// draft insert and is shared with runtime, takeover and unified sync.
func (s *Service) saveDraftInTransaction(ctx context.Context, db runtimeDB, id int64, o platform.Object, user *auth.User, allowCompact bool) (record, error) {
	if _, err := getRuntimeTraining(ctx, db, id, user); err != nil {
		return nil, err
	}
	training, err := queryRecord(ctx, db, `SELECT to_jsonb(t) FROM training_session t WHERE id=$1 FOR UPDATE`, id)
	if err != nil {
		return nil, err
	}
	payload := o["payload"].(map[string]any)
	version := compactVersion(payload)
	_, hasVersion := payload["syncStateVersion"]
	if hasVersion && (version == 0 || !allowCompact) {
		return nil, draftError("DRAFT_CONTRACT_REQUIRED", nil)
	}
	bytes, err := canonical.JSON(payload)
	if err != nil {
		return nil, invalidDraft("payload", "must use canonical JSON-compatible values")
	}
	hash, err := canonical.SHA256(payload)
	if err != nil {
		return nil, err
	}
	if len(bytes) > draftMaxBytes(s) {
		return nil, draftError("DRAFT_PAYLOAD_TOO_LARGE", map[string]any{"sizeBytes": len(bytes), "maxBytes": draftMaxBytes(s)})
	}
	revisioned := o.Int("contract_version") == 3
	if training.number("comment_contract_version") == 1 && !revisioned {
		return nil, draftError("DRAFT_CONTRACT_REQUIRED", nil)
	}
	if revisioned {
		if o.String("payload_sha256") != hash {
			return nil, draftError("DRAFT_PAYLOAD_HASH_INVALID", nil)
		}
		validated := payload
		if version > 0 {
			projected, err := compactDraft(payload, version)
			if err != nil {
				return nil, err
			}
			if !jsonEqual(projected, payload) {
				return nil, invalidDraft("payload", "unsupported compact state fields")
			}
			if training.number("comment_contract_version") == 1 && !jsonEqual(payload["evaluationCatalogSha256"], training["evaluation_catalog_sha256"]) {
				return nil, invalidDraft("evaluationCatalogSha256", "must match training catalog")
			}
			validated = expandDraft(payload, training)
		}
		if err := validateRevisionedDraft(ctx, db, training, validated, o.Int("client_revision"), o.Bool("submitted"), user); err != nil {
			return nil, err
		}
	}
	draft, err := loadDraft(ctx, db, id, user.InternalID, true)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	var writer, storedHash any
	revision, contract := int64(0), int64(0)
	if revisioned {
		writer = o["writer_instance_id"]
		storedHash = hash
		revision = o.Int("client_revision")
		contract = 3
		if draft != nil {
			storedVersion := compactVersion(jsonMap(draft["payload"]))
			if storedVersion > 0 && (version == 0 || version < storedVersion) {
				return nil, draftError("DRAFT_CONTRACT_REQUIRED", nil)
			}
			conflict := func() error {
				return draftError("DRAFT_REVISION_HASH_CONFLICT", map[string]any{"clientRevision": revision})
			}
			if draft.number("contract_version") != 0 && draft.number("contract_version") != 3 {
				return nil, conflict()
			}
			if draft.number("contract_version") != 0 || draft.number("client_revision") != 0 {
				if draft.text("writer_instance_id") != pythonString(writer) {
					return nil, draftError("DRAFT_WRITER_CONFLICT", map[string]any{"storedWriterInstanceId": pythonString(draft["writer_instance_id"])})
				}
				if revision < draft.number("client_revision") {
					return nil, draftError("STALE_DRAFT_REVISION", map[string]any{"receivedRevision": revision, "storedRevision": draft.number("client_revision")})
				}
				if revision == draft.number("client_revision") {
					if draft.text("payload_sha256") == hash {
						return draft, nil
					}
					if version == 0 || storedVersion >= version {
						return nil, conflict()
					}
					projected, err := compactDraft(jsonMap(draft["payload"]), version)
					if err != nil {
						return nil, err
					}
					if !jsonEqual(projected, payload) {
						return nil, conflict()
					}
					return queryRecord(ctx, db, `UPDATE training_session_draft d SET payload=$2,payload_sha256=$3,updated_at=now() WHERE id=$1 RETURNING to_jsonb(d)`, draft.number("id"), payload, hash)
				}
			}
		}
	} else {
		if training.number("comment_contract_version") != 0 || draft != nil && draft.number("contract_version") == 3 {
			return nil, draftError("DRAFT_CONTRACT_REQUIRED", nil)
		}
	}
	var submittedAt *time.Time
	if o.Bool("submitted") {
		now := time.Now().UTC()
		submittedAt = &now
	}
	if draft == nil {
		return queryRecord(ctx, db, `INSERT INTO training_session_draft AS d(training_session_id,user_id,contract_version,writer_instance_id,client_revision,payload_sha256,payload,submitted,submitted_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING to_jsonb(d)`, id, user.InternalID, contract, writer, revision, storedHash, payload, o.Bool("submitted"), submittedAt)
	}
	if !revisioned && jsonEqual(draft["payload"], payload) && draft["submitted"] == o.Bool("submitted") && submittedAt == nil && draft["submitted_at"] == nil && draft.number("contract_version") == 0 && draft.number("client_revision") == 0 && draft["writer_instance_id"] == nil && draft["payload_sha256"] == nil {
		return draft, nil
	}
	return queryRecord(ctx, db, `UPDATE training_session_draft d SET contract_version=$2,writer_instance_id=$3,client_revision=$4,payload_sha256=$5,payload=$6,submitted=$7,submitted_at=$8,updated_at=now() WHERE id=$1 RETURNING to_jsonb(d)`, draft.number("id"), contract, writer, revision, storedHash, payload, o.Bool("submitted"), submittedAt)
}

func (s *Service) saveDraft(w http.ResponseWriter, r *http.Request) (resultErr error) {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	o, err := platform.ReadSchema(r, draftSaveSchema)
	if err != nil {
		return err
	}
	started := time.Now()
	if o.Int("contract_version") == 3 {
		defer func() {
			result := "succeeded"
			if resultErr != nil {
				result = "rejected"
			}
			s.Auth.Config.Metrics.Inc("training_draft_v3_save_total", result)
			s.Auth.Config.Metrics.Observe("training_draft_v3_save_seconds", time.Since(started).Seconds(), result)
		}()
	}
	tx, err := s.Auth.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	d, err := s.saveDraftInTransaction(r.Context(), tx, id, o, user, false)
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	response, err := draftResponse(d)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, response)
	return nil
}
func (s *Service) readDraft(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	id, err := platform.PathInt(r, "training_id")
	if err != nil {
		return err
	}
	if _, err = getRuntimeTraining(r.Context(), s.Auth.DB, id, user); err != nil {
		return err
	}
	draft, err := loadDraft(r.Context(), s.Auth.DB, id, user.InternalID, false)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Draft not found")
	}
	if err != nil {
		return err
	}
	response, err := s.draftRecoveryResponse(r.Context(), s.Auth.DB, draft)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, response)
	return nil
}
func (s *Service) activeDrafts(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:read")
	if err != nil {
		return err
	}
	q, err := platform.QueryObject(r.URL.Query(), platform.Field{Name: "limit", Kind: "integer", Min: 1, Max: 100, Default: int64(10)})
	if err != nil {
		return err
	}
	drafts, err := queryRecords(r.Context(), s.Auth.DB, `SELECT to_jsonb(d) FROM training_session_draft d JOIN training_session t ON t.id=d.training_session_id WHERE d.user_id=$1 AND NOT d.submitted AND t.status<>'DELETED' AND t.submission_status<>'COMPLETED' ORDER BY d.updated_at DESC,d.id DESC LIMIT $2`, user.InternalID, q.Int("limit"))
	if err != nil {
		return err
	}
	items := []any{}
	for _, d := range drafts {
		response, err := s.draftRecoveryResponse(r.Context(), s.Auth.DB, d)
		if err != nil {
			return err
		}
		items = append(items, response)
	}
	platform.WriteJSON(w, 200, map[string]any{"items": items})
	return nil
}
