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
