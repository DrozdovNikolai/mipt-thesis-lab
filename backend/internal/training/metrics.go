package training

import (
	_ "embed"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5/pgconn"
	"north55/backend/internal/platform"
)

// Router-local observation starts after auth/schema validation and the source
// byte-limit checks. The caller chooses the exact success status/reason.
func (s *Service) observeRuntime(start time.Time, err error, successStatus, successReason string) {
	status, reason := successStatus, successReason
	if err != nil {
		var domain *platform.APIError
		if errors.As(err, &domain) {
			status, reason = "rejected", domain.Code
			if domain.Status == 409 {
				s.Auth.Config.Metrics.Inc("north55_training_runtime_conflicts_total", domain.Code)
			}
		} else {
			status, reason = "failed", "INTERNAL_ERROR"
		}
	}
	s.Auth.Config.Metrics.Inc("north55_training_runtime_sync_requests_total", status, reason)
	s.Auth.Config.Metrics.Observe("north55_training_runtime_sync_latency_seconds", time.Since(start).Seconds(), status)
}

//go:embed projection_error_codes.json
var projectionCodesJSON []byte

var projectionCodes = func() map[string]string {
	var codes map[string]string
	if err := json.Unmarshal(projectionCodesJSON, &codes); err != nil {
		panic(err)
	}
	return codes
}()

// Projection failure labels use domain codes and stable database error categories.
func projectionFailureReason(err error) string {
	var domain *platform.APIError
	if errors.As(err, &domain) {
		return domain.Code
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		if code := projectionCodes[pg.Code]; code != "" {
			return code
		}
		return "dbapi"
	}
	return "RuntimeError"
}
