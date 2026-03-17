package filestorage

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"
)

// Explicit opt-in: the migration runner supplies an isolated MinIO endpoint.
// This test never discovers a production bucket or uses ambient credentials.
func TestS3IntegrationDelete(t *testing.T) {
	endpoint := os.Getenv("NORTH55_TEST_S3_ENDPOINT")
	if endpoint == "" {
		t.Skip("isolated S3 test endpoint not provided")
	}
	t.Setenv("AWS_ACCESS_KEY_ID", "isolated-storage-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "isolated-storage-secret")
	t.Setenv("AWS_SESSION_TOKEN", "")
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")
	t.Setenv("AWS_MAX_ATTEMPTS", "1")
	ctx := context.Background()
	base := t.TempDir()
	s := New(Config{Backend: "s3", MediaDir: base, FeedbackDir: base, Bucket: "migration-delete-fixtures", Region: "us-east-1", Endpoint: endpoint, ForcePathStyle: true, MediaPrefix: "media", FeedbackPrefix: "feedback"})
	client, err := s.s3Client(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = client.HeadBucket(ctx, &s3.HeadBucketInput{Bucket: aws.String(s.Config.Bucket)}); err != nil {
		if _, err = client.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String(s.Config.Bucket)}); err != nil {
			t.Fatal(err)
		}
	}
	for _, tc := range []struct {
		name   string
		kind   Kind
		prefix string
		dual   bool
	}{
		{"media", Media, "media", false}, {"empty-prefix", Media, "", false}, {"feedback-dual", Feedback, "feedback", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s.Config.MediaPrefix = tc.prefix
			s.Config.FeedbackPrefix = tc.prefix
			s.Config.DualWriteLocal = tc.dual
			s.Config.Backend = "s3"
			if tc.dual {
				s.Config.Backend = "local"
			}
			path := "snapshot/é space%2F/image.png"
			key := path
			if tc.prefix != "" {
				key = tc.prefix + "/" + path
			}
			if _, err := client.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), Body: strings.NewReader("fixture bytes")}); err != nil {
				t.Fatal(err)
			}
			if _, err := client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key)}); err != nil {
				t.Fatal(err)
			}
			writeFixture(t, filepath.Join(base, path))
			if err := s.Delete(ctx, tc.kind, path); err != nil {
				t.Fatal(err)
			}
			_, err := client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key)})
			var apiError smithy.APIError
			if !errors.As(err, &apiError) || (apiError.ErrorCode() != "NotFound" && apiError.ErrorCode() != "NoSuchKey") {
				t.Fatalf("expected missing S3 object, got %v", err)
			}
			if _, err := os.Stat(filepath.Join(base, path)); !os.IsNotExist(err) {
				t.Fatalf("local file retained: %v", err)
			}
			if err := s.Delete(ctx, tc.kind, path); err != nil {
				t.Fatalf("repeat delete: %v", err)
			}
		})
	}
}
