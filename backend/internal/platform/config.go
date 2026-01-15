package platform

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"north55/backend/internal/filestorage"
	"north55/backend/internal/telemetry"
)

type Config struct {
	ErrorTracker                                *ErrorTracker
	SentryDSN                                   string
	Metrics                                     *telemetry.Metrics
	EnableMetrics                               bool
	Storage                                     filestorage.Config
	Environment, AppName, Host, Port, APIPrefix string
	LogLevel                                    string
	DatabaseURL, RedisURL                       string
	AccessSecret, RefreshSecret, JWTAlgorithm   string
	AccessTTL, RefreshTTL                       time.Duration
	ScenarioLockTTL                             time.Duration
	ScenarioRequireLegacyContentContract        *bool
	MediaPhotoMaxFileBytes                      int64
	MediaSignatureMaxFileBytes                  int64
	MediaExerciseImageMaxFiles                  int64
	MediaExerciseImageMaxFileBytes              int64
	MediaExerciseImageMaxFilesText              string
	MediaExerciseImageMaxFileBytesText          string
	MediaScenarioPDFMaxFiles                    int64
	MediaScenarioPDFMaxFileBytes                int64
	FeedbackMaxFiles                            int64
	FeedbackMaxFileBytes                        int64
	FeedbackMaxTotalBytes                       int64
	MediaScenarioPDFMaxFilesText                string
	MediaScenarioPDFMaxFileBytesText            string
	AdminLogin, AdminPassword, AdminEmail       string
	AllowedOrigins                              []string
	EnableCORS                                  bool
	EnableRateLimit                             bool
	RateLimitPerMinute, RateLimitPerSecond      int64
	BackupDir                                   string
	RuntimeWriteEnabled, LiveCrewSwapEnabled    bool
	LiveCrewSwapAirlineIDs                      string
	LiveCrewSwapVersion                         int
	QuickCommentsEnabled                        bool
	QuickCommentsAirlineIDs                     string
	DraftMaxPayloadBytes                        int
}

func LoadConfig() (Config, error) {
	c := Config{Environment: Env("ENVIRONMENT", "local"), SentryDSN: Env("SENTRY_DSN", ""), AppName: Env("APP_NAME", "ff-backend"), LogLevel: Env("LOG_LEVEL", "INFO"),
		Host: Env("HOST", "0.0.0.0"), Port: Env("PORT", "8000"), APIPrefix: strings.TrimRight(Env("API_PREFIX", "/api"), "/"),
		DatabaseURL: Env("DATABASE_URL", "postgresql://ff_user:ff_pass@db:5432/ff_db"), RedisURL: Env("REDIS_URL", "redis://redis:6379/0"),
		AccessSecret: Env("JWT_SECRET_KEY", "change-me-access"), RefreshSecret: Env("JWT_REFRESH_SECRET_KEY", "change-me-refresh"), JWTAlgorithm: Env("JWT_ALGORITHM", "HS256"),
		AdminLogin: Env("ADMIN_LOGIN", "admin"), AdminPassword: Env("ADMIN_PASSWORD", "admin123"), AdminEmail: Env("ADMIN_EMAIL", "admin@example.com"),
		AllowedOrigins: strings.Split(Env("ALLOWED_HOSTS", "*"), ","), BackupDir: Env("BACKUP_DIR", "/backups")}
	c.DatabaseURL = strings.Replace(strings.Replace(c.DatabaseURL, "postgresql+asyncpg://", "postgresql://", 1), "postgresql+psycopg://", "postgresql://", 1)
	var err error
	access, err := strconv.Atoi(Env("ACCESS_TOKEN_EXP_MINUTES", "30"))
	if err != nil || access <= 0 {
		return c, fmt.Errorf("invalid ACCESS_TOKEN_EXP_MINUTES")
	}
	refresh, err := strconv.Atoi(Env("REFRESH_TOKEN_EXP_MINUTES", "10080"))
	if err != nil || refresh <= 0 {
		return c, fmt.Errorf("invalid REFRESH_TOKEN_EXP_MINUTES")
	}
	c.AccessTTL = time.Duration(access) * time.Minute
	c.RefreshTTL = time.Duration(refresh) * time.Minute
	lockTTL, err := strconv.Atoi(Env("SCENARIO_LOCK_TTL_SECONDS", "60"))
	if err != nil {
		return c, fmt.Errorf("invalid SCENARIO_LOCK_TTL_SECONDS")
	}
	c.ScenarioLockTTL = time.Duration(lockTTL) * time.Second
	c.ScenarioRequireLegacyContentContract, err = configOptionalBool(Env("SCENARIO_REQUIRE_LEGACY_CONTENT_CONTRACT", ""))
	if err != nil {
		return c, fmt.Errorf("invalid SCENARIO_REQUIRE_LEGACY_CONTENT_CONTRACT: %w", err)
	}
	for _, limit := range []struct {
		key, fallback string
		destination   *int64
		spelling      *string
	}{
		{"MEDIA_PHOTO_MAX_FILE_BYTES", "5242880", &c.MediaPhotoMaxFileBytes, new(string)},
		{"MEDIA_SIGNATURE_MAX_FILE_BYTES", "2097152", &c.MediaSignatureMaxFileBytes, new(string)},
		{"MEDIA_EXERCISE_IMAGE_MAX_FILES", "20", &c.MediaExerciseImageMaxFiles, &c.MediaExerciseImageMaxFilesText},
		{"MEDIA_EXERCISE_IMAGE_MAX_FILE_BYTES", "10485760", &c.MediaExerciseImageMaxFileBytes, &c.MediaExerciseImageMaxFileBytesText},
		{"MEDIA_SCENARIO_PDF_MAX_FILES", "20", &c.MediaScenarioPDFMaxFiles, &c.MediaScenarioPDFMaxFilesText},
		{"MEDIA_SCENARIO_PDF_MAX_FILE_BYTES", "52428800", &c.MediaScenarioPDFMaxFileBytes, &c.MediaScenarioPDFMaxFileBytesText},
		{"FEEDBACK_MAX_FILES", "5", &c.FeedbackMaxFiles, new(string)},
		{"FEEDBACK_MAX_FILE_BYTES", "10485760", &c.FeedbackMaxFileBytes, new(string)},
		{"FEEDBACK_MAX_TOTAL_BYTES", "26214400", &c.FeedbackMaxTotalBytes, new(string)},
	} {
		key, fallback, destination := limit.key, limit.fallback, limit.destination
		value, e := ValidateObject(map[string]any{"value": Env(key, fallback)}, nil, Schema{Fields: []Field{{Name: "value", Kind: "integer", AllowBigInteger: true}}})
		if e != nil {
			return c, fmt.Errorf("invalid %s", key)
		}
		// Keep Python's arbitrary-precision integer spelling in error messages,
		// even when the effective filesystem/count limit is clamped to int64.
		*limit.spelling = fmt.Sprint(value["value"])
		// Values beyond machine size are effectively unbounded (or reject all files).
		if value.CompareInteger("value", int64(^uint64(0)>>1)) > 0 {
			*destination = int64(^uint64(0) >> 1)
		} else if value.CompareInteger("value", -int64(^uint64(0)>>1)-1) < 0 {
			*destination = -int64(^uint64(0)>>1) - 1
		} else {
			*destination = value.Int("value")
		}
	}
	metricsEnabled, metricsError := configOptionalBool(Env("ENABLE_METRICS", "true"))
	if metricsError != nil || metricsEnabled == nil {
		return c, fmt.Errorf("invalid ENABLE_METRICS")
	}
	c.EnableMetrics = *metricsEnabled
	c.EnableCORS, err = strconv.ParseBool(Env("ENABLE_CORS", "true"))
	if err != nil {
		return c, fmt.Errorf("invalid ENABLE_CORS")
	}
	rateEnabled, err := configOptionalBool(Env("ENABLE_RATE_LIMIT", "false"))
	if err != nil || rateEnabled == nil {
		return c, fmt.Errorf("invalid ENABLE_RATE_LIMIT")
	}
	c.EnableRateLimit = *rateEnabled
	for _, limit := range []struct {
		key, fallback string
		destination   *int64
	}{
		{"RATE_LIMIT_PER_MINUTE", "120", &c.RateLimitPerMinute},
		{"RATE_LIMIT_PER_SECOND", "20", &c.RateLimitPerSecond},
	} {
		value, e := ValidateObject(map[string]any{"value": Env(limit.key, limit.fallback)}, nil,
			Schema{Fields: []Field{{Name: "value", Kind: "integer"}}})
		if e != nil {
			return c, fmt.Errorf("invalid %s", limit.key)
		}
		*limit.destination = value.Int("value")
	}
	c.RuntimeWriteEnabled, err = strconv.ParseBool(Env("TRAINING_RUNTIME_WRITE_ENABLED", "true"))
	if err != nil {
		return c, fmt.Errorf("invalid TRAINING_RUNTIME_WRITE_ENABLED")
	}
	c.LiveCrewSwapEnabled, err = strconv.ParseBool(Env("TRAINING_LIVE_CREW_SWAP_ENABLED", "true"))
	if err != nil {
		return c, fmt.Errorf("invalid TRAINING_LIVE_CREW_SWAP_ENABLED")
	}
	c.LiveCrewSwapAirlineIDs = Env("TRAINING_LIVE_CREW_SWAP_AIRLINE_IDS", "")
	c.QuickCommentsAirlineIDs = Env("TRAINING_QUICK_COMMENTS_AIRLINE_IDS", "")
	c.QuickCommentsEnabled, err = strconv.ParseBool(Env("TRAINING_QUICK_COMMENTS_ENABLED", "true"))
	if err != nil {
		return c, fmt.Errorf("invalid TRAINING_QUICK_COMMENTS_ENABLED")
	}
	if Env("TRAINING_QUICK_COMMENTS_CONTRACT_VERSION", "1") != "1" {
		return c, fmt.Errorf("invalid TRAINING_QUICK_COMMENTS_CONTRACT_VERSION")
	}
	c.DraftMaxPayloadBytes, err = strconv.Atoi(Env("TRAINING_DRAFT_MAX_PAYLOAD_BYTES", "2097152"))
	if err != nil || c.DraftMaxPayloadBytes < 16*1024 || c.DraftMaxPayloadBytes > 16*1024*1024 {
		return c, fmt.Errorf("invalid TRAINING_DRAFT_MAX_PAYLOAD_BYTES")
	}
	c.LiveCrewSwapVersion, err = strconv.Atoi(Env("TRAINING_LIVE_CREW_SWAP_CAPABILITY_VERSION", "1"))
	if err != nil || c.LiveCrewSwapVersion < 1 {
		return c, fmt.Errorf("invalid TRAINING_LIVE_CREW_SWAP_CAPABILITY_VERSION")
	}
	c.Storage, err = filestorage.LoadConfig(c.Environment)
	if err != nil {
		return c, err
	}
	return c, nil
}

func configOptionalBool(value string) (*bool, error) {
	if strings.Trim(value, " \t\n\r\v\f\x1c\x1d\x1e\x1f\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000") == "" {
		return nil, nil
	}
	var result bool
	switch strings.ToLower(value) {
	case "true", "1", "yes", "y", "on", "t":
		result = true
	case "false", "0", "no", "n", "off", "f":
		result = false
	default:
		return nil, fmt.Errorf("invalid optional boolean")
	}
	return &result, nil
}

func Env(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
