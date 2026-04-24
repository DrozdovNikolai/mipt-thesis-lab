package support

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/auth"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

type Service struct {
	Auth  *auth.Service
	Store *filestorage.Store
}

func (s *Service) Register(mux *platform.Router) {
	if s.Store == nil {
		s.Store = filestorage.New(s.Auth.Config.Storage)
	}
	p := s.Auth.Config.APIPrefix + "/support/feedback"
	mux.HandleFunc("GET "+p+"/config", platform.Wrap(s.config))
	mux.HandleFunc("POST "+p, platform.Wrap(s.create))
	mux.HandleFunc("GET "+p+"/my", platform.Wrap(s.myList))
	mux.HandleFunc("GET "+p+"/my/{ticket_id}", platform.Wrap(s.myDetail))
	mux.HandleFunc("GET "+p, platform.Wrap(s.adminList))
	mux.HandleFunc("GET "+p+"/{ticket_id}", platform.Wrap(s.adminDetail))
	mux.HandleFunc("PATCH "+p+"/{ticket_id}", platform.Wrap(s.update))
	mux.HandleFunc("GET "+p+"/{ticket_id}/attachments/{attachment_id}", platform.Wrap(s.downloadAttachment))
}

func decode(raw []byte) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value map[string]any
	err := decoder.Decode(&value)
	return value, err
}

func readRow(row pgx.Row) (map[string]any, error) {
	var raw []byte
	if err := row.Scan(&raw); err != nil {
		return nil, err
	}
	return decode(raw)
}

func number(value any) int64 {
	if raw, ok := value.(json.Number); ok {
		n, _ := raw.Int64()
		return n
	}
	return 0
}

func wireTime(value any) any {
	if value == nil {
		return nil
	}
	if raw, ok := value.(string); ok {
		if parsed, err := time.Parse(time.RFC3339Nano, raw); err == nil {
			return parsed
		}
	}
	return value
}

func ticketPath(r *http.Request, includeAttachment bool) (int64, int64, error) {
	fields := []platform.Field{{Name: "ticket_id", Kind: "integer", Required: true, AllowBigInteger: true}}
	raw := map[string]any{"ticket_id": r.PathValue("ticket_id")}
	if includeAttachment {
		fields = append(fields, platform.Field{Name: "attachment_id", Kind: "integer", Required: true, AllowBigInteger: true})
		raw["attachment_id"] = r.PathValue("attachment_id")
	}
	path, err := platform.ValidateObject(raw, []any{"path"}, platform.Schema{Fields: fields})
	if err != nil {
		return 0, 0, err
	}
	return path.Int("ticket_id"), path.Int("attachment_id"), nil
}

func listQuery(r *http.Request) (int64, int64, error) {
	query, err := platform.QueryObject(r.URL.Query(),
		platform.Field{Name: "limit", Kind: "integer", AllowBigInteger: true},
		platform.Field{Name: "offset", Kind: "integer", AllowBigInteger: true})
	if err != nil {
		return 0, 0, err
	}
	limit, offset := int64(50), int64(0)
	if query["limit"] != nil {
		if query.CompareInteger("limit", 1) < 0 {
			limit = 1
		} else if query.CompareInteger("limit", 200) > 0 {
			limit = 200
		} else {
			limit = query.Int("limit")
		}
	}
	if query["offset"] != nil && query.CompareInteger("offset", 0) > 0 {
		offset = query.Int("offset")
	}
	return limit, offset, nil
}

func (s *Service) config(w http.ResponseWriter, r *http.Request) error {
	if _, err := s.Auth.Authenticate(r); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, map[string]any{
		"maxFiles":      s.Auth.Config.FeedbackMaxFiles,
		"maxFileBytes":  s.Auth.Config.FeedbackMaxFileBytes,
		"maxTotalBytes": s.Auth.Config.FeedbackMaxTotalBytes,
	})
	return nil
}

func (s *Service) dto(ctx context.Context, ticket map[string]any, admin bool) (map[string]any, error) {
	id := number(ticket["id"])
	rows, err := s.Auth.DB.Query(ctx, `SELECT to_jsonb(a) FROM feedback_attachment a WHERE ticket_id=$1 ORDER BY id`, id)
	if err != nil {
		return nil, err
	}
	attachments := []any{}
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			rows.Close()
			return nil, err
		}
		item, e := decode(raw)
		if e != nil {
			rows.Close()
			return nil, e
		}
		attachments = append(attachments, map[string]any{
			"id": item["id"], "originalFilename": item["original_filename"],
			"contentType": item["content_type"], "sizeBytes": item["size_bytes"],
			"sha256": item["sha256"],
		})
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	result := map[string]any{
		"id": ticket["id"], "subject": ticket["subject"], "message": ticket["message"],
		"pageUrl": ticket["page_url"], "status": ticket["status"],
		"adminReply": ticket["admin_reply"], "adminRepliedAt": wireTime(ticket["admin_replied_at"]),
		"createdAt": wireTime(ticket["created_at"]), "attachments": attachments,
	}
	if admin {
		result["userId"], result["userLogin"] = ticket["user_id"], nil
		if ticket["user_id"] != nil {
			var login *string
			err = s.Auth.DB.QueryRow(ctx, `SELECT login FROM users WHERE id=$1`, number(ticket["user_id"])).Scan(&login)
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return nil, err
			}
			result["userLogin"] = login
		}
	}
	return result, nil
}
