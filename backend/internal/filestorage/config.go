package filestorage

import (
	"fmt"
	"north55/backend/internal/telemetry"
	"os"
	"strings"
	"unicode"
)

type Config struct {
	Metrics                           *telemetry.Metrics
	Backend, MediaDir, FeedbackDir    string
	ReadFallbackLocal, DualWriteLocal bool
	Bucket, Region, Endpoint          string
	ForcePathStyle                    bool
	MediaPrefix, FeedbackPrefix       string
}

func trim(value string) string {
	return strings.TrimFunc(value, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
}

func LoadConfig(environment string) (Config, error) {
	env := func(name, fallback string) string {
		if value, exists := os.LookupEnv(name); exists {
			return value
		}
		return fallback
	}
	c := Config{Backend: env("FILE_STORAGE_BACKEND", "local"), MediaDir: trim(env("MEDIA_UPLOAD_DIR", "uploads/media")), FeedbackDir: env("FEEDBACK_UPLOAD_DIR", "uploads/feedback"),
		Bucket: trim(env("S3_BUCKET", env("S3_BUCKET_NAME", ""))), Region: trim(env("S3_REGION", "")), Endpoint: trim(env("S3_ENDPOINT_URL", "")),
		MediaPrefix: strings.Trim(trim(env("S3_MEDIA_PREFIX", "media")), "/"), FeedbackPrefix: strings.Trim(trim(env("S3_FEEDBACK_PREFIX", "feedback")), "/")}
	if c.Backend != "local" && c.Backend != "s3" {
		return c, fmt.Errorf("invalid FILE_STORAGE_BACKEND")
	}
	if c.MediaDir == "" {
		return c, fmt.Errorf("invalid MEDIA_UPLOAD_DIR")
	}
	for name, destination := range map[string]*bool{"FILE_STORAGE_S3_READ_FALLBACK_LOCAL": &c.ReadFallbackLocal, "FILE_STORAGE_S3_DUAL_WRITE_LOCAL": &c.DualWriteLocal, "S3_FORCE_PATH_STYLE": &c.ForcePathStyle} {
		switch strings.ToLower(env(name, "false")) {
		case "true", "1", "yes", "y", "on", "t":
			*destination = true
		case "false", "0", "no", "n", "off", "f":
			*destination = false
		default:
			return c, fmt.Errorf("invalid %s", name)
		}
	}
	if environment == "prod" && c.Backend == "s3" {
		missing := []string{}
		if c.Bucket == "" {
			missing = append(missing, "S3_BUCKET")
		}
		if c.Region == "" && c.Endpoint == "" {
			missing = append(missing, "S3_REGION or S3_ENDPOINT_URL")
		}
		if len(missing) > 0 {
			return c, fmt.Errorf("S3 file storage enabled but missing: %s", strings.Join(missing, ", "))
		}
	}
	return c, nil
}
