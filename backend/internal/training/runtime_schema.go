package training

import (
	"fmt"
	"sort"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func runtimeID(name, alias string) platform.Field {
	return platform.Field{Name: name, Alias: alias, Kind: "uuid7", Required: true}
}
func runtimeInt(name, alias string, min int, strict bool) platform.Field {
	return platform.Field{Name: name, Alias: alias, Kind: "integer", Required: true, Min: min, NonNegative: true, GreaterThanZero: strict, AllowBigInteger: name == "writer_epoch" || name == "expected_writer_epoch" || name == "base_server_revision"}
}
func runtimeChoice(name, alias string, choices ...string) platform.Field {
	return platform.Field{Name: name, Alias: alias, Kind: "literal", Required: true, Choices: choices}
}
func runtimeTime(name, alias, message string, optional bool) platform.Field {
	return platform.Field{Name: name, Alias: alias, Kind: "datetime", Required: !optional, Nullable: optional, Check: func(value any) string {
		if !platform.HasTimeZone(value.(time.Time)) {
			return message
		}
		return ""
	}}
}
func optionalField(f platform.Field) platform.Field { f.Required = false; f.Nullable = true; return f }
func runtimeHash() platform.Field {
	return platform.Field{Name: "payload_hash", Alias: "payloadHash", Kind: "string", Required: true, Pattern: "^[0-9a-f]{64}$"}
}

var runtimeRunSchema = platform.Schema{Fields: []platform.Field{
	runtimeID("exercise_session_key", "exerciseSessionKey"), runtimeInt("runtime_exercise_id", "runtimeExerciseId", 0, true), runtimeInt("run_index", "runIndex", 1, false), runtimeChoice("status", "status", "READY", "ACTIVE", "PAUSED", "COMPLETED", "ABANDONED"), runtimeID("initial_assignment_event_id", "initialAssignmentEventId"), runtimeInt("planned_duration_ms", "plannedDurationMs", 0, false), runtimeInt("active_duration_ms", "activeDurationMs", 0, false), runtimeTime("started_at", "startedAt", "run timestamps must be timezone-aware", true), runtimeTime("ended_at", "endedAt", "run timestamps must be timezone-aware", true), runtimeInt("client_revision", "clientRevision", 1, false), runtimeHash(),
}, Check: func(o platform.Object) string {
	start, end := o["started_at"], o["ended_at"]
	switch o.String("status") {
	case "READY":
		if o.Int("active_duration_ms") != 0 || start != nil || end != nil {
			return "READY run must have zero duration and no timestamps"
		}
	case "ACTIVE", "PAUSED":
		if start == nil || end != nil {
			return "ACTIVE/PAUSED run requires started_at and no ended_at"
		}
	case "COMPLETED":
		if start == nil || end == nil {
			return "COMPLETED run requires both timestamps"
		}
	case "ABANDONED":
		if end == nil {
			return "ABANDONED run requires ended_at"
		}
		if start == nil && o.Int("active_duration_ms") != 0 {
			return "unstarted ABANDONED run must have zero duration"
		}
	}
	if start != nil && end != nil && end.(time.Time).Before(start.(time.Time)) {
		return "ended_at must not be earlier than started_at"
	}
	return ""
}}
var runtimeEventSchema = platform.Schema{Fields: []platform.Field{
	runtimeID("client_event_id", "clientEventId"), runtimeInt("client_sequence", "clientSequence", 1, false), runtimeID("previous_event_id", "previousEventId"), runtimeTime("occurred_at", "occurredAt", "occurred_at must be timezone-aware", false), runtimeChoice("scope", "scope", "SESSION", "EXERCISE_RUN"), optionalField(runtimeInt("runtime_exercise_id", "runtimeExerciseId", 0, true)), optionalField(runtimeID("exercise_session_key", "exerciseSessionKey")), optionalField(runtimeInt("exercise_offset_ms", "exerciseOffsetMs", 0, false)), runtimeChoice("timer_state", "timerState", "NONE", "RUNNING", "PAUSED"), runtimeInt("cm1_assessment_id_after", "cm1AssessmentIdAfter", 0, true), runtimeInt("cm2_assessment_id_after", "cm2AssessmentIdAfter", 0, true), runtimeHash(), {Name: "client_app_version", Alias: "clientAppVersion", Kind: "string", Nullable: true, Max: 50}, {Name: "client_platform", Alias: "clientPlatform", Kind: "string", Nullable: true, Max: 30},
}, Check: func(o platform.Object) string {
	if o.Int("cm1_assessment_id_after") == o.Int("cm2_assessment_id_after") {
		return "crew assignment assessment IDs must differ"
	}
	if o.String("scope") == "SESSION" {
		if o["runtime_exercise_id"] != nil || o["exercise_session_key"] != nil || o["exercise_offset_ms"] != nil || o.String("timer_state") != "NONE" {
			return "SESSION event must not contain run context"
		}
	} else if o["runtime_exercise_id"] == nil || o["exercise_session_key"] == nil || o["exercise_offset_ms"] == nil || o.String("timer_state") == "NONE" {
		return "EXERCISE_RUN event requires complete run context"
	}
	return ""
}}
var runtimeSyncSchema = platform.Schema{Fields: []platform.Field{
	runtimeID("writer_instance_id", "writerInstanceId"), runtimeInt("writer_epoch", "writerEpoch", 1, false), runtimeInt("base_server_revision", "baseServerRevision", 0, false), runtimeID("base_server_event_id", "baseServerEventId"),
	{Name: "run_snapshots", Alias: "runSnapshots", Kind: "list", Max: 200, Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &runtimeRunSchema}},
	{Name: "crew_assignment_events", Alias: "crewAssignmentEvents", Kind: "list", Max: 200, Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &runtimeEventSchema}},
}, Check: func(o platform.Object) string {
	runs, events := o["run_snapshots"].([]any), o["crew_assignment_events"].([]any)
	if len(runs) == 0 && len(events) == 0 {
		return "runtime sync batch must not be empty"
	}
	for i := 1; i < len(events); i++ {
		if events[i].(platform.Object).Int("client_sequence") < events[i-1].(platform.Object).Int("client_sequence") {
			return "crew_assignment_events must be ordered by client_sequence"
		}
	}
	for i := 1; i < len(events); i++ {
		if events[i].(platform.Object).Int("client_sequence") != events[0].(platform.Object).Int("client_sequence")+int64(i) {
			return "crew_assignment_events must have contiguous sequences"
		}
	}
	keys := map[uuid.UUID]bool{}
	for _, item := range runs {
		key := item.(platform.Object)["exercise_session_key"].(uuid.UUID)
		if keys[key] {
			return "run_snapshots must contain one revision per run"
		}
		keys[key] = true
	}
	return ""
}}

func versionList(name, alias string) platform.Field {
	return platform.Field{Name: name, Alias: alias, Kind: "list", Max: 8, Default: []any{}, Item: &platform.Field{Kind: "integer"}, Check: func(value any) string {
		for _, v := range value.([]any) {
			if v.(int64) < 1 || v.(int64) > 100 {
				return fmt.Sprintf("%s must contain values between 1 and 100", name)
			}
		}
		return ""
	}}
}

var runtimeCapabilitiesSchema = platform.Schema{Fields: []platform.Field{
	versionList("live_crew_swap_versions", "liveCrewSwapVersions"), versionList("quick_comment_versions", "quickCommentVersions"),
	{Name: "transactional_store", Alias: "transactionalStore", Kind: "literal", Choices: []string{"SQLITE", "INDEXED_DB", "NONE"}, Default: "NONE"},
	{Name: "offline_durability_ready", Alias: "offlineDurabilityReady", Kind: "boolean", Default: false},
}}
var runtimeBootstrapSchema = platform.Schema{Fields: []platform.Field{runtimeID("writer_instance_id", "writerInstanceId"), {Name: "runtime_client_capabilities", Alias: "runtimeClientCapabilities", Kind: "object", Required: true, Schema: &runtimeCapabilitiesSchema}}}
var runtimeTakeoverSchema = platform.Schema{Fields: []platform.Field{runtimeID("new_writer_instance_id", "newWriterInstanceId"), runtimeInt("expected_writer_epoch", "expectedWriterEpoch", 1, false), {Name: "explicit_confirmation", Alias: "explicitConfirmation", Kind: "boolean", Required: true}, {Name: "reason", Kind: "string", Nullable: true, Max: 500}}, Check: func(o platform.Object) string {
	if !o.Bool("explicit_confirmation") {
		return "explicit_confirmation must be true"
	}
	return ""
}}

func runtimePtr[T any](o platform.Object, name string) *T {
	if value, ok := o[name].(T); ok {
		return &value
	}
	return nil
}
func parseRuntimeBatch(o platform.Object) runtimeBatch {
	batch := runtimeBatch{Writer: o["writer_instance_id"].(uuid.UUID), Epoch: o.Int("writer_epoch"), BaseRevision: o.Int("base_server_revision"), BaseEvent: o["base_server_event_id"].(uuid.UUID)}
	for _, item := range o["run_snapshots"].([]any) {
		v := item.(platform.Object)
		batch.Runs = append(batch.Runs, runtimeRunInput{ExerciseRun: canonical.ExerciseRun{ExerciseSessionKey: v["exercise_session_key"].(uuid.UUID), InitialAssignmentEventID: v["initial_assignment_event_id"].(uuid.UUID), RuntimeExerciseID: v.Int("runtime_exercise_id"), RunIndex: v.Int("run_index"), PlannedDurationMS: v.Int("planned_duration_ms"), ActiveDurationMS: v.Int("active_duration_ms"), ClientRevision: v.Int("client_revision"), Status: v.String("status"), StartedAt: runtimePtr[time.Time](v, "started_at"), EndedAt: runtimePtr[time.Time](v, "ended_at")}, Hash: v.String("payload_hash")})
	}
	for _, item := range o["crew_assignment_events"].([]any) {
		v := item.(platform.Object)
		batch.Events = append(batch.Events, runtimeEventInput{CrewEvent: canonical.CrewEvent{ClientEventID: v["client_event_id"].(uuid.UUID), PreviousEventID: v["previous_event_id"].(uuid.UUID), ClientSequence: v.Int("client_sequence"), OccurredAt: v["occurred_at"].(time.Time), Scope: v.String("scope"), TimerState: v.String("timer_state"), RuntimeExerciseID: runtimePtr[int64](v, "runtime_exercise_id"), ExerciseOffsetMS: runtimePtr[int64](v, "exercise_offset_ms"), ExerciseSessionKey: runtimePtr[uuid.UUID](v, "exercise_session_key"), CM1AssessmentIDAfter: v.Int("cm1_assessment_id_after"), CM2AssessmentIDAfter: v.Int("cm2_assessment_id_after")}, Hash: v.String("payload_hash"), AppVersion: v.StringPtr("client_app_version"), Platform: v.StringPtr("client_platform")})
	}
	return batch
}
func parseCapabilities(o platform.Object) canonical.Capabilities {
	c := canonical.Capabilities{OfflineDurabilityReady: o.Bool("offline_durability_ready"), TransactionalStore: o.String("transactional_store")}
	for _, v := range o["live_crew_swap_versions"].([]any) {
		c.LiveCrewSwapVersions = append(c.LiveCrewSwapVersions, v.(int64))
	}
	sort.Slice(c.LiveCrewSwapVersions, func(i, j int) bool { return c.LiveCrewSwapVersions[i] < c.LiveCrewSwapVersions[j] })
	for _, v := range o["quick_comment_versions"].([]any) {
		c.QuickCommentVersions = append(c.QuickCommentVersions, v.(int64))
	}
	return c
}
