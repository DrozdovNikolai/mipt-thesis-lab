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

func TestSavePDFUploadValidatesAndCleansTemporaryFiles(t *testing.T) {
	pdf := []byte("%PDF-1.4\nfixture\n%%EOF\n")
	cases := []struct {
		name, filename, mime string
		content              []byte
		limit                int64
		status               int
	}{
		{"valid", "рейс.pdf", "application/pdf; charset=binary", pdf, 100, 0},
		{"extension-only", "a.pdf", "application/octet-stream", pdf, 100, 0},
		{"mime-only", "a.bin", "application/pdf", pdf, 100, 0},
		{"unsupported", "a.txt", "text/plain", pdf, 100, 415},
		{"empty", "a.pdf", "application/pdf", nil, 100, 400},
		{"too-large", "a.pdf", "application/pdf", pdf, int64(len(pdf) - 1), 413},
		{"invalid-signature", "a.pdf", "application/pdf", []byte("garbage"), 100, 415},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			base := t.TempDir()
			store := New(Config{Backend: "local", MediaDir: base})
			stored, err := store.SavePDFUpload(context.Background(), bytes.NewReader(tc.content), tc.filename, tc.mime, "scenario_pdfs/1", tc.limit)
			if tc.status != 0 {
				var media *MediaError
				if !errors.As(err, &media) || media.Status != tc.status {
					t.Fatalf("expected status %d, got %v", tc.status, err)
				}
				entries, walkErr := os.ReadDir(filepath.Join(base, "scenario_pdfs", "1"))
				if walkErr == nil && len(entries) != 0 {
					t.Fatalf("temporary file leaked: %v", entries)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			wanted := sha256.Sum256(tc.content)
			if stored.SHA256 != hex.EncodeToString(wanted[:]) || stored.SizeBytes != int64(len(tc.content)) || stored.ContentType != "application/pdf" {
				t.Fatalf("wrong metadata: %+v", stored)
			}
			actual, err := os.ReadFile(filepath.Join(base, stored.StoragePath))
			if err != nil || !bytes.Equal(actual, tc.content) {
				t.Fatalf("wrong bytes: %v", err)
			}
		})
	}
}
