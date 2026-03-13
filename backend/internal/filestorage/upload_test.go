package filestorage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestSaveImageUploadValidatesAndCleansTemporaryFiles(t *testing.T) {
	png := append([]byte{0x89, 'P', 'N', 'G', 13, 10, 26, 10}, []byte("isolated-photo")...)
	cases := []struct {
		name, filename, mime string
		content              []byte
		limit                int64
		status               int
	}{
		{"valid", "a.png", "image/png; charset=binary", png, 100, 0},
		{"extension-only", "a.png", "application/octet-stream", png, 100, 0},
		{"unsupported", "a.txt", "text/plain", png, 100, 415},
		{"empty", "a.png", "image/png", nil, 100, 400},
		{"too-large", "a.png", "image/png", png, int64(len(png) - 1), 413},
		{"invalid-signature", "a.png", "image/png", []byte("garbage"), 100, 415},
		{"mime-mismatch", "a.png", "image/jpeg", png, 100, 415},
		{"extension-mismatch", "a.jpg", "image/png", png, 100, 415},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			base := t.TempDir()
			store := New(Config{Backend: "local", MediaDir: base})
			stored, err := store.SaveImageUpload(context.Background(), bytes.NewReader(tc.content), tc.filename, tc.mime, "user_photos/fixture", tc.limit)
			if tc.status != 0 {
				var media *MediaError
				if !errors.As(err, &media) || media.Status != tc.status {
					t.Fatalf("expected media status %d, got %v", tc.status, err)
				}
				entries, walkErr := os.ReadDir(filepath.Join(base, "user_photos", "fixture"))
				if walkErr == nil && len(entries) != 0 {
					t.Fatalf("temporary file leaked: %v", entries)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			wanted := sha256.Sum256(tc.content)
			if stored.SHA256 != hex.EncodeToString(wanted[:]) || stored.SizeBytes != int64(len(tc.content)) || stored.ContentType != "image/png" {
				t.Fatalf("unexpected metadata: %+v", stored)
			}
			actual, err := os.ReadFile(filepath.Join(base, stored.StoragePath))
			if err != nil || !bytes.Equal(actual, tc.content) {
				t.Fatalf("wrong saved bytes: %v", err)
			}
		})
	}
}
