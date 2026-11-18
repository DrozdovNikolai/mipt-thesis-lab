package training

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

var mistakeReportSchema = platform.Schema{Fields: []platform.Field{
	optionalField(runtimeID("client_report_id", "clientReportId")),
	{Name: "timeline_source", Alias: "timelineSource", Kind: "literal", Choices: []string{"TIMELINE", "LEGACY_STATIC"}, Default: "LEGACY_STATIC"},
	runtimeInt("exercise_id", "exerciseId", 0, true), runtimeTime("timestamp", "timestamp", "timestamp must be timezone-aware (UTC)", false), runtimeInt("exercise_offset_sec", "exerciseOffsetSec", 0, false), optionalField(runtimeInt("exercise_offset_ms", "exerciseOffsetMs", 0, false)),
	{Name: "exercise_session_key", Alias: "exerciseSessionKey", Kind: "string", Required: true, Min: 36, Max: 36, Check: func(value any) string {
		s := strings.ToLower(pythonTrim(value.(string)))
		if s == "" {
			return "exercise_session_key must not be empty"
		}
		if !regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).MatchString(s) {
			return "exercise_session_key must be RFC4122 UUIDv7"
		}
		return ""
	}},
	{Name: "assignment_event_id_at_observation", Alias: "assignmentEventIdAtObservation", Kind: "uuid", Nullable: true},
	{Name: "comp_id", Alias: "compId", Kind: "integer", Required: true},
	{Name: "bi_id", Alias: "biId", Kind: "integer", Nullable: true},
	{Name: "comment", Kind: "string", Nullable: true}, {Name: "hashtag", Kind: "string", Nullable: true},
	{Name: "is_positive", Alias: "isPositive", Kind: "boolean", Default: false},
}, Check: func(o platform.Object) string {
	o["exercise_session_key"] = strings.ToLower(pythonTrim(o.String("exercise_session_key")))
	if o.String("timeline_source") == "TIMELINE" {
		if o["client_report_id"] == nil {
			return "client_report_id is required for TIMELINE report"
		}
		if o["exercise_offset_ms"] == nil {
			return "exercise_offset_ms is required for TIMELINE report"
		}
		if o["assignment_event_id_at_observation"] == nil {
			return "assignment_event_id_at_observation is required for TIMELINE report"
		}
	}
	return ""
}}
var quickReferenceSchema = platform.Schema{Fields: []platform.Field{runtimeID("client_report_id", "clientReportId")}}
var finalizeBlockSchema = platform.Schema{Fields: []platform.Field{
	{Name: "assessment_id", Alias: "assessmentId", Kind: "integer", Required: true},
	{Name: "grades", Kind: "string_dictionary", Default: map[string]any{}},
	{Name: "mistake_reports", Alias: "mistakeReports", Kind: "list", Default: []any{}, Item: &platform.Field{Kind: "object", Schema: &mistakeReportSchema}},
	{Name: "unresolved_quick_comments", Alias: "unresolvedQuickComments", Kind: "list", Default: []any{}, Max: 1000, Item: &platform.Field{Kind: "object", Schema: &quickReferenceSchema}},
	{Name: "summary", Kind: "string", Nullable: true}, {Name: "result", Kind: "boolean", Nullable: true},
}}
var finalizeSchema = platform.Schema{Fields: []platform.Field{
	{Name: "training_id", Alias: "trainingId", Kind: "integer", GreaterThanZero: true, Nullable: true},
	{Name: "comment_contract_version", Alias: "commentContractVersion", Kind: "literal_integer", Choices: []string{"1"}, Nullable: true},
	{Name: "cm1", Kind: "object", Nullable: true, Schema: &finalizeBlockSchema},
	{Name: "cm2", Kind: "object", Nullable: true, Schema: &finalizeBlockSchema},
}}

// Preserve grade insertion order and explicit completion proof independently of
// typed validation. These affect report IDs and canonical case collisions.
func attachBlockWire(o platform.Object, raw json.RawMessage) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return err
	}
	grades := canonical.Grades{}
	if data, ok := fields["grades"]; ok {
		if err := json.Unmarshal(data, &grades); err != nil {
			return err
		}
	}
	o["ordered_grades"] = grades
	_, camel := fields["unresolvedQuickComments"]
	_, snake := fields["unresolved_quick_comments"]
	o["quick_proof_present"] = camel || snake
	return nil
}
func readAssessmentSchema(r *http.Request, schema platform.Schema) (platform.Object, error) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, 16*1024*1024+1))
	if err != nil {
		return nil, err
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	o, err := platform.ReadSchema(r, schema)
	if err != nil {
		return nil, err
	}
	var fields map[string]json.RawMessage
	if err = json.Unmarshal(raw, &fields); err != nil {
		return nil, err
	}
	for _, name := range []string{"cm1", "cm2"} {
		if block, ok := o[name].(platform.Object); ok {
			if err := attachBlockWire(block, fields[name]); err != nil {
				return nil, err
			}
		}
	}
	if blocks, ok := o["assessments"].([]any); ok && len(blocks) > 0 {
		var rawBlocks []json.RawMessage
		if err = json.Unmarshal(fields["assessments"], &rawBlocks); err != nil {
			return nil, err
		}
		for i, raw := range rawBlocks {
			if err := attachBlockWire(blocks[i].(platform.Object), raw); err != nil {
				return nil, err
			}
		}
	}
	return o, nil
}
func canonicalAssessment(o platform.Object) canonical.AssessmentBlock {
	b := canonical.AssessmentBlock{AssessmentID: o.Int("assessment_id"), Grades: o["ordered_grades"].(canonical.Grades), Summary: o.StringPtr("summary"), Result: runtimePtr[bool](o, "result")}
	for _, item := range o["mistake_reports"].([]any) {
		r := item.(platform.Object)
		b.MistakeReports = append(b.MistakeReports, canonical.MistakeReport{ClientReportID: runtimePtr[uuid.UUID](r, "client_report_id"), AssignmentEventIDAtObservation: runtimePtr[uuid.UUID](r, "assignment_event_id_at_observation"), TimelineSource: r.String("timeline_source"), ExerciseID: r.Int("exercise_id"), ExerciseOffsetSec: r.Int("exercise_offset_sec"), CompID: r.Int("comp_id"), Timestamp: r["timestamp"].(time.Time), ExerciseOffsetMS: runtimePtr[int64](r, "exercise_offset_ms"), BiID: runtimePtr[int64](r, "bi_id"), ExerciseSessionKey: r.String("exercise_session_key"), Comment: r.StringPtr("comment"), Hashtag: r.StringPtr("hashtag"), IsPositive: r.Bool("is_positive")})
	}
	for _, raw := range o["unresolved_quick_comments"].([]any) {
		b.UnresolvedQuickComments = append(b.UnresolvedQuickComments, raw.(platform.Object)["client_report_id"].(uuid.UUID))
	}
	return b
}
