package filestorage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path"
	"strings"

	"github.com/google/uuid"
)

// SaveFeedbackUpload streams an arbitrary attachment to the configured
// feedback store, retaining the source filename suffix and SHA-256 digest.
func (s *Store) SaveFeedbackUpload(ctx context.Context, reader io.Reader, filename, contentType string, ticketID, maxBytes int64) (StoredMedia, error) {
	var result StoredMedia
	originalName := path.Base(filename)
	suffix := []rune(path.Ext(originalName))
	if len(suffix) > 16 {
		suffix = suffix[:16]
	}
	storageName := strings.ReplaceAll(uuid.NewString(), "-", "") + string(suffix)
	result.StorageKey = storageName
	result.StoragePath = fmt.Sprintf("%d/%s", ticketID, storageName)
	result.ContentType = contentType
	temporaryPath := result.StoragePath + ".uploading"
	root, err := s.localRoot(Feedback, true)
	if err != nil {
		return StoredMedia{}, err
	}
	defer root.Close()
	if err = root.MkdirAll(path.Dir(temporaryPath), 0777); err != nil {
		return StoredMedia{}, err
	}
	file, err := root.OpenFile(temporaryPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0666)
	if err != nil {
		return StoredMedia{}, err
	}
	defer root.Remove(temporaryPath)
	digest := sha256.New()
	buffer := make([]byte, 1024*1024)
	for {
		n, readErr := reader.Read(buffer)
		if n > 0 {
			result.SizeBytes += int64(n)
			if result.SizeBytes > maxBytes {
				file.Close()
				return StoredMedia{}, &MediaError{413, fmt.Sprintf("Attachment %q exceeds max size", filename)}
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
	result.SHA256 = hex.EncodeToString(digest.Sum(nil))
	if err = s.PersistTemp(ctx, Feedback, temporaryPath, result.StoragePath, result.ContentType); err != nil {
		return StoredMedia{}, err
	}
	return result, nil
}
