package filestorage

import (
	"os"
	"testing"
)

func clearStorageEnvironment(t *testing.T) {
	t.Helper()
	for _, key := range []string{"FILE_STORAGE_BACKEND", "MEDIA_UPLOAD_DIR", "FEEDBACK_UPLOAD_DIR", "FILE_STORAGE_S3_READ_FALLBACK_LOCAL", "FILE_STORAGE_S3_DUAL_WRITE_LOCAL", "S3_BUCKET", "S3_BUCKET_NAME", "S3_REGION", "S3_ENDPOINT_URL", "S3_FORCE_PATH_STYLE", "S3_MEDIA_PREFIX", "S3_FEEDBACK_PREFIX"} {
		t.Setenv(key, "")
		if err := os.Unsetenv(key); err != nil {
			t.Fatal(err)
		}
	}
}

func TestStorageConfiguration(t *testing.T) {
	clearStorageEnvironment(t)
	c, err := LoadConfig("prod")
	if err != nil {
		t.Fatal(err)
	}
	if c.Backend != "local" || c.MediaDir != "uploads/media" || c.FeedbackDir != "uploads/feedback" || c.MediaPrefix != "media" || c.FeedbackPrefix != "feedback" {
		t.Fatalf("defaults: %+v", c)
	}
	t.Setenv("FILE_STORAGE_BACKEND", "s3")
	if _, err = LoadConfig("prod"); err == nil {
		t.Fatal("production S3 requires destination")
	}
	if _, err = LoadConfig("test"); err != nil {
		t.Fatalf("test configuration must allow unset destination: %v", err)
	}
	t.Setenv("S3_BUCKET_NAME", " alias-bucket ")
	t.Setenv("S3_ENDPOINT_URL", " http://storage-s3:9000 ")
	t.Setenv("S3_FORCE_PATH_STYLE", "YeS")
	t.Setenv("S3_MEDIA_PREFIX", " /library/media// ")
	t.Setenv("S3_FEEDBACK_PREFIX", "///")
	t.Setenv("FILE_STORAGE_S3_DUAL_WRITE_LOCAL", "on")
	t.Setenv("MEDIA_UPLOAD_DIR", " \x1c/tmp/media\u00a0")
	t.Setenv("FEEDBACK_UPLOAD_DIR", " /tmp/feedback ")
	c, err = LoadConfig("prod")
	if err != nil {
		t.Fatal(err)
	}
	if c.Bucket != "alias-bucket" || c.Endpoint != "http://storage-s3:9000" || !c.ForcePathStyle || !c.DualWriteLocal || c.MediaPrefix != "library/media" || c.FeedbackPrefix != "" || c.MediaDir != "/tmp/media" || c.FeedbackDir != " /tmp/feedback " {
		t.Fatalf("normalization: %+v", c)
	}
	t.Setenv("S3_BUCKET", "")
	if _, err = LoadConfig("prod"); err == nil {
		t.Fatal("explicit primary alias must take precedence even when empty")
	}
	t.Setenv("S3_BUCKET", "primary-bucket")
	c, err = LoadConfig("prod")
	if err != nil || c.Bucket != "primary-bucket" {
		t.Fatalf("primary bucket alias: %+v %v", c, err)
	}
}

func TestStorageConfigurationRejectsInvalidValues(t *testing.T) {
	for _, tc := range []struct{ key, value string }{
		{"FILE_STORAGE_BACKEND", "S3"}, {"FILE_STORAGE_BACKEND", ""}, {"MEDIA_UPLOAD_DIR", " \t"}, {"S3_FORCE_PATH_STYLE", " true "}, {"FILE_STORAGE_S3_DUAL_WRITE_LOCAL", "2"}, {"FILE_STORAGE_S3_READ_FALLBACK_LOCAL", "sometimes"},
	} {
		t.Run(tc.key+"/"+tc.value, func(t *testing.T) {
			clearStorageEnvironment(t)
			t.Setenv(tc.key, tc.value)
			if _, err := LoadConfig("test"); err == nil {
				t.Fatal("invalid configuration accepted")
			}
		})
	}
}
