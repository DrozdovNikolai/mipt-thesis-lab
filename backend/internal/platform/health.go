package platform

import (
	"context"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type ComponentHealth struct {
	Status    string   `json:"status"`
	LatencyMS *float64 `json:"latencyMs"`
	Error     *string  `json:"error"`
}
type Health struct {
	DB      *pgxpool.Pool
	Redis   *redis.Client
	Config  Config
	Started time.Time
}

func (h *Health) components(ctx context.Context) map[string]ComponentHealth {
	out := map[string]ComponentHealth{}
	for name, check := range map[string]func(context.Context) error{"database": h.DB.Ping, "redis": func(c context.Context) error { return h.Redis.Ping(c).Err() }} {
		start := time.Now()
		checkContext, cancel := context.WithTimeout(ctx, 5*time.Second)
		err := check(checkContext)
		cancel()
		if err != nil {
			msg := err.Error()
			out[name] = ComponentHealth{Status: "unhealthy", Error: &msg}
		} else {
			latency := math.Round(float64(time.Since(start).Microseconds())/10) / 100
			out[name] = ComponentHealth{Status: "healthy", LatencyMS: &latency}
		}
	}
	return out
}
func (h *Health) Register(mux *Router) {
	p := h.Config.APIPrefix
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		WriteJSON(w, 200, map[string]string{"status": "ok", "app": h.Config.AppName, "environment": h.Config.Environment})
	})
	mux.HandleFunc("GET "+p+"/health", func(w http.ResponseWriter, r *http.Request) {
		WriteJSON(w, 200, map[string]string{"status": "ok", "environment": h.Config.Environment})
	})
	for _, path := range []string{"/health/ready", "/health/detailed"} {
		mux.HandleFunc("GET "+p+path, func(w http.ResponseWriter, r *http.Request) {
			components := h.components(r.Context())
			status := "ready"
			for _, c := range components {
				if c.Status != "healthy" {
					status = "degraded"
				}
			}
			payload := map[string]any{"status": status, "components": components}
			if r.URL.Path == p+"/health/detailed" {
				if status == "ready" {
					payload["status"] = "healthy"
				}
				payload["environment"] = h.Config.Environment
				payload["version"] = "0.1.0"
				payload["uptimeSeconds"] = math.Round(time.Since(h.Started).Seconds()*100) / 100
			}
			WriteJSON(w, 200, payload)
		})
	}
	mux.HandleFunc("GET "+p+"/health/backups", func(w http.ResponseWriter, r *http.Request) { WriteJSON(w, 200, h.backups()) })
}
func (h *Health) backups() map[string]any {
	out := map[string]any{"status": "unknown", "lastBackup": nil, "lastBackupAgeHours": nil, "backupSizeMb": nil, "backupCount": 0, "warning": nil}
	if _, err := os.Stat(h.Config.BackupDir); os.IsNotExist(err) {
		out["warning"] = "Backup directory not found"
		return out
	}
	paths, err := filepath.Glob(filepath.Join(h.Config.BackupDir, "backup_*.sql.gz"))
	if err != nil {
		out["status"] = "error"
		out["warning"] = err.Error()
		return out
	}
	if len(paths) == 0 {
		out["status"] = "critical"
		out["warning"] = "No backups found!"
		return out
	}
	files := []os.FileInfo{}
	for _, p := range paths {
		f, err := os.Stat(p)
		if err != nil {
			out["status"] = "error"
			out["warning"] = err.Error()
			return out
		}
		files = append(files, f)
	}
	sort.Slice(files, func(i, j int) bool { return files[i].ModTime().After(files[j].ModTime()) })
	latest := files[0]
	age := time.Since(latest.ModTime()).Hours()
	out["status"] = "healthy"
	out["lastBackup"] = latest.ModTime().UTC().Format("2006-01-02T15:04:05.999999+00:00")
	out["lastBackupAgeHours"] = math.Round(age*100) / 100
	out["backupSizeMb"] = math.Round(float64(latest.Size())/(1024*1024)*1000) / 1000
	out["backupCount"] = len(files)
	if age > 48 {
		out["status"] = "critical"
		out["warning"] = fmt.Sprintf("Last backup is %.1f hours old!", age)
	} else if age > 24 {
		out["status"] = "warning"
		out["warning"] = fmt.Sprintf("Last backup is %.1f hours old", age)
	}
	return out
}
