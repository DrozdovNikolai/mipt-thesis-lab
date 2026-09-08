package training

import (
	"north55/backend/internal/platform"
	"strings"
)

var draftSaveSchema = platform.Schema{Fields: []platform.Field{
	{Name: "contract_version", Alias: "contractVersion", Kind: "literal_integer", Choices: []string{"3"}, Nullable: true},
	optionalField(runtimeID("writer_instance_id", "writerInstanceId")),
	{Name: "client_revision", Alias: "clientRevision", Kind: "integer", Min: 1, Nullable: true},
	{Name: "payload_sha256", Alias: "payloadSha256", Kind: "string", Pattern: "^[0-9a-f]{64}$", Nullable: true},
	{Name: "payload", Kind: "dictionary", Default: map[string]any{}},
	{Name: "submitted", Kind: "boolean", Default: false},
}, Check: func(o platform.Object) string {
	count := 0
	for _, key := range []string{"contract_version", "writer_instance_id", "client_revision", "payload_sha256"} {
		if o[key] != nil {
			count++
		}
	}
	if count != 0 && count != 4 {
		return "contractVersion, writerInstanceId, clientRevision and payloadSha256 must be provided together"
	}
	return ""
}}

var draftPatchSchema = platform.Schema{Fields: []platform.Field{
	{Name: "crew", Kind: "string", Required: true, Min: 2, Max: 3},
	{Name: "comment", Kind: "string", Nullable: true},
	{Name: "hashtag", Kind: "string", Nullable: true},
	{Name: "exercise_id", Alias: "exerciseId", Kind: "integer", GreaterThanZero: true, Nullable: true},
	{Name: "is_positive", Alias: "isPositive", Kind: "boolean", Nullable: true},
}, Check: func(o platform.Object) string {
	crew := strings.ToUpper(strings.TrimSpace(o.String("crew")))
	if crew != "CM1" && crew != "CM2" {
		return "crew must be CM1 or CM2"
	}
	if o["comment"] == nil && o["hashtag"] == nil && o["exercise_id"] == nil && o["is_positive"] == nil {
		return "At least one field must be provided for update"
	}
	o["crew"] = crew
	return ""
}}

func draftError(code string, extra map[string]any) *platform.APIError {
	status, message := 422, ""
	switch code {
	case "DRAFT_CONTRACT_REQUIRED":
		message = "Revisioned draft contract v3 is required for this training"
	case "DRAFT_PAYLOAD_INVALID":
		message = "Training draft payload failed integrity validation"
	case "DRAFT_PAYLOAD_TOO_LARGE":
		status = 413
		message = "Training draft payload exceeds the configured size limit"
	case "DRAFT_PAYLOAD_HASH_INVALID":
		status = 400
		message = "Draft payload hash does not match canonical payload"
	case "STALE_DRAFT_REVISION":
		status = 409
		message = "Remote draft has a newer revision"
	case "DRAFT_REVISION_HASH_CONFLICT":
		status = 409
		message = "The same draft revision was received with different content"
	case "DRAFT_WRITER_CONFLICT":
		status = 409
		message = "Draft belongs to a different logical writer"
	case "UNRESOLVED_QUICK_COMMENTS":
		status = 409
		message = "Resolve all quick comments before completing training"
	case "QUICK_COMMENT_CAPABILITY_NOT_GRANTED":
		status = 409
		message = "This training session was not granted Quick Comments"
	case "EVALUATION_CATALOG_SNAPSHOT_INVALID":
		status = 409
		message = "The training evaluation catalog snapshot is missing or invalid"
	}
	return &platform.APIError{Status: status, Code: code, Message: message, Extra: extra}
}

func invalidDraft(field, reason string) error {
	return draftError("DRAFT_PAYLOAD_INVALID", map[string]any{"field": field, "reason": reason})
}
