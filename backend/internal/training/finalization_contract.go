package training

import (
	"sort"
	"strings"
	"unicode/utf8"

	"north55/backend/internal/platform"
)

func commentCompletionError(code string, extra map[string]any) error {
	status, message := 422, ""
	switch code {
	case "COMMENT_OB_REQUIRED":
		message = "Every comment must have a behavioural indicator"
	case "COMMENT_TEXT_INVALID":
		message = "Comment text contains an unsupported control character"
	case "COMMENT_TEXT_REQUIRED":
		message = "Every contract-v1 comment must contain text"
	case "COMMENT_TEXT_TOO_LONG":
		message = "Comment text exceeds the 4000 character limit"
	case "QUICK_COMMENT_CONTRACT_INCOMPLETE":
		message = "Quick comment completion proof is required"
	case "COMMENT_CONTRACT_VERSION_REQUIRED":
		status = 409
		message = "Request comment contract does not match the training session"
	}
	return &platform.APIError{Status: status, Code: code, Message: message, Extra: extra}
}
func finalizeBlocks(o platform.Object) []platform.Object {
	blocks := []platform.Object{}
	for _, key := range []string{"cm1", "cm2"} {
		if b, ok := o[key].(platform.Object); ok {
			blocks = append(blocks, b)
		}
	}
	return blocks
}
func normalizeComment(s string) string {
	return pythonTrim(strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\r", "\n"))
}
func unsupportedCommentControl(s string) bool {
	for _, r := range s {
		if r < 0x20 && r != '\t' && r != '\n' && r != '\r' || r >= 0x7f && r <= 0x9f {
			return true
		}
	}
	return false
}
func validateCommentCompletion(o platform.Object, version int64) error {
	blocks := finalizeBlocks(o)
	if version == 0 {
		bad := o["comment_contract_version"] != nil
		for _, b := range blocks {
			bad = bad || len(b["unresolved_quick_comments"].([]any)) > 0
		}
		if bad {
			return draftError("QUICK_COMMENT_CAPABILITY_NOT_GRANTED", nil)
		}
		return nil
	}
	if version != 1 || o.Int("comment_contract_version") != version {
		return commentCompletionError("COMMENT_CONTRACT_VERSION_REQUIRED", map[string]any{"expectedVersion": version, "receivedVersion": o["comment_contract_version"]})
	}
	if len(blocks) == 0 {
		return commentCompletionError("QUICK_COMMENT_CONTRACT_INCOMPLETE", nil)
	}
	ids := []string{}
	assessments := map[int64]bool{}
	for _, b := range blocks {
		for _, raw := range b["unresolved_quick_comments"].([]any) {
			ids = append(ids, pythonString(raw.(platform.Object)["client_report_id"]))
			assessments[b.Int("assessment_id")] = true
		}
	}
	if len(ids) > 0 {
		linked := []int64{}
		for id := range assessments {
			linked = append(linked, id)
		}
		sort.Slice(linked, func(i, j int) bool { return linked[i] < linked[j] })
		count := len(ids)
		if count > 50 {
			ids = ids[:50]
		}
		return draftError("UNRESOLVED_QUICK_COMMENTS", map[string]any{"count": count, "assessmentIds": linked, "clientReportIds": ids, "truncated": count > 50})
	}
	for _, b := range blocks {
		if !b.Bool("quick_proof_present") {
			return commentCompletionError("QUICK_COMMENT_CONTRACT_INCOMPLETE", map[string]any{"assessmentId": b.Int("assessment_id")})
		}
		for _, raw := range b["mistake_reports"].([]any) {
			r := raw.(platform.Object)
			var extra map[string]any
			if r["client_report_id"] != nil {
				extra = map[string]any{"clientReportId": r["client_report_id"]}
			}
			if r["bi_id"] == nil {
				return commentCompletionError("COMMENT_OB_REQUIRED", extra)
			}
			text := r.String("comment")
			if unsupportedCommentControl(text) {
				return commentCompletionError("COMMENT_TEXT_INVALID", extra)
			}
			normalized := normalizeComment(text)
			if normalized == "" {
				return commentCompletionError("COMMENT_TEXT_REQUIRED", extra)
			}
			if utf8.RuneCountInString(normalized) > 4000 {
				return commentCompletionError("COMMENT_TEXT_TOO_LONG", extra)
			}
		}
	}
	return nil
}
