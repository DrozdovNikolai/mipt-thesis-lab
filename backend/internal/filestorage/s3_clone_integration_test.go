package filestorage

import (
	"bytes"
	"context"
	"crypto/md5"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func TestS3IntegrationClone(t *testing.T)    { testS3IntegrationClone(t, false) }
func TestS3IntegrationClonePDF(t *testing.T) { testS3IntegrationClone(t, true) }

func testS3IntegrationClone(t *testing.T, pdf bool) {
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
	s := New(Config{Backend: "s3", MediaDir: t.TempDir(), Bucket: "migration-clone-fixtures", Region: "us-east-1", Endpoint: endpoint, ForcePathStyle: true, MediaPrefix: "media"})
	if pdf {
		s.Config.Bucket = "migration-clone-pdf-fixtures"
	}
	client, err := s.s3Client(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = client.HeadBucket(ctx, &s3.HeadBucketInput{Bucket: aws.String(s.Config.Bucket)}); err != nil {
		if _, err = client.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String(s.Config.Bucket)}); err != nil {
			t.Fatal(err)
		}
	}
	for _, size := range []int{32, int(multipartChunkSize), int(multipartChunkSize) + 1} {
		for _, mode := range []string{"s3", "s3-dual", "local-dual", "s3-fallback"} {
			t.Run(fmt.Sprintf("%s/%d", mode, size), func(t *testing.T) {
				s.Config.MediaDir = t.TempDir()
				s.Config.Backend = "s3"
				if mode == "local-dual" {
					s.Config.Backend = "local"
				}
				s.Config.DualWriteLocal = strings.HasSuffix(mode, "-dual")
				s.Config.ReadFallbackLocal = mode == "s3-fallback"
				data := bytes.Repeat([]byte{0x42}, size)
				copy(data, []byte("\x89PNG\r\n\x1a\n"))
				contentType, namespace, clone := "image/png", "exercise_images/1/2", s.CloneImage
				if pdf {
					copy(data, []byte("%PDF-1.7\n"))
					contentType, namespace, clone = "application/pdf", "scenario_pdfs/1", s.ClonePDF
				}
				source := fmt.Sprintf("source-%s-%d.wrong", mode, size)
				key := "media/" + source
				if mode != "s3-fallback" {
					_, err = client.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), Body: bytes.NewReader(data), ContentType: aws.String("application/octet-stream")})
					if err != nil {
						t.Fatal(err)
					}
				} else {
					if _, err = client.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key)}); err != nil {
						t.Fatal(err)
					}
				}
				if err = os.WriteFile(filepath.Join(s.Config.MediaDir, source), data, 0600); err != nil {
					t.Fatal(err)
				}
				stored, err := clone(ctx, source, namespace, int64(size))
				if err != nil {
					t.Fatal(err)
				}
				get, err := client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String("media/" + stored.StoragePath)})
				if err != nil {
					t.Fatal(err)
				}
				got, err := io.ReadAll(get.Body)
				get.Body.Close()
				if err != nil || !bytes.Equal(got, data) || aws.ToString(get.ContentType) != contentType {
					t.Fatalf("object differs: %v, type %s", err, aws.ToString(get.ContentType))
				}
				digest := md5.Sum(data)
				etag := fmt.Sprintf("%x", digest)
				if size >= int(multipartChunkSize) {
					partHashes := []byte{}
					parts := 0
					for i := 0; i < size; i += int(multipartChunkSize) {
						hash := md5.Sum(data[i:min(size, i+int(multipartChunkSize))])
						partHashes = append(partHashes, hash[:]...)
						parts++
					}
					etag = fmt.Sprintf("%x-%d", md5.Sum(partHashes), parts)
				}
				if strings.Trim(aws.ToString(get.ETag), "\"") != etag {
					t.Fatalf("ETag: got %s, expected %s", aws.ToString(get.ETag), etag)
				}
				local, err := os.ReadFile(filepath.Join(s.Config.MediaDir, stored.StoragePath))
				if s.Config.DualWriteLocal {
					if err != nil || !bytes.Equal(local, data) {
						t.Fatalf("dual local: %v", err)
					}
				} else if !os.IsNotExist(err) {
					t.Fatalf("unexpected local destination: %v", err)
				}
				if err = s.Delete(ctx, Media, stored.StoragePath); err != nil {
					t.Fatal(err)
				}
				if err = s.Delete(ctx, Media, source); err != nil {
					t.Fatal(err)
				}
				if err = filepath.WalkDir(s.Config.MediaDir, func(path string, entry os.DirEntry, err error) error {
					if err != nil {
						return err
					}
					if !entry.IsDir() {
						return fmt.Errorf("leaked file %s", path)
					}
					return nil
				}); err != nil {
					t.Fatal(err)
				}
			})
		}
	}
	parts, err := client.ListMultipartUploads(ctx, &s3.ListMultipartUploadsInput{Bucket: aws.String(s.Config.Bucket)})
	if err != nil || len(parts.Uploads) != 0 {
		t.Fatalf("unfinished uploads: %v %v", parts, err)
	}
}
