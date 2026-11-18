package support

import (
	"encoding/json"
	"errors"
	"fmt"
	"mime/multipart"
	"net/http"
	"path"
	"strings"
	"unicode"

	"github.com/jackc/pgx/v5"
	"north55/backend/internal/filestorage"
	"north55/backend/internal/platform"
)

func trim(value string) string {
	return strings.TrimFunc(value, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f })
}

func formatBytes(value int64) string {
	if value < 1024 {
		return fmt.Sprintf("%d B", value)
	}
	if value < 1024*1024 {
		return fmt.Sprintf("%.1f KB", float64(value)/1024)
	}
	return fmt.Sprintf("%.1f MB", float64(value)/(1024*1024))
}

func feedbackError(status int, code, message string, extra map[string]any) error {
	return &platform.APIError{Status: status, Code: code, Message: message, Extra: extra}
}

func feedbackForm(r *http.Request) (string, string, any, any, []*multipart.FileHeader, error) {
	err := r.ParseMultipartForm(1 << 20)
	form := r.MultipartForm
	if errors.Is(err, http.ErrNotMultipart) {
		if err = r.ParseForm(); err == nil {
			form = &multipart.Form{Value: r.PostForm, File: map[string][]*multipart.FileHeader{}}
		}
	}
	if err != nil {
		return "", "", nil, nil, nil, platform.Error(400, "There was an error parsing the body")
	}
	get := func(name string) (string, bool) {
		values := form.Value[name]
		if len(values) == 0 {
			return "", false
		}
		return values[len(values)-1], true
	}
	subject, subjectPresent := get("subject")
	message, messagePresent := get("message")
	details := []any{}
	for _, field := range []struct {
		name    string
		value   string
		present bool
		maximum int
	}{{"subject", subject, subjectPresent, 255}, {"message", message, messagePresent, 20000}} {
		if !field.present {
			details = append(details, platform.Detail("missing", "Field required", []any{"body", field.name}, nil, nil))
		} else if len([]rune(field.value)) > field.maximum {
			details = append(details, platform.Detail("string_too_long", fmt.Sprintf("String should have at most %d characters", field.maximum), []any{"body", field.name}, field.value, map[string]any{"max_length": field.maximum}))
		}
	}
	if len(details) != 0 {
		return "", "", nil, nil, nil, feedbackError(422, "VALIDATION_ERROR", "Validation failed", map[string]any{"details": details})
	}
	subject, message = trim(subject), trim(message)
	if subject == "" {
		return "", "", nil, nil, nil, feedbackError(422, "SUBJECT_REQUIRED", "Subject is required", nil)
	}
	if message == "" {
		return "", "", nil, nil, nil, feedbackError(422, "MESSAGE_REQUIRED", "Message is required", nil)
	}
	var pageURL any
	if raw, exists := get("pageUrl"); exists {
		if len([]rune(raw)) > 2048 {
			return "", "", nil, nil, nil, feedbackError(422, "VALIDATION_ERROR", "Validation failed", map[string]any{"details": []any{platform.Detail("string_too_long", "String should have at most 2048 characters", []any{"body", "pageUrl"}, raw, map[string]any{"max_length": 2048})}})
		}
		if value := trim(raw); value != "" {
			pageURL = value
		}
	}
	var clientInfo any
	if raw, exists := get("clientInfo"); exists && trim(raw) != "" {
		var parsed any
		if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
			runes := []rune(raw)
			if len(runes) > 5000 {
				runes = runes[:5000]
			}
			clientInfo = map[string]any{"raw": string(runes)}
		} else if value, ok := parsed.(map[string]any); ok {
			clientInfo = value
		}
	}
	return subject, message, pageURL, clientInfo, form.File["files"], nil
}

func (s *Service) create(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r)
	if err != nil {
		return err
	}
	subject, message, pageURL, clientInfo, files, err := feedbackForm(r)
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	if err != nil {
		return err
	}
	if int64(len(files)) > s.Auth.Config.FeedbackMaxFiles {
		limit := s.Auth.Config.FeedbackMaxFiles
		return feedbackError(413, "TOO_MANY_ATTACHMENTS", fmt.Sprintf("Too many attachments (max %d)", limit), map[string]any{"max_files": limit})
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var ticketID int64
	var clientJSON any
	if clientInfo != nil {
		raw, marshalErr := json.Marshal(clientInfo)
		if marshalErr != nil {
			return marshalErr
		}
		clientJSON = string(raw)
	}
	err = tx.QueryRow(ctx, `INSERT INTO feedback_ticket (user_id,subject,message,page_url,client_info,status) VALUES ($1,$2,$3,$4,$5::jsonb,'OPEN') RETURNING id`, user.InternalID, subject, message, pageURL, clientJSON).Scan(&ticketID)
	if err != nil {
		return feedbackError(500, "FEEDBACK_CREATE_FAILED", "Failed to create feedback ticket", nil)
	}
	type attachment struct {
		stored   filestorage.StoredMedia
		name     string
		mimeType any
	}
	attachments := []attachment{}
	committed := false
	defer func() {
		if !committed {
			for _, file := range attachments {
				_ = s.Store.Delete(ctx, filestorage.Feedback, file.stored.StoragePath)
			}
		}
	}()
	var total int64
	for _, header := range files {
		if header.Filename == "" {
			continue
		}
		file, openErr := header.Open()
		if openErr != nil {
			return feedbackError(500, "FEEDBACK_CREATE_FAILED", "Failed to create feedback ticket", nil)
		}
		mimeType := header.Header.Get("Content-Type")
		stored, saveErr := s.Store.SaveFeedbackUpload(ctx, file, header.Filename, mimeType, ticketID, s.Auth.Config.FeedbackMaxFileBytes)
		_ = file.Close()
		if saveErr != nil {
			var media *filestorage.MediaError
			if errors.As(saveErr, &media) && media.Status == 413 {
				return feedbackError(413, "FEEDBACK_FILE_TOO_LARGE", fmt.Sprintf("Attachment '%s' exceeds max size (max %s)", header.Filename, formatBytes(s.Auth.Config.FeedbackMaxFileBytes)), map[string]any{"max_bytes": s.Auth.Config.FeedbackMaxFileBytes})
			}
			return feedbackError(500, "FEEDBACK_CREATE_FAILED", "Failed to create feedback ticket", nil)
		}
		originalName := path.Base(header.Filename)
		var databaseType any
		if mimeType != "" {
			databaseType = mimeType
		}
		attachments = append(attachments, attachment{stored: stored, name: originalName, mimeType: databaseType})
		total += stored.SizeBytes
		if total > s.Auth.Config.FeedbackMaxTotalBytes {
			return feedbackError(413, "FEEDBACK_TOTAL_TOO_LARGE", fmt.Sprintf("Total attachments size exceeds limit (max %s)", formatBytes(s.Auth.Config.FeedbackMaxTotalBytes)), map[string]any{"max_bytes": s.Auth.Config.FeedbackMaxTotalBytes})
		}
	}
	for _, attachment := range attachments {
		stored := attachment.stored
		_, err = tx.Exec(ctx, `INSERT INTO feedback_attachment (ticket_id,original_filename,content_type,size_bytes,sha256,storage_path) VALUES ($1,$2,$3,$4,$5,$6)`, ticketID, attachment.name, attachment.mimeType, stored.SizeBytes, stored.SHA256, stored.StoragePath)
		if err != nil {
			return feedbackError(500, "FEEDBACK_CREATE_FAILED", "Failed to create feedback ticket", nil)
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return feedbackError(500, "FEEDBACK_CREATE_FAILED", "Failed to create feedback ticket", nil)
	}
	committed = true
	ticket, err := readRow(s.Auth.DB.QueryRow(ctx, `SELECT to_jsonb(t) FROM feedback_ticket t WHERE id=$1`, ticketID))
	if err != nil {
		return err
	}
	result, err := s.dto(ctx, ticket, false)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, result)
	return nil
}

func (s *Service) update(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "users:read")
	if err != nil {
		return err
	}
	schema := platform.Schema{Fields: []platform.Field{
		{Name: "status", Kind: "string", Nullable: true},
		{Name: "admin_reply", Alias: "adminReply", Kind: "string", Nullable: true, Max: 20000},
	}}
	pathValue, body, err := platform.ReadPathAndBody(r, platform.Schema{Fields: []platform.Field{
		{Name: "ticket_id", Kind: "integer", Required: true, AllowBigInteger: true},
	}}, schema)
	if err != nil {
		return err
	}
	id := pathValue.Int("ticket_id")
	ctx := r.Context()
	ticket, err := readRow(s.Auth.DB.QueryRow(ctx, `SELECT to_jsonb(t) FROM feedback_ticket t WHERE id=$1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(404, "Ticket not found")
	}
	if err != nil {
		return err
	}
	newStatus := ticket["status"]
	statusSet := false
	if raw, ok := body["status"].(string); ok {
		status := strings.ToUpper(trim(raw))
		switch status {
		case "OPEN", "IN_PROGRESS", "ANSWERED", "CLOSED":
		default:
			return feedbackError(422, "INVALID_FEEDBACK_STATUS", "Invalid status", map[string]any{"allowed": []string{"ANSWERED", "CLOSED", "IN_PROGRESS", "OPEN"}})
		}
		newStatus = status
		statusSet = status != ticket["status"]
	}
	if raw, ok := body["admin_reply"].(string); ok {
		reply := trim(raw)
		var replyValue, adminID any
		if reply != "" {
			replyValue, adminID = reply, user.InternalID
		}
		_, err = s.Auth.DB.Exec(ctx, `UPDATE feedback_ticket SET status=$2,admin_reply=$3,admin_user_id=$4,admin_replied_at=CASE WHEN $3::text IS NULL THEN NULL ELSE now() END,updated_at=now() WHERE id=$1`, id, newStatus, replyValue, adminID)
	} else if statusSet {
		_, err = s.Auth.DB.Exec(ctx, `UPDATE feedback_ticket SET status=$2,updated_at=now() WHERE id=$1`, id, newStatus)
	}
	if err != nil {
		return err
	}
	ticket, err = readRow(s.Auth.DB.QueryRow(ctx, `SELECT to_jsonb(t) FROM feedback_ticket t WHERE id=$1`, id))
	if err != nil {
		return err
	}
	result, err := s.dto(ctx, ticket, true)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, result)
	return nil
}
