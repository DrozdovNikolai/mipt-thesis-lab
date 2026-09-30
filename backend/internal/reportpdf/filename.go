package reportpdf

import (
	"fmt"
	"strings"
	"time"
)

func Filename(r Report) string {
	name := safeName(r.Trainee.Name)
	if name == "" {
		name = r.Role
	}
	day := r.GeneratedAt.UTC()
	if day.IsZero() {
		day = time.Now().UTC()
	}
	if r.CompletedAt != nil {
		day = *r.CompletedAt
	}
	return fmt.Sprintf("training-report-%d-%s-%s-%s.pdf", r.TrainingID, r.Role, name, day.Format("2006-01-02"))
}

func safeName(value string) string {
	var result strings.Builder
	separator := false
	for _, char := range strings.ToLower(strings.TrimSpace(value)) {
		switch {
		case char >= 'a' && char <= 'z', char >= '0' && char <= '9':
			if separator && result.Len() > 0 {
				result.WriteByte('-')
			}
			separator = false
			result.WriteRune(char)
		case char == ' ', char == '-', char == '_', char == '.':
			separator = true
		}
		if result.Len() >= 80 {
			break
		}
	}
	return strings.Trim(result.String(), "-")
}
