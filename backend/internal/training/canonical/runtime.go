package canonical

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
)

func decimal(value int64) string { return strconv.FormatInt(value, 10) }
func optionalDecimal(value *int64) any {
	if value == nil {
		return nil
	}
	return decimal(*value)
}
func optionalUUID(value *uuid.UUID) any {
	if value == nil {
		return nil
	}
	return value.String()
}
func timestamp(value *time.Time) any {
	if value == nil {
		return nil
	}
	v := value.UTC()
	return fmt.Sprintf("%d-%02d-%02dT%02d:%02d:%02d.%03dZ", v.Year(), v.Month(), v.Day(), v.Hour(), v.Minute(), v.Second(), v.Nanosecond()/1_000_000)
}
func upper(value string) string { return cases.Upper(language.Und).String(strings.TrimSpace(value)) }
func versions(values []int64) []string {
	unique := map[int64]bool{}
	for _, v := range values {
		unique[v] = true
	}
	sorted := make([]int64, 0, len(unique))
	for v := range unique {
		sorted = append(sorted, v)
	}
	sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })
	out := make([]string, 0, len(sorted))
	for _, v := range sorted {
		out = append(out, decimal(v))
	}
	return out
}

type CrewMapping struct{ CM1AssessmentID, CM2AssessmentID int64 }

func (m CrewMapping) Validate() error {
	if m.CM1AssessmentID <= 0 || m.CM2AssessmentID <= 0 {
		return fmt.Errorf("assessment IDs must be positive")
	}
	if m.CM1AssessmentID == m.CM2AssessmentID {
		return fmt.Errorf("crew mapping assessment IDs must differ")
	}
	return nil
}
func (m CrewMapping) Swapped() CrewMapping { return CrewMapping{m.CM2AssessmentID, m.CM1AssessmentID} }
func ValidateExactSwap(previous, next CrewMapping) error {
	if err := previous.Validate(); err != nil {
		return err
	}
	if err := next.Validate(); err != nil {
		return err
	}
	if next != previous.Swapped() {
		return fmt.Errorf("next crew mapping is not an exact swap")
	}
	return nil
}

type Capabilities struct {
	LiveCrewSwapVersions, QuickCommentVersions []int64
	OfflineDurabilityReady                     bool
	TransactionalStore                         string
}
type TrainingCreate struct {
	ClientCreationID, WriterInstanceID *uuid.UUID
	ScenarioDayModuleID, ScenarioID    *int64
	CM1ID, CM2ID                       int64
	Capabilities                       *Capabilities
}

func CreatePayload(input TrainingCreate) map[string]any {
	var capabilityPayload any
	if c := input.Capabilities; c != nil {
		payload := map[string]any{"liveCrewSwapVersions": versions(c.LiveCrewSwapVersions), "offlineDurabilityReady": c.OfflineDurabilityReady, "transactionalStore": c.TransactionalStore}
		if len(c.QuickCommentVersions) > 0 {
			payload["quickCommentVersions"] = versions(c.QuickCommentVersions)
		}
		capabilityPayload = payload
	}
	return map[string]any{"clientCreationId": optionalUUID(input.ClientCreationID), "cm1Id": decimal(input.CM1ID), "cm2Id": decimal(input.CM2ID), "runtimeClientCapabilities": capabilityPayload, "scenarioDayModuleId": optionalDecimal(input.ScenarioDayModuleID), "scenarioId": optionalDecimal(input.ScenarioID), "schemaVersion": "1", "writerInstanceId": optionalUUID(input.WriterInstanceID)}
}
func InitialPayload(trainingID int64, eventID uuid.UUID, mapping CrewMapping) map[string]any {
	return map[string]any{"clientSequence": "0", "cm1AssessmentIdAfter": decimal(mapping.CM1AssessmentID), "cm2AssessmentIdAfter": decimal(mapping.CM2AssessmentID), "eventId": eventID.String(), "kind": "CREW_ASSIGNMENT_INITIAL", "schemaVersion": "1", "trainingId": decimal(trainingID), "writerEpoch": "0"}
}

type CrewEvent struct {
	ClientEventID, PreviousEventID             uuid.UUID
	ClientSequence                             int64
	OccurredAt                                 time.Time
	Scope, TimerState                          string
	RuntimeExerciseID, ExerciseOffsetMS        *int64
	ExerciseSessionKey                         *uuid.UUID
	CM1AssessmentIDAfter, CM2AssessmentIDAfter int64
}

func SwapPayload(trainingID int64, writerID uuid.UUID, epoch int64, event CrewEvent) map[string]any {
	return map[string]any{"clientEventId": event.ClientEventID.String(), "clientSequence": decimal(event.ClientSequence), "cm1AssessmentIdAfter": decimal(event.CM1AssessmentIDAfter), "cm2AssessmentIdAfter": decimal(event.CM2AssessmentIDAfter), "exerciseOffsetMs": optionalDecimal(event.ExerciseOffsetMS), "exerciseSessionKey": optionalUUID(event.ExerciseSessionKey), "kind": "CREW_ASSIGNMENT_EVENT", "occurredAt": timestamp(&event.OccurredAt), "previousEventId": event.PreviousEventID.String(), "runtimeExerciseId": optionalDecimal(event.RuntimeExerciseID), "schemaVersion": "1", "scope": event.Scope, "timerState": event.TimerState, "trainingId": decimal(trainingID), "writerEpoch": decimal(epoch), "writerInstanceId": writerID.String()}
}

type ExerciseRun struct {
	ExerciseSessionKey, InitialAssignmentEventID                                     uuid.UUID
	RuntimeExerciseID, RunIndex, PlannedDurationMS, ActiveDurationMS, ClientRevision int64
	Status                                                                           string
	StartedAt, EndedAt                                                               *time.Time
}

func RunPayload(trainingID int64, writerID uuid.UUID, epoch int64, run ExerciseRun) map[string]any {
	return map[string]any{"activeDurationMs": decimal(run.ActiveDurationMS), "clientRevision": decimal(run.ClientRevision), "endedAt": timestamp(run.EndedAt), "exerciseSessionKey": run.ExerciseSessionKey.String(), "initialAssignmentEventId": run.InitialAssignmentEventID.String(), "kind": "EXERCISE_RUN_SNAPSHOT", "plannedDurationMs": decimal(run.PlannedDurationMS), "runIndex": decimal(run.RunIndex), "runtimeExerciseId": decimal(run.RuntimeExerciseID), "schemaVersion": "1", "startedAt": timestamp(run.StartedAt), "status": run.Status, "trainingId": decimal(trainingID), "writerEpoch": decimal(epoch), "writerInstanceId": writerID.String()}
}

type MistakeReport struct {
	ClientReportID, AssignmentEventIDAtObservation *uuid.UUID
	TimelineSource                                 string
	ExerciseID, ExerciseOffsetSec, CompID          int64
	Timestamp                                      time.Time
	ExerciseOffsetMS, BiID                         *int64
	ExerciseSessionKey                             string
	Comment, Hashtag                               *string
	IsPositive                                     bool
}

func ReportPayload(report MistakeReport) map[string]any {
	return map[string]any{"assignmentEventIdAtObservation": optionalUUID(report.AssignmentEventIDAtObservation), "biId": optionalDecimal(report.BiID), "clientReportId": optionalUUID(report.ClientReportID), "comment": report.Comment, "compId": decimal(report.CompID), "exerciseId": decimal(report.ExerciseID), "exerciseOffsetMs": optionalDecimal(report.ExerciseOffsetMS), "exerciseOffsetSec": decimal(report.ExerciseOffsetSec), "exerciseSessionKey": strings.ToLower(report.ExerciseSessionKey), "hashtag": report.Hashtag, "isPositive": report.IsPositive, "timelineSource": report.TimelineSource, "timestamp": timestamp(&report.Timestamp)}
}

type GradeEntry struct{ Code, Value string }

// Grades retain JSON object insertion order for case-normalization collisions.
type Grades []GradeEntry

func (g *Grades) UnmarshalJSON(data []byte) error {
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	token, err := decoder.Token()
	if err != nil || token != json.Delim('{') {
		return fmt.Errorf("grades must be an object")
	}
	out := Grades{}
	indices := map[string]int{}
	for decoder.More() {
		token, err = decoder.Token()
		if err != nil {
			return err
		}
		key, ok := token.(string)
		if !ok {
			return fmt.Errorf("invalid grade key")
		}
		var value *string
		if err = decoder.Decode(&value); err != nil {
			return err
		}
		if value == nil {
			return fmt.Errorf("grade value must be a string")
		}
		if index, exists := indices[key]; exists {
			out[index].Value = *value
		} else {
			indices[key] = len(out)
			out = append(out, GradeEntry{key, *value})
		}
	}
	if _, err = decoder.Token(); err != nil {
		return err
	}
	*g = out
	return nil
}

type AssessmentBlock struct {
	AssessmentID            int64
	Grades                  Grades
	MistakeReports          []MistakeReport
	UnresolvedQuickComments []uuid.UUID
	Summary                 *string
	Result                  *bool
}
