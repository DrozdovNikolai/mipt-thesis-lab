package filestorage

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func TestS3IntegrationUserUpload(t *testing.T) {
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
	content := append([]byte{0x89, 'P', 'N', 'G', 13, 10, 26, 10}, []byte("isolated user upload")...)
	for _, dual := range []bool{false, true} {
		name := "s3-only"
		if dual {
			name = "s3-dual"
		}
		t.Run(name, func(t *testing.T) {
			base := t.TempDir()
			store := New(Config{Backend: "s3", DualWriteLocal: dual, ReadFallbackLocal: dual, MediaDir: base, Bucket: "migration-user-upload-fixtures", Region: "us-east-1", Endpoint: endpoint, ForcePathStyle: true, MediaPrefix: "media"})
			client, err := store.s3Client(ctx)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = client.HeadBucket(ctx, &s3.HeadBucketInput{Bucket: aws.String(store.Config.Bucket)}); err != nil {
				if _, err = client.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String(store.Config.Bucket)}); err != nil {
					t.Fatal(err)
				}
			}
			stored, err := store.SaveImageUpload(ctx, bytes.NewReader(content), "photo.png", "image/png", "user_photos/fixture", 100)
			if err != nil {
				t.Fatal(err)
			}
			key := "media/" + stored.StoragePath
			response, err := client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(store.Config.Bucket), Key: aws.String(key)})
			if err != nil {
				t.Fatal(err)
			}
			actual, err := io.ReadAll(response.Body)
			response.Body.Close()
			if err != nil || !bytes.Equal(actual, content) || response.ContentLength == nil || *response.ContentLength != int64(len(content)) || response.ContentType == nil || *response.ContentType != "image/png" {
				t.Fatalf("wrong stored object: read=%v, length=%v, content-type=%v", err, response.ContentLength, response.ContentType)
			}
			local, localErr := os.ReadFile(filepath.Join(base, stored.StoragePath))
			if dual {
				if localErr != nil || !bytes.Equal(local, content) {
					t.Fatalf("dual local copy missing: %v", localErr)
				}
			} else if !os.IsNotExist(localErr) {
				t.Fatalf("S3-only upload retained local copy: %v", localErr)
			}
			reader, err := store.Open(ctx, Media, stored.StoragePath)
			if err != nil {
				t.Fatal(err)
			}
			sized, ok := reader.(interface{ ContentLength() *int64 })
			if !ok || sized.ContentLength() == nil || *sized.ContentLength() != int64(len(content)) {
				t.Fatalf("S3 reader lost content length: %T", reader)
			}
			reader.Close()
			if err := store.Delete(ctx, Media, stored.StoragePath); err != nil {
				t.Fatal(err)
			}
		})
	}
}
