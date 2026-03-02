package filestorage

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func writeFixture(t *testing.T, name string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(name), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(name, []byte("retained media"), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestDeleteLocalPaths(t *testing.T) {
	for _, tc := range []struct {
		input, stored string
		removed       bool
	}{
		{"photos/a.png", "photos/a.png", true},
		{" \x1c/photos//./a.png/\u00a0", "photos/a.png", true},
		{`photos\a.png`, "photos/a.png", true},
		{"photos/../a.png", "a.png", false},
		{"../a.png", "a.png", false},
		{"photos/%2e%2e/a.png", "photos/%2e%2e/a.png", true},
		{"photos/é 雲.png", "photos/é 雲.png", true},
		{"photos/a.png\x00", "photos/a.png", false},
		{"", "photos/a.png", false},
		{"/\t/", "photos/a.png", false},
		{"missing/a.png", "photos/a.png", false},
	} {
		t.Run(tc.input, func(t *testing.T) {
			base := t.TempDir()
			name := filepath.Join(base, tc.stored)
			writeFixture(t, name)
			s := New(Config{Backend: "local", MediaDir: base})
			if err := s.Delete(context.Background(), Media, tc.input); err != nil {
				t.Fatal(err)
			}
			_, err := os.Stat(name)
			if os.IsNotExist(err) != tc.removed {
				t.Fatalf("removed=%v, stat=%v", tc.removed, err)
			}
		})
	}
}

func TestDeleteResolvesSymlinksAndPreservesDirectories(t *testing.T) {
	base, outside := t.TempDir(), t.TempDir()
	inFile, outFile := filepath.Join(base, "real", "image.png"), filepath.Join(outside, "image.png")
	writeFixture(t, inFile)
	writeFixture(t, outFile)
	for link, target := range map[string]string{"inside": inFile, "outside": outFile, "outside-dir": outside, "dangling": filepath.Join(base, "missing")} {
		if err := os.Symlink(target, filepath.Join(base, link)); err != nil {
			t.Fatal(err)
		}
	}
	s := New(Config{Backend: "local", MediaDir: base})
	for _, path := range []string{"outside", "outside-dir/image.png", "dangling", "inside"} {
		if err := s.Delete(context.Background(), Media, path); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := os.Stat(inFile); !os.IsNotExist(err) {
		t.Fatalf("in-root target retained: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(base, "inside")); err != nil {
		t.Fatalf("source symlink must remain: %v", err)
	}
	if _, err := os.Stat(outFile); err != nil {
		t.Fatalf("outside target changed: %v", err)
	}
	for _, path := range []string{".", "real"} {
		if err := s.Delete(context.Background(), Media, path); !errors.Is(err, syscall.EISDIR) {
			t.Fatalf("directory %s: %v", path, err)
		}
	}
	if err := os.Symlink(base, filepath.Join(outside, "root-link")); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, inFile)
	s.Config.MediaDir = filepath.Join(outside, "root-link")
	if err := s.Delete(context.Background(), Media, "real/image.png"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(inFile); !os.IsNotExist(err) {
		t.Fatalf("symlink root not followed: %v", err)
	}
}

func TestDeleteS3RequestAndLocalCleanup(t *testing.T) {
	for _, tc := range []struct {
		backend string
		dual    bool
		status  int
		kind    Kind
		prefix  string
	}{
		{"s3", false, 204, Media, "media"},
		{"s3", false, 403, Media, "media"},
		{"s3", false, 503, Media, ""},
		{"local", true, 204, Feedback, "feedback"},
	} {
		t.Run(tc.backend+"/"+tc.prefix+"/"+http.StatusText(tc.status), func(t *testing.T) {
			base := t.TempDir()
			key := "photos/é %2F.png"
			file := filepath.Join(base, key)
			writeFixture(t, file)
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				want := "/fixture-bucket/" + key
				if tc.prefix != "" {
					want = "/fixture-bucket/" + tc.prefix + "/" + key
				}
				if r.Method != "DELETE" || r.URL.Path != want {
					t.Errorf("request %s %s, want DELETE %s", r.Method, r.URL.Path, want)
				}
				if !strings.HasPrefix(r.Header.Get("Authorization"), "AWS4-HMAC-SHA256 ") {
					t.Error("request was not signed")
				}
				w.WriteHeader(tc.status)
				if tc.status >= 400 {
					_, _ = w.Write([]byte("<Error><Code>AccessDenied</Code><Message>fixture error</Message></Error>"))
				}
			}))
			defer server.Close()
			s := New(Config{Backend: tc.backend, DualWriteLocal: tc.dual, MediaDir: base, FeedbackDir: base, Bucket: "fixture-bucket", MediaPrefix: tc.prefix, FeedbackPrefix: tc.prefix})
			s.client = s3.NewFromConfig(aws.Config{Region: "us-east-1", Credentials: aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
				return aws.Credentials{AccessKeyID: "fixture-key", SecretAccessKey: "fixture-secret"}, nil
			})}, func(o *s3.Options) {
				o.BaseEndpoint = aws.String(server.URL)
				o.UsePathStyle = true
				o.RetryMaxAttempts = 1
			})
			if err := s.Delete(context.Background(), tc.kind, key); err != nil {
				t.Fatal(err)
			}
			if calls != 1 {
				t.Fatalf("DELETE calls=%d", calls)
			}
			if _, err := os.Stat(file); !os.IsNotExist(err) {
				t.Fatalf("local cleanup not performed: %v", err)
			}
			if err := s.Delete(context.Background(), tc.kind, "../invalid"); err != nil {
				t.Fatal(err)
			}
			if calls != 1 {
				t.Fatal("invalid path reached S3")
			}
		})
	}
}

func TestDeleteS3KeepsLocalFailureVisible(t *testing.T) {
	base := t.TempDir()
	s := New(Config{Backend: "s3", MediaDir: base})
	// No bucket: source skips failed S3 cleanup and still tries local unlink.
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")
	if err := s.Delete(context.Background(), Media, "."); !errors.Is(err, syscall.EISDIR) {
		t.Fatalf("local failure hidden: %v", err)
	}
}
