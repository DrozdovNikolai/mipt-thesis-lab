// Package filestorage provides the local/S3 media and feedback storage boundary.
// Speech storage is intentionally outside the target application.
package filestorage

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/user"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"syscall"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type Kind string

const (
	Media    Kind = "media"
	Feedback Kind = "feedback"
)

var ErrInvalidPath = errors.New("invalid storage path")

type Store struct {
	Config Config
	mu     sync.Mutex
	client *s3.Client
}

func New(config Config) *Store { return &Store{Config: config} }

// Match PurePosixPath normalization, including harmless ./ and repeated slashes,
// while rejecting every parent traversal component before cleaning the path.
func NormalizePath(value string) (string, error) {
	value = strings.Trim(strings.ReplaceAll(trim(value), `\`, "/"), "/")
	if value == "" || strings.ContainsRune(value, 0) {
		return "", ErrInvalidPath
	}
	for _, component := range strings.Split(value, "/") {
		if component == ".." {
			return "", ErrInvalidPath
		}
	}
	return path.Clean(value), nil
}

func (s *Store) base(kind Kind) (string, error) {
	var value string
	switch kind {
	case Media:
		value = s.Config.MediaDir
	case Feedback:
		value = s.Config.FeedbackDir
	default:
		return "", fmt.Errorf("unsupported storage kind %q", kind)
	}
	if strings.HasPrefix(value, "~") {
		name, rest, _ := strings.Cut(value[1:], "/")
		var home string
		var err error
		if name == "" {
			home, err = os.UserHomeDir()
		} else {
			var account *user.User
			account, err = user.Lookup(name)
			if err == nil {
				home = account.HomeDir
			}
		}
		if err != nil {
			return "", err
		}
		value = filepath.Join(home, rest)
	}
	return filepath.Abs(value)
}

func (s *Store) objectKey(kind Kind, normalized string) (string, error) {
	var prefix string
	switch kind {
	case Media:
		prefix = s.Config.MediaPrefix
	case Feedback:
		prefix = s.Config.FeedbackPrefix
	default:
		return "", fmt.Errorf("unsupported storage kind %q", kind)
	}
	if prefix == "" {
		return normalized, nil
	}
	return prefix + "/" + normalized, nil
}

func (s *Store) s3Client(ctx context.Context) (*s3.Client, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.client != nil {
		return s.client, nil
	}
	options := []func(*awsconfig.LoadOptions) error{}
	if s.Config.Region != "" {
		options = append(options, awsconfig.WithRegion(s.Config.Region))
	}
	config, err := awsconfig.LoadDefaultConfig(ctx, options...)
	if err != nil {
		return nil, err
	}
	// Boto3's S3 client uses the global us-east-1 endpoint when no region is
	// configured. Keep credential/profile resolution in the official SDK.
	if config.Region == "" {
		config.Region = "us-east-1"
	}
	s.client = s3.NewFromConfig(config, func(options *s3.Options) {
		options.UsePathStyle = s.Config.ForcePathStyle
		if s.Config.Endpoint != "" {
			options.BaseEndpoint = aws.String(s.Config.Endpoint)
		}
	})
	return s.client, nil
}

// Delete follows the existing post-commit cleanup contract: an S3 error does
// not stop local cleanup, while a local I/O failure is returned to the caller.
func (s *Store) Delete(ctx context.Context, kind Kind, storagePath string) error {
	normalized, err := NormalizePath(storagePath)
	if errors.Is(err, ErrInvalidPath) {
		return nil
	}
	if err != nil {
		return err
	}
	key, err := s.objectKey(kind, normalized)
	if err != nil {
		return err
	}
	if s.Config.Backend == "s3" || s.Config.DualWriteLocal {
		if client, err := s.s3Client(ctx); err == nil && s.Config.Bucket != "" {
			_, _ = client.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: aws.String(s.Config.Bucket), Key: aws.String(key)})
		}
	}
	base, err := s.base(kind)
	if err != nil {
		return err
	}
	base, err = filepath.EvalSymlinks(base)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	// Resolve the final symlink before unlinking: an in-root symlink
	// deletes its target. An outside target is ignored. Missing paths are no-op.
	target, err := filepath.EvalSymlinks(base + string(filepath.Separator) + filepath.FromSlash(normalized))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	relative, err := filepath.Rel(base, target)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return nil
	}
	root, err := os.OpenRoot(base)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	defer root.Close()
	info, err := root.Stat(relative)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	// Guard against removing directories through the file deletion endpoint.
	if info.IsDir() {
		return &os.PathError{Op: "unlink", Path: target, Err: syscall.EISDIR}
	}
	err = root.Remove(relative)
	if os.IsNotExist(err) {
		return nil
	}
	return err
}
