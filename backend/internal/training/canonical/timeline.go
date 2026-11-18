package canonical

import (
	"fmt"
	"sort"

	"github.com/google/uuid"
)

type CrewEventProjection struct {
	EventID                          uuid.UUID
	ServerRevision, ExerciseOffsetMS int64
	MappingAfter                     CrewMapping
}
type CrewSegment struct {
	SegmentIndex                   int
	FromOffsetMS, ToOffsetMS       int64
	Mapping                        CrewMapping
	PFAssessmentID, PMAssessmentID *int64
	StartsAfterEventID             uuid.UUID
}

func ReplayAssignment(initial CrewMapping, after []CrewMapping) (CrewMapping, error) {
	if err := initial.Validate(); err != nil {
		return CrewMapping{}, err
	}
	current := initial
	for _, next := range after {
		if err := ValidateExactSwap(current, next); err != nil {
			return CrewMapping{}, err
		}
		current = next
	}
	return current, nil
}
func BuildCrewSegments(duration int64, pfSlot *int, initialEventID uuid.UUID, initial CrewMapping, events []CrewEventProjection) ([]CrewSegment, error) {
	if duration < 0 {
		return nil, fmt.Errorf("active_duration_ms must be non-negative")
	}
	if pfSlot != nil && *pfSlot != 1 && *pfSlot != 2 {
		return nil, fmt.Errorf("planned_pf_slot must be 1, 2 or None")
	}
	if err := initial.Validate(); err != nil {
		return nil, err
	}
	ordered := append([]CrewEventProjection{}, events...)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].ServerRevision < ordered[j].ServerRevision })
	segments := []CrewSegment{}
	mapping := initial
	source := initialEventID
	cursor := int64(0)
	appendSegment := func(end int64) {
		segment := CrewSegment{SegmentIndex: len(segments), FromOffsetMS: cursor, ToOffsetMS: end, Mapping: mapping, StartsAfterEventID: source}
		if pfSlot != nil {
			pf, pm := mapping.CM1AssessmentID, mapping.CM2AssessmentID
			if *pfSlot == 2 {
				pf, pm = pm, pf
			}
			segment.PFAssessmentID = &pf
			segment.PMAssessmentID = &pm
		}
		segments = append(segments, segment)
	}
	for _, event := range ordered {
		boundary := event.ExerciseOffsetMS
		if boundary < cursor {
			return nil, fmt.Errorf("crew event offsets must be non-decreasing")
		}
		if boundary > duration {
			return nil, fmt.Errorf("crew event offset exceeds final run duration")
		}
		if boundary > cursor {
			appendSegment(boundary)
		}
		if err := ValidateExactSwap(mapping, event.MappingAfter); err != nil {
			return nil, err
		}
		mapping = event.MappingAfter
		source = event.EventID
		cursor = boundary
	}
	if cursor < duration {
		appendSegment(duration)
	}
	covered := int64(0)
	for _, segment := range segments {
		covered += segment.ToOffsetMS - segment.FromOffsetMS
	}
	if covered != duration {
		return nil, fmt.Errorf("crew segment projection does not cover the run")
	}
	return segments, nil
}
