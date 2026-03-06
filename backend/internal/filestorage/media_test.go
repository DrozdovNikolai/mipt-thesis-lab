package filestorage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"testing"
)

func TestCloneImageLocalMetadataAndCleanup(t *testing.T) {
	for _, tc := range []struct {
		name             string
		data             []byte
		limit            int64
		status           int
		media, extension string
	}{
		{"png", []byte("\x89PNG\r\n\x1a\nfixture"), 100, 0, "image/png", ".png"},
		{"jpeg", []byte("\xff\xd8\xfffixture"), 100, 0, "image/jpeg", ".jpg"},
		{"webp", []byte("RIFF0000WEBPfixture"), 100, 0, "image/webp", ".webp"},
		{"empty", nil, 100, 400, "", ""}, {"invalid", []byte("not an image"), 100, 415, "", ""},
		{"over-limit-before-signature", []byte("not an image"), 1, 413, "", ""},
		{"zero-limit", []byte("\x89PNG\r\n\x1a\n"), 0, 413, "", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			base := t.TempDir()
			source := filepath.Join(base, "source.invalid-extension")
			if err := os.WriteFile(source, tc.data, 0600); err != nil {
				t.Fatal(err)
			}
			s := New(Config{Backend: "local", MediaDir: base})
			stored, err := s.CloneImage(context.Background(), "source.invalid-extension", "exercise_images/1/2", tc.limit)
			if tc.status != 0 {
				var media *MediaError
				if !errors.As(err, &media) || media.Status != tc.status {
					t.Fatalf("expected status %d: %v", tc.status, err)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				if stored.ContentType != tc.media || !regexp.MustCompile(`^[a-f0-9]{32}`+regexp.QuoteMeta(tc.extension)+`$`).MatchString(stored.StorageKey) {
					t.Fatalf("metadata: %+v", stored)
				}
				got, err := os.ReadFile(filepath.Join(base, stored.StoragePath))
				if err != nil || !bytes.Equal(got, tc.data) {
					t.Fatalf("copy bytes: %v", err)
				}
				digest := sha256.Sum256(tc.data)
				if stored.SHA256 != hex.EncodeToString(digest[:]) || stored.SizeBytes != int64(len(tc.data)) {
					t.Fatalf("size/hash: %+v", stored)
				}
			}
			got, err := os.ReadFile(source)
			if err != nil || !bytes.Equal(got, tc.data) {
				t.Fatalf("source changed: %v", err)
			}
			matches, err := filepath.Glob(filepath.Join(base, "exercise_images/1/2/*.uploading"))
			if err != nil || len(matches) != 0 {
				t.Fatalf("temporary files leaked: %v %v", matches, err)
			}
			if tc.status != 0 {
				entries, _ := os.ReadDir(filepath.Join(base, "exercise_images/1/2"))
				if len(entries) != 0 {
					t.Fatalf("failed copy left files: %v", entries)
				}
			}
		})
	}
}

func TestCloneImageMissingAndOutsideSources(t *testing.T) {
	base, outside := t.TempDir(), t.TempDir()
	writeFixture(t, filepath.Join(outside, "private"))
	if err := os.Symlink(outside, filepath.Join(base, "outside")); err != nil {
		t.Fatal(err)
	}
	s := New(Config{Backend: "local", MediaDir: base})
	for _, path := range []string{"missing", ".", "../private", "outside/private", "/"} {
		_, err := s.CloneImage(context.Background(), path, "exercise_images/1/2", 100)
		var media *MediaError
		if !errors.As(err, &media) || media.Status != 404 {
			t.Fatalf("%q: %v", path, err)
		}
	}
	if _, err := os.Stat(filepath.Join(outside, "private")); err != nil {
		t.Fatal(err)
	}
}
