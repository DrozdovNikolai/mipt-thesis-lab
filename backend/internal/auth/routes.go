package auth

import (
	"errors"
	"net"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"north55/backend/internal/platform"
)

func sortStrings(values []string) { sort.Strings(values) }
func clientIP(r *http.Request) *string {
	v := r.Header.Get("X-Forwarded-For")
	if v != "" {
		v = strings.TrimSpace(strings.Split(v, ",")[0])
	} else if v = r.Header.Get("X-Real-IP"); v != "" {
		v = strings.TrimSpace(v)
	} else {
		v, _, _ = net.SplitHostPort(r.RemoteAddr)
	}
	if v == "" {
		return nil
	}
	return &v
}
func headerPtr(r *http.Request, key string) *string {
	if _, ok := r.Header[http.CanonicalHeaderKey(key)]; !ok {
		return nil
	}
	v := r.Header.Get(key)
	return &v
}

var loginFields = []platform.Field{{Name: "login", Kind: "string", Required: true, Min: 3, Max: 50}, {Name: "password", Kind: "string", Required: true, Min: 8, Max: 128}, {Name: "device_id", Alias: "deviceId", Kind: "string", Nullable: true, Max: 255}, {Name: "device_name", Alias: "deviceName", Kind: "string", Nullable: true, Max: 255}, {Name: "platform", Kind: "string", Nullable: true, Max: 64}, {Name: "app_version", Alias: "appVersion", Kind: "string", Nullable: true, Max: 64}}
var refreshField = platform.Field{Name: "refresh_token", Alias: "refreshToken", Kind: "string", Required: true}

func (s *Service) Register(mux *platform.Router) {
	s.registerUserMedia(mux)
	s.registerUserAdmin(mux)
	s.registerRecurrentCompliance(mux)
	s.registerRBAC(mux)
	prefix := s.Config.APIPrefix
	mux.HandleFunc("POST "+prefix+"/auth/login", platform.Wrap(s.login))
	mux.HandleFunc("POST "+prefix+"/auth/refresh", platform.Wrap(s.refresh))
	mux.HandleFunc("GET "+prefix+"/auth/me", platform.Wrap(s.me))
	mux.HandleFunc("GET "+prefix+"/users/me", platform.Wrap(s.me))
	mux.HandleFunc("POST "+prefix+"/auth/logout", platform.Wrap(s.logout))
	mux.HandleFunc("POST "+prefix+"/auth/logout-refresh", platform.Wrap(s.logoutRefresh))
	mux.HandleFunc("POST "+prefix+"/auth/logout-all", platform.Wrap(s.logoutAll))
	mux.HandleFunc("GET "+prefix+"/auth/sessions", platform.Wrap(s.sessions))
	mux.HandleFunc("POST "+prefix+"/auth/sessions/{session_id}/revoke", platform.Wrap(s.revoke))
	mux.HandleFunc("POST "+prefix+"/auth/change-password", platform.Wrap(s.changePassword))
}
func (s *Service) login(w http.ResponseWriter, r *http.Request) error {
	body, err := platform.ReadObject(r, loginFields...)
	if err != nil {
		return err
	}
	var id int64
	var publicID uuid.UUID
	var hash string
	var active bool
	err = s.DB.QueryRow(r.Context(), `SELECT id,public_id,hashed_password,is_active FROM users WHERE login=$1`, body.String("login")).Scan(&id, &publicID, &hash, &active)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(401, "Invalid credentials")
	}
	if err != nil {
		return err
	}
	if !VerifyPassword(body.String("password"), hash) {
		return platform.Error(401, "Invalid credentials")
	}
	if !active {
		return platform.Error(403, "Inactive user")
	}
	sid, jti := uuid.New(), uuid.New()
	now := time.Now().UTC()
	_, err = s.DB.Exec(r.Context(), `INSERT INTO auth_sessions(id,user_id,refresh_jti,refresh_expires_at,last_used_at,ip_address,user_agent,device_id,device_name,platform,app_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, sid, id, jti, now.Add(s.Config.RefreshTTL), now, clientIP(r), headerPtr(r, "User-Agent"), body.StringPtr("device_id"), body.StringPtr("device_name"), body.StringPtr("platform"), body.StringPtr("app_version"))
	if err != nil {
		return err
	}
	pair, err := Pair(s.Config, publicID, sid, jti)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Login", "action", "auth.login", "user_id", publicID, "session_id", sid)
	platform.WriteJSON(w, 200, pair)
	return nil
}
func (s *Service) refresh(w http.ResponseWriter, r *http.Request) error {
	body, err := platform.ReadObject(r, refreshField)
	if err != nil {
		return err
	}
	data, err := DecodeToken(s.Config, body.String("refresh_token"), "refresh")
	if err != nil {
		return platform.Error(401, "Invalid refresh token")
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	var stored uuid.UUID
	var revoked *time.Time
	err = tx.QueryRow(r.Context(), `SELECT a.refresh_jti,a.revoked_at FROM auth_sessions a JOIN users u ON u.id=a.user_id WHERE a.id=$1 AND u.public_id=$2 FOR UPDATE OF a`, data.SessionID, data.Subject).Scan(&stored, &revoked)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Error(401, "Invalid refresh token")
	}
	if err != nil {
		return err
	}
	if revoked != nil {
		return platform.Error(401, "Invalid refresh token")
	}
	if stored != data.TokenID {
		_, err = tx.Exec(r.Context(), `UPDATE auth_sessions SET revoked_at=now(),revoked_reason='refresh_reuse' WHERE id=$1`, data.SessionID)
		if err != nil {
			return err
		}
		if err = tx.Commit(r.Context()); err != nil {
			return err
		}
		return platform.Error(401, "Invalid refresh token")
	}
	next := uuid.New()
	now := time.Now().UTC()
	_, err = tx.Exec(r.Context(), `UPDATE auth_sessions SET refresh_jti=$1,refresh_expires_at=$2,last_used_at=$3,ip_address=$4,user_agent=$5 WHERE id=$6`, next, now.Add(s.Config.RefreshTTL), now, clientIP(r), headerPtr(r, "User-Agent"), data.SessionID)
	if err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	pair, err := Pair(s.Config, data.Subject, data.SessionID, next)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Refresh", "action", "auth.refresh", "user_id", data.Subject, "session_id", data.SessionID)
	platform.WriteJSON(w, 200, pair)
	return nil
}
func (s *Service) me(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 200, user)
	return nil
}
func (s *Service) logout(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(r.Context(), `UPDATE auth_sessions SET revoked_at=now(),revoked_reason='logout' WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL`, u.SessionID, u.InternalID)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Logout", "action", "auth.logout", "user_id", u.ID)
	platform.WriteJSON(w, 200, map[string]bool{"success": true})
	return nil
}
func (s *Service) logoutRefresh(w http.ResponseWriter, r *http.Request) error {
	body, err := platform.ReadObject(r, refreshField)
	if err != nil {
		return err
	}
	data, tokenErr := DecodeToken(s.Config, body.String("refresh_token"), "refresh")
	if tokenErr == nil {
		_, err = s.DB.Exec(r.Context(), `UPDATE auth_sessions a SET revoked_at=now(),revoked_reason='logout' FROM users u WHERE a.user_id=u.id AND u.public_id=$1 AND a.id=$2 AND a.revoked_at IS NULL`, data.Subject, data.SessionID)
		if err != nil {
			return err
		}
		platform.LogModule("app.audit", r.Context()).Info("Logout (refresh)", "action", "auth.logout_refresh", "user_id", data.Subject, "session_id", data.SessionID)
	}
	platform.WriteJSON(w, 200, map[string]bool{"success": true})
	return nil
}
func (s *Service) logoutAll(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(r.Context(), `UPDATE auth_sessions SET revoked_at=now(),revoked_reason='logout_all' WHERE user_id=$1 AND revoked_at IS NULL`, u.InternalID)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Logout all", "action", "auth.logout_all", "user_id", u.ID)
	platform.WriteJSON(w, 200, map[string]bool{"success": true})
	return nil
}

type Session struct {
	ID               uuid.UUID  `json:"id"`
	CreatedAt        time.Time  `json:"createdAt"`
	LastUsedAt       *time.Time `json:"lastUsedAt"`
	RefreshExpiresAt time.Time  `json:"refreshExpiresAt"`
	RevokedAt        *time.Time `json:"revokedAt"`
	RevokedReason    *string    `json:"revokedReason"`
	IPAddress        *string    `json:"ipAddress"`
	UserAgent        *string    `json:"userAgent"`
	DeviceID         *string    `json:"deviceId"`
	DeviceName       *string    `json:"deviceName"`
	Platform         *string    `json:"platform"`
	AppVersion       *string    `json:"appVersion"`
}

func (s *Service) sessions(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	rows, err := s.DB.Query(r.Context(), `SELECT id,created_at,last_used_at,refresh_expires_at,revoked_at,revoked_reason,ip_address,user_agent,device_id,device_name,platform,app_version FROM auth_sessions WHERE user_id=$1 ORDER BY created_at DESC`, u.InternalID)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []Session{}
	for rows.Next() {
		var item Session
		if err = rows.Scan(&item.ID, &item.CreatedAt, &item.LastUsedAt, &item.RefreshExpiresAt, &item.RevokedAt, &item.RevokedReason, &item.IPAddress, &item.UserAgent, &item.DeviceID, &item.DeviceName, &item.Platform, &item.AppVersion); err != nil {
			return err
		}
		out = append(out, item)
	}
	if err = rows.Err(); err != nil {
		return err
	}
	platform.WriteJSON(w, 200, out)
	return nil
}
func (s *Service) revoke(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	sid, err := uuid.Parse(r.PathValue("session_id"))
	if err != nil {
		return &platform.APIError{Status: 422, Code: "VALIDATION_ERROR", Message: "Validation failed", Extra: map[string]any{"details": []any{platform.Detail("uuid_parsing", "Input should be a valid UUID", []any{"path", "session_id"}, r.PathValue("session_id"), nil)}}}
	}
	_, err = s.DB.Exec(r.Context(), `UPDATE auth_sessions SET revoked_at=now(),revoked_reason='revoke' WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL`, sid, u.InternalID)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Session revoked", "action", "auth.session_revoke", "user_id", u.ID)
	platform.WriteJSON(w, 200, map[string]bool{"success": true})
	return nil
}
func (s *Service) changePassword(w http.ResponseWriter, r *http.Request) error {
	u, err := s.Authenticate(r)
	if err != nil {
		return err
	}
	body, err := platform.ReadObject(r, platform.Field{Name: "current_password", Alias: "currentPassword", Kind: "string", Required: true, Min: 8, Max: 128}, platform.Field{Name: "new_password", Alias: "newPassword", Kind: "string", Required: true, Min: 8, Max: 128})
	if err != nil {
		return err
	}
	if !VerifyPassword(body.String("current_password"), u.HashedPassword) {
		return platform.Error(400, "Invalid current password")
	}
	hash, err := HashPassword(body.String("new_password"))
	if err != nil {
		return err
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		return err
	}
	defer tx.Rollback(r.Context())
	if _, err = tx.Exec(r.Context(), `UPDATE users SET hashed_password=$1,must_change_password=false,updated_at=now() WHERE id=$2`, hash, u.InternalID); err != nil {
		return err
	}
	if _, err = tx.Exec(r.Context(), `UPDATE auth_sessions SET revoked_at=now(),revoked_reason='password_changed' WHERE user_id=$1 AND id<>$2 AND revoked_at IS NULL`, u.InternalID, u.SessionID); err != nil {
		return err
	}
	if err = tx.Commit(r.Context()); err != nil {
		return err
	}
	updated, err := s.LoadUser(r.Context(), u.ID)
	if err != nil {
		return err
	}
	platform.LogModule("app.audit", r.Context()).Info("Password changed", "action", "auth.change_password", "user_id", u.ID)
	platform.WriteJSON(w, 200, updated)
	return nil
}
