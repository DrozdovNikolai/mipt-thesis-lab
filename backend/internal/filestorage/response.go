package filestorage

import (
	"crypto/md5"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
)

func mediaQuote(filename string, slashSafe bool) string {
	const hex = "0123456789ABCDEF"
	var out strings.Builder
	for i := 0; i < len(filename); i++ {
		b := filename[i]
		if b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' || b >= '0' && b <= '9' || strings.ContainsRune("-_.~", rune(b)) || slashSafe && b == '/' {
			out.WriteByte(b)
		} else {
			out.WriteByte('%')
			out.WriteByte(hex[b>>4])
			out.WriteByte(hex[b&15])
		}
	}
	return out.String()
}

func mediaDisposition(filename string, s3 bool) string {
	if s3 {
		fallback := strings.Map(func(r rune) rune {
			if r > 127 || r == '"' || r == '\\' || r == '\r' || r == '\n' {
				return '_'
			}
			return r
		}, filename)
		return "attachment; filename=\"" + fallback + "\"; filename*=utf-8''" + mediaQuote(filename, false)
	}
	encoded := mediaQuote(filename, true)
	if encoded != filename {
		return "attachment; filename*=utf-8''" + encoded
	}
	return "attachment; filename=\"" + filename + "\""
}

// ServeMediaResponse retains the frozen Starlette FileResponse headers for
// local objects and the source's streaming headers for S3 objects. Range is
// ignored by this frozen version for both backends.
func (s *Store) ServeMediaResponse(w http.ResponseWriter, r *http.Request, kind Kind, storagePath, filename, mediaType string) error {
	reader, err := s.open(r.Context(), kind, storagePath, "stream")
	if err != nil {
		return err
	}
	defer reader.Close()
	if strings.HasPrefix(strings.ToLower(mediaType), "text/") && !strings.Contains(strings.ToLower(mediaType), "charset=") {
		mediaType += "; charset=utf-8"
	}
	w.Header().Set("Content-Type", mediaType)
	if local, ok := reader.(*os.File); ok {
		info, err := local.Stat()
		if err != nil {
			return err
		}
		w.Header().Set("Content-Disposition", mediaDisposition(filename, false))
		w.Header().Set("Content-Length", strconv.FormatInt(info.Size(), 10))
		w.Header().Set("Last-Modified", info.ModTime().UTC().Format(http.TimeFormat))
		stamp := strconv.FormatFloat(float64(info.ModTime().UnixNano())/1e9, 'f', -1, 64)
		if !strings.Contains(stamp, ".") {
			stamp += ".0"
		}
		etag := md5.Sum([]byte(stamp + "-" + strconv.FormatInt(info.Size(), 10)))
		w.Header().Set("ETag", fmt.Sprintf("\"%x\"", etag))
		_, err = io.Copy(w, local)
		return err
	}
	w.Header().Set("Content-Disposition", mediaDisposition(filename, true))
	if object, ok := reader.(interface{ ContentLength() *int64 }); ok {
		if length := object.ContentLength(); length != nil {
			w.Header().Set("Content-Length", strconv.FormatInt(*length, 10))
		}
	}
	_, err = io.Copy(w, reader)
	return err
}
