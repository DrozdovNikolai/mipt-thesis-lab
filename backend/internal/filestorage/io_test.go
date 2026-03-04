package filestorage

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"north55/backend/internal/telemetry"
	"os"
	"path/filepath"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func fixtureS3Store(t *testing.T, handler http.HandlerFunc) *Store {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	s := New(Config{Backend: "s3", MediaDir: t.TempDir(), Bucket: "fixture", ReadFallbackLocal: true})
	s.client = s3.New(s3.Options{Region: "us-east-1", BaseEndpoint: aws.String(server.URL), UsePathStyle: true, RetryMaxAttempts: 1, Credentials: aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
		return aws.Credentials{AccessKeyID: "fixture", SecretAccessKey: "fixture"}, nil
	})})
	return s
}

func TestReadFallbackOnlyForMissingS3Objects(t *testing.T) {
	for _, status := range []int{404, 403, 503} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			s := fixtureS3Store(t, func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(status)
				_, _ = io.WriteString(w, "<Error><Code>FixtureError</Code></Error>")
			})
			s.Config.Metrics = telemetry.New(false)
			writeFixture(t, filepath.Join(s.Config.MediaDir, "source"))
			reader, err := s.Open(context.Background(), Media, "source")
			if status == 404 {
				if err != nil {
					t.Fatal(err)
				}
				defer reader.Close()
				data, err := io.ReadAll(reader)
				if err != nil || string(data) != "retained media" {
					t.Fatalf("fallback: %s %v", data, err)
				}
			} else if err == nil {
				reader.Close()
				t.Fatal("S3 error was masked by local fallback")
			}
			families, metricErr := s.Config.Metrics.Gather()
			if metricErr != nil {
				t.Fatal(metricErr)
			}
			for _, family := range families {
				if family.GetName() == "file_storage_s3_fallback_total" {
					if (len(family.Metric) > 0) != (status == 404) {
						t.Fatal("fallback metric for wrong S3 status", status, family)
					}
				}
			}
		})
	}
}

func TestCloneS3DownloadErrorPrecedesImageValidation(t *testing.T) {
	s := fixtureS3Store(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "1000")
		_, _ = io.WriteString(w, "invalid image exceeds configured size")
	})
	_, err := s.CloneImage(context.Background(), "source", "exercise_images/1/2", 1)
	var media *MediaError
	if err == nil || errors.As(err, &media) {
		t.Fatalf("expected download error before 413/415: %v", err)
	}
}

func TestMultipartFailureAbortsUploadAndRemovesTemporaryFile(t *testing.T) {
	aborted := false
	s := fixtureS3Store(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "POST" && r.URL.Query().Has("uploads"):
			_, _ = io.WriteString(w, `<InitiateMultipartUploadResult><Bucket>fixture</Bucket><Key>copy.png</Key><UploadId>fixture-upload</UploadId></InitiateMultipartUploadResult>`)
		case r.Method == "PUT" && r.URL.Query().Get("uploadId") == "fixture-upload":
			w.WriteHeader(403)
			_, _ = io.WriteString(w, "<Error><Code>AccessDenied</Code></Error>")
		case r.Method == "DELETE" && r.URL.Query().Get("uploadId") == "fixture-upload":
			aborted = true
			w.WriteHeader(204)
		default:
			t.Errorf("unexpected request: %s %s", r.Method, r.URL)
			w.WriteHeader(500)
		}
	})
	path := filepath.Join(s.Config.MediaDir, "temporary.uploading")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = file.Truncate(multipartChunkSize); err != nil {
		t.Fatal(err)
	}
	file.Close()
	err = s.PersistTemp(context.Background(), Media, "temporary.uploading", "copy.png", "image/png")
	if err == nil || !aborted {
		t.Fatalf("error %v, aborted %v", err, aborted)
	}
	if _, err = os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("temporary file leaked: %v", err)
	}
}

func TestFallbackMetricsCountAttemptBeforeLocalRead(t *testing.T) {
	store := fixtureS3Store(t, func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404) })
	store.Config.Metrics = telemetry.New(false)
	_, err := store.Open(context.Background(), Media, "missing")
	if !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	err = store.ServeMediaResponse(httptest.NewRecorder(), httptest.NewRequest("GET", "/media", nil), Media, "missing", "missing", "image/png")
	if !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	_, err = store.ClonePDF(context.Background(), "missing", "copies", 1024)
	var media *MediaError
	if !errors.As(err, &media) || media.Status != 404 {
		t.Fatal(err)
	}
	_, _ = store.Open(context.Background(), Media, "../invalid")
	store.Config.ReadFallbackLocal = false
	_, _ = store.Open(context.Background(), Media, "missing")
	families, err := store.Config.Metrics.Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range families {
		if f.GetName() != "file_storage_s3_fallback_total" {
			continue
		}
		if len(f.Metric) != 3 {
			t.Fatal("unexpected fallback operation", f)
		}
		for _, sample := range f.Metric {
			labels := map[string]string{}
			for _, l := range sample.Label {
				labels[l.GetName()] = l.GetValue()
			}
			if labels["kind"] != "media" || (labels["operation"] != "read" && labels["operation"] != "stream" && labels["operation"] != "local_path") || sample.Counter.GetValue() != 1 {
				t.Fatal("fallback attempt", sample)
			}
		}
		return
	}
	t.Fatal("missing fallback metrics")
}
