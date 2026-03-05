package filestorage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"strings"

	"github.com/google/uuid"
)

type MediaError struct {
	Status  int
	Message string
}

func (e *MediaError) Error() string { return e.Message }

type StoredMedia struct {
	StorageKey, StoragePath, ContentType, SHA256 string
	SizeBytes                                    int64
}

func imageContentType(probe []byte) (string, string) {
	switch {
	case bytes.HasPrefix(probe, []byte{0x89, 'P', 'N', 'G', 13, 10, 26, 10}):
		return "image/png", ".png"
	case bytes.HasPrefix(probe, []byte{255, 216, 255}):
		return "image/jpeg", ".jpg"
	case len(probe) >= 12 && string(probe[:4]) == "RIFF" && string(probe[8:12]) == "WEBP":
		return "image/webp", ".webp"
	}
	return "", ""
}

// CloneImage keeps the source bytes and determines metadata from those bytes,
// independently of stale source-row content type, size, extension or checksum.
func (s *Store) CloneImage(ctx context.Context, sourcePath, namespace string, maxBytes int64) (StoredMedia, error) {
	return s.cloneMedia(ctx, sourcePath, namespace, maxBytes, false)
}

// ClonePDF validates the PDF signature and retains the source bytes.
func (s *Store) ClonePDF(ctx context.Context, sourcePath, namespace string, maxBytes int64) (StoredMedia, error) {
	return s.cloneMedia(ctx, sourcePath, namespace, maxBytes, true)
}

func (s *Store) cloneMedia(ctx context.Context, sourcePath, namespace string, maxBytes int64, pdf bool) (StoredMedia, error) {
	kind := "image"
	if pdf {
		kind = "PDF"
	}
	var result StoredMedia
	reader, err := s.open(ctx, Media, sourcePath, "local_path")
	if errors.Is(err, ErrNotFound) || errors.Is(err, ErrInvalidPath) {
		return result, &MediaError{404, "Source " + kind + " not found"}
	}
	if err != nil {
		return result, err
	}
	defer reader.Close()
	if s.Config.Backend == "s3" {
		// The source materializes the complete S3 object before validating the
		// image or its size. A failed download must remain a storage failure.
		temporary, e := os.CreateTemp("", "ff-storage-*")
		if e != nil {
			return result, e
		}
		defer os.Remove(temporary.Name())
		_, copyErr := io.Copy(temporary, reader)
		closeErr := temporary.Close()
		if copyErr != nil {
			return result, copyErr
		}
		if closeErr != nil {
			return result, closeErr
		}
		reader, err = os.Open(temporary.Name())
		if err != nil {
			return result, err
		}
		defer reader.Close()
	}
	namespace, err = NormalizePath(namespace)
	if err != nil {
		return result, err
	}
	storageID := strings.ReplaceAll(uuid.NewString(), "-", "")
	temporaryPath := namespace + "/" + storageID + ".uploading"
	root, err := s.localRoot(Media, true)
	if err != nil {
		return result, err
	}
	defer root.Close()
	if err = root.MkdirAll(path.Dir(temporaryPath), 0777); err != nil {
		return result, err
	}
	file, err := root.OpenFile(temporaryPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0666)
	if err != nil {
		return result, err
	}
	defer root.Remove(temporaryPath)
	digest := sha256.New()
	probe := []byte{}
	buffer := make([]byte, 1024*1024)
	for {
		n, readErr := reader.Read(buffer)
		if n > 0 {
			if len(probe) < 64 {
				probe = append(probe, buffer[:min(n, 64-len(probe))]...)
			}
			result.SizeBytes += int64(n)
			if result.SizeBytes > maxBytes {
				file.Close()
				return StoredMedia{}, &MediaError{413, fmt.Sprintf("File too large (max %d bytes)", maxBytes)}
			}
			if _, err = file.Write(buffer[:n]); err != nil {
				file.Close()
				return StoredMedia{}, err
			}
			_, _ = digest.Write(buffer[:n])
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			file.Close()
			return StoredMedia{}, readErr
		}
	}
	if err = file.Close(); err != nil {
		return StoredMedia{}, err
	}
	if result.SizeBytes == 0 {
		return StoredMedia{}, &MediaError{400, "Empty file upload is not allowed"}
	}
	contentType, extension := imageContentType(probe)
	if pdf {
		contentType, extension = "", ""
		if bytes.HasPrefix(probe, []byte("%PDF-")) {
			contentType, extension = "application/pdf", ".pdf"
		}
	}
	if contentType == "" {
		return StoredMedia{}, &MediaError{415, "Unsupported media type: invalid " + kind + " signature"}
	}
	result.StorageKey = storageID + extension
	result.StoragePath = namespace + "/" + result.StorageKey
	result.ContentType = contentType
	result.SHA256 = hex.EncodeToString(digest.Sum(nil))
	if err = s.PersistTemp(ctx, Media, temporaryPath, result.StoragePath, contentType); err != nil {
		return StoredMedia{}, err
	}
	return result, nil
}
