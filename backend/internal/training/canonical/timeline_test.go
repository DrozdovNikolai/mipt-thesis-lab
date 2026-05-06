package canonical

import "testing"

func TestSameOffsetSwapsPreserveLatestSegmentIdentity(t *testing.T) {
	initial := CrewMapping{501, 502}
	events := []CrewEventProjection{{id(4), 2, 2500, initial}, {id(3), 1, 2500, initial.Swapped()}, {id(5), 3, 2500, initial.Swapped()}}
	segments, err := BuildCrewSegments(5000, ptr(1), id(2), initial, events)
	if err != nil {
		t.Fatal(err)
	}
	if len(segments) != 2 {
		t.Fatalf("got %d segments", len(segments))
	}
	if segments[0].Mapping != initial || segments[0].FromOffsetMS != 0 || segments[0].ToOffsetMS != 2500 || segments[0].StartsAfterEventID != id(2) {
		t.Fatalf("first segment %+v", segments[0])
	}
	if segments[1].Mapping != initial.Swapped() || segments[1].FromOffsetMS != 2500 || segments[1].ToOffsetMS != 5000 || segments[1].StartsAfterEventID != id(5) || *segments[1].PFAssessmentID != 502 {
		t.Fatalf("final segment %+v", segments[1])
	}
	if events[0].EventID != id(4) {
		t.Fatal("caller events mutated")
	}
}
func TestCrewSegmentsRejectCorruptSequenceAndCoverWholeRun(t *testing.T) {
	initial := CrewMapping{1, 2}
	for _, events := range [][]CrewEventProjection{
		{{id(1), 1, 2500, initial}},
		{{id(1), 1, 6000, initial.Swapped()}},
		{{id(1), 1, 2500, initial.Swapped()}, {id(2), 2, 2400, initial}},
	} {
		if _, err := BuildCrewSegments(5000, nil, id(3), initial, events); err == nil {
			t.Fatal("accepted corrupt timeline")
		}
	}
	empty, err := BuildCrewSegments(0, nil, id(1), initial, nil)
	if err != nil || len(empty) != 0 {
		t.Fatalf("zero duration: %v %v", empty, err)
	}
	single, err := BuildCrewSegments(5000, nil, id(1), initial, nil)
	if err != nil || len(single) != 1 || single[0].ToOffsetMS != 5000 || single[0].PFAssessmentID != nil {
		t.Fatalf("single segment: %+v %v", single, err)
	}
}
