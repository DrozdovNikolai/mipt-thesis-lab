package training

import (
	"north55/backend/internal/platform"
)

var pendingRuntimeSchema = platform.Schema{Fields: runtimeSyncSchema.Fields[4:], Check: func(o platform.Object) string {
	if len(o["run_snapshots"].([]any)) == 0 && len(o["crew_assignment_events"].([]any)) == 0 {
		return ""
	}
	return runtimeSyncSchema.Check(o)
}}
var runtimeSealSchema = platform.Schema{Fields: []platform.Field{
	runtimeID("writer_instance_id", "writerInstanceId"), runtimeInt("writer_epoch", "writerEpoch", 1, false), runtimeID("expected_current_event_id", "expectedCurrentEventId"), runtimeInt("expected_client_sequence", "expectedClientSequence", 0, false), runtimeInt("base_server_revision", "baseServerRevision", 0, false),
	{Name: "pending_runtime", Alias: "pendingRuntime", Kind: "object", Schema: &pendingRuntimeSchema, Default: platform.Object{"run_snapshots": []any{}, "crew_assignment_events": []any{}}},
}}
var submitSchema = platform.Schema{Fields: []platform.Field{
	{Name: "idempotency_key", Alias: "idempotencyKey", Kind: "string", Min: 8, Max: 128, Nullable: true},
	{Name: "comment_contract_version", Alias: "commentContractVersion", Kind: "literal_integer", Choices: []string{"1"}, Nullable: true},
	{Name: "submission_manifest_hash", Alias: "submissionManifestHash", Kind: "string", Nullable: true, Pattern: "^[0-9a-f]{64}$"},
	{Name: "runtime_seal", Alias: "runtimeSeal", Kind: "object", Nullable: true, Schema: &runtimeSealSchema},
	{Name: "assessments", Kind: "list", Default: []any{}, Max: 2, Item: &platform.Field{Kind: "object", Schema: &finalizeBlockSchema}},
	{Name: "speech_session_id", Alias: "speechSessionId", Kind: "uuid", Nullable: true},
	{Name: "speech_last_chunk_index", Alias: "speechLastChunkIndex", Kind: "integer", Min: 1, Nullable: true},
	{Name: "speech_finish_managed_by_client", Alias: "speechFinishManagedByClient", Kind: "boolean", Default: false},
	{Name: "cm1", Kind: "object", Nullable: true, Schema: &finalizeBlockSchema},
	{Name: "cm2", Kind: "object", Nullable: true, Schema: &finalizeBlockSchema},
}, Check: func(o platform.Object) string {
	if o.Bool("speech_finish_managed_by_client") && (o["speech_session_id"] == nil || o["speech_last_chunk_index"] == nil) {
		return "client-managed speech finish requires session and final chunk index"
	}
	blocks := o["assessments"].([]any)
	if o["runtime_seal"] != nil {
		if o["submission_manifest_hash"] == nil {
			return "submission_manifest_hash is required with runtime_seal"
		}
		if o.String("idempotency_key") != o.String("submission_manifest_hash") {
			return "idempotency_key must equal submission_manifest_hash for runtime submit"
		}
		if len(blocks) != 2 {
			return "runtime submit requires exactly two assessment blocks"
		}
		if blocks[0].(platform.Object).Int("assessment_id") == blocks[1].(platform.Object).Int("assessment_id") {
			return "runtime assessment IDs must be unique"
		}
		if o["cm1"] != nil || o["cm2"] != nil {
			return "runtime submit must use assessments instead of cm1/cm2"
		}
	} else if len(blocks) > 0 {
		return "assessments requires runtime_seal"
	}
	return ""
}}
