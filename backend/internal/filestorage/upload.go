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

// SaveImageUpload mirrors the source's declared MIME/extension checks, one MiB
// streaming limit, signature validation, digest and publish-after-validation.
// The caller owns the database commit and old-file cleanup.
func (s *Store) SaveImageUpload(ctx context.Context, reader io.Reader, filename, rawContentType, namespace string, maxBytes int64) (StoredMedia, error) {
	var result StoredMedia
	contentType := strings.ToLower(strings.TrimSpace(strings.SplitN(rawContentType, ";", 2)[0]))
	if contentType == "image/jpg" {
		contentType = "image/jpeg"
	}
	declaredType := ""
	switch contentType {
	case "image/png", "image/jpeg", "image/webp":
		declaredType = contentType
	}
	filenameType := ""
	extension := strings.ToLower(path.Ext(filename))
	switch extension {
	case ".png":
		filenameType = "image/png"
	case ".jpg", ".jpeg":
		filenameType = "image/jpeg"
	case ".webp":
		filenameType = "image/webp"
	}
	if declaredType == "" && filenameType == "" {
		label := rawContentType
		if label == "" {
			label = extension
		}
		if label == "" {
			label = "unknown"
		}
		return result, &MediaError{415, "Unsupported media type: " + label}
	}
	namespace, err := NormalizePath(namespace)
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
	if err := root.MkdirAll(path.Dir(temporaryPath), 0777); err != nil {
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
			if _, err := file.Write(buffer[:n]); err != nil {
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
	if err := file.Close(); err != nil {
		return StoredMedia{}, err
	}
	if result.SizeBytes == 0 {
		return StoredMedia{}, &MediaError{400, "Empty file upload is not allowed"}
	}
	detectedType, detectedExtension := imageContentType(probe)
	if detectedType == "" {
		return StoredMedia{}, &MediaError{415, "Unsupported media type: invalid image signature"}
	}
	if declaredType != "" && declaredType != detectedType {
		return StoredMedia{}, &MediaError{415, "Content type does not match file signature"}
	}
	if filenameType != "" && filenameType != detectedType {
		return StoredMedia{}, &MediaError{415, "Filename extension does not match file signature"}
	}
	result.StorageKey = storageID + detectedExtension
	result.StoragePath = namespace + "/" + result.StorageKey
	result.ContentType = detectedType
	result.SHA256 = hex.EncodeToString(digest.Sum(nil))
	if err := s.PersistTemp(ctx, Media, temporaryPath, result.StoragePath, detectedType); err != nil {
		return StoredMedia{}, err
	}
	return result, nil
}
