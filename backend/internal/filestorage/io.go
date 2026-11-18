package filestorage

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
	smithyhttp "github.com/aws/smithy-go/transport/http"
)

var ErrNotFound = errors.New("storage object not found")

// An S3 GET supplies a length that HTTP file readers must forward even while
// streaming. Local readers remain *os.File so ServeContent can handle ranges.
type objectReader struct {
	io.ReadCloser
	length *int64
}

func (r *objectReader) ContentLength() *int64 { return r.length }

func s3NotFound(err error) bool {
	var response *smithyhttp.ResponseError
	if errors.As(err, &response) && response.HTTPStatusCode() == 404 {
		return true
	}
	var api smithy.APIError
	if errors.As(err, &api) {
		switch strings.TrimSpace(api.ErrorCode()) {
		case "404", "NoSuchKey", "NotFound":
			return true
		}
	}
	return false
}

func (s *Store) localRoot(kind Kind, create bool) (*os.Root, error) {
	base, err := s.base(kind)
	if err != nil {
		return nil, err
	}
	if create {
		if err = os.MkdirAll(base, 0777); err != nil {
			return nil, err
		}
	}
	return os.OpenRoot(base)
}

func (s *Store) openLocal(kind Kind, normalized string) (io.ReadCloser, error) {
	base, err := s.base(kind)
	if err != nil {
		return nil, err
	}
	base, err = filepath.EvalSymlinks(base)
	if os.IsNotExist(err) || errors.Is(err, syscall.ENOTDIR) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	target, err := filepath.EvalSymlinks(base + string(filepath.Separator) + filepath.FromSlash(normalized))
	if os.IsNotExist(err) || errors.Is(err, syscall.ENOTDIR) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	relative, err := filepath.Rel(base, target)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return nil, ErrInvalidPath
	}
	root, err := os.OpenRoot(base)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	info, err := root.Stat(relative)
	if os.IsNotExist(err) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, ErrNotFound
	}
	return root.Open(relative)
}

// Open streams the object. Only a missing S3 object permits the configured
// local fallback; authorization, transport and other S3 errors remain errors.
func (s *Store) Open(ctx context.Context, kind Kind, storagePath string) (io.ReadCloser, error) {
	return s.open(ctx, kind, storagePath, "read")
}

func (s *Store) open(ctx context.Context, kind Kind, storagePath, operation string) (io.ReadCloser, error) {
	normalized, err := NormalizePath(storagePath)
	if err != nil {
		return nil, err
	}
	if s.Config.Backend != "s3" {
		return s.openLocal(kind, normalized)
	}
	client, err := s.s3Client(ctx)
	if err != nil {
		return nil, err
	}
	key, err := s.objectKey(kind, normalized)
	if err != nil {
		return nil, err
	}
	if s.Config.Bucket == "" {
		return nil, fmt.Errorf("S3 bucket is not configured")
	}
	response, err := client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key)})
	if err == nil {
		return &objectReader{ReadCloser: response.Body, length: response.ContentLength}, nil
	}
	if !s3NotFound(err) {
		return nil, err
	}
	if s.Config.ReadFallbackLocal {
		s.Config.Metrics.Inc("file_storage_s3_fallback_total", string(kind), operation)
		slog.Default().With("logger", "app.core.object_storage").WarnContext(ctx, "S3 object missing; falling back to local file storage", "storage_kind", string(kind), "storage_path", normalized, "s3_object_key", key, "operation", operation)
		return s.openLocal(kind, normalized)
	}
	return nil, ErrNotFound
}

// Preserve boto3 upload_file's 8 MiB threshold/parts, including multipart at
// exactly the threshold. Part boundaries also determine the object's ETag.
const multipartChunkSize int64 = 8 * 1024 * 1024

func (s *Store) uploadFile(ctx context.Context, kind Kind, file *os.File, storagePath, contentType string) error {
	client, err := s.s3Client(ctx)
	if err != nil {
		return err
	}
	if s.Config.Bucket == "" {
		return fmt.Errorf("S3 bucket is not configured")
	}
	key, err := s.objectKey(kind, storagePath)
	if err != nil {
		return err
	}
	info, err := file.Stat()
	if err != nil {
		return err
	}
	var mediaType *string
	if contentType != "" {
		mediaType = aws.String(contentType)
	}
	if info.Size() < multipartChunkSize {
		_, err = client.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), Body: file, ContentLength: aws.Int64(info.Size()), ContentType: mediaType})
		return err
	}
	start, err := client.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), ContentType: mediaType, ChecksumAlgorithm: types.ChecksumAlgorithmCrc32})
	if err != nil {
		return err
	}
	completed := false
	defer func() {
		if !completed {
			cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
			defer cancel()
			_, _ = client.AbortMultipartUpload(cleanup, &s3.AbortMultipartUploadInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), UploadId: start.UploadId})
		}
	}()
	partSize := multipartChunkSize
	for (info.Size()+partSize-1)/partSize > 10000 {
		partSize *= 2
	}
	parts := []types.CompletedPart{}
	for offset, number := int64(0), int32(1); offset < info.Size(); offset, number = offset+partSize, number+1 {
		size := min(partSize, info.Size()-offset)
		part, err := client.UploadPart(ctx, &s3.UploadPartInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), UploadId: start.UploadId, PartNumber: aws.Int32(number), Body: io.NewSectionReader(file, offset, size), ContentLength: aws.Int64(size), ChecksumAlgorithm: types.ChecksumAlgorithmCrc32})
		if err != nil {
			return err
		}
		parts = append(parts, types.CompletedPart{PartNumber: aws.Int32(number), ETag: part.ETag, ChecksumCRC32: part.ChecksumCRC32})
	}
	_, err = client.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key), UploadId: start.UploadId, MultipartUpload: &types.CompletedMultipartUpload{Parts: parts}})
	completed = err == nil
	return err
}

// PersistTemp publishes a temporary file under the same storage root. S3 is
// written before an optional local copy. Every failed attempt removes the temp.
func (s *Store) PersistTemp(ctx context.Context, kind Kind, temporaryPath, storagePath, contentType string) (err error) {
	temporaryPath, err = NormalizePath(temporaryPath)
	if err != nil {
		return err
	}
	storagePath, err = NormalizePath(storagePath)
	if err != nil {
		return err
	}
	root, err := s.localRoot(kind, false)
	if err != nil {
		return err
	}
	defer root.Close()
	moved := false
	defer func() {
		if !moved {
			if cleanupErr := root.Remove(temporaryPath); cleanupErr != nil && !os.IsNotExist(cleanupErr) {
				err = cleanupErr
			}
		}
	}()
	if s.Config.Backend == "s3" || s.Config.DualWriteLocal {
		file, err := root.Open(temporaryPath)
		if err != nil {
			return err
		}
		err = s.uploadFile(ctx, kind, file, storagePath, contentType)
		closeErr := file.Close()
		if err != nil {
			return err
		}
		if closeErr != nil {
			return closeErr
		}
	}
	if s.Config.Backend == "s3" && !s.Config.DualWriteLocal {
		return nil
	}
	if err = root.MkdirAll(filepath.Dir(storagePath), 0777); err != nil {
		return err
	}
	if err = root.Rename(temporaryPath, storagePath); err != nil {
		return err
	}
	moved = true
	return nil
}
