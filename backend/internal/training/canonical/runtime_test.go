package canonical

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func id(number int) uuid.UUID {
	return uuid.MustParse(fmt.Sprintf("01900000-0000-7000-8000-%012d", number))
}
func ptr[T any](value T) *T { return &value }
func instant(value string) time.Time {
	v, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		panic(err)
	}
	return v
}
func expectHash(t *testing.T, payload map[string]any, expected string) {
	t.Helper()
	actual, err := SHA256(payload)
	if err != nil {
		t.Fatal(err)
	}
	if actual != expected {
		encoded, _ := JSON(payload)
		t.Fatalf("hash %s, want %s; JSON=%s", actual, expected, encoded)
	}
}

func TestRuntimeMatchesExistingDartPythonGoldens(t *testing.T) {
	// These constants verify the training wire format.
	create := TrainingCreate{ClientCreationID: ptr(id(2)), ScenarioDayModuleID: ptr(int64(11)), ScenarioID: ptr(int64(7)), CM1ID: 41, CM2ID: 42, WriterInstanceID: ptr(id(1)), Capabilities: &Capabilities{LiveCrewSwapVersions: []int64{1, 1}, OfflineDurabilityReady: true, TransactionalStore: "SQLITE"}}
	expectHash(t, CreatePayload(create), "00c9f3b2b545e00f39602c854efdc3d34c9bd7ee5da10c981ea285574da29390")
	initial := InitialPayload(1001, id(3), CrewMapping{501, 502})
	expectHash(t, initial, "6630e8e2d49cea87a04cc06ca01401fbcdeb6f216f542a872bf7c5d0d8eda2eb")
	swap := CrewEvent{ClientEventID: id(4), ClientSequence: 1, PreviousEventID: id(3), OccurredAt: instant("2026-07-11T10:05:10.123456Z"), Scope: "EXERCISE_RUN", RuntimeExerciseID: ptr(int64(7001)), ExerciseSessionKey: ptr(id(5)), ExerciseOffsetMS: ptr(int64(310000)), TimerState: "RUNNING", CM1AssessmentIDAfter: 502, CM2AssessmentIDAfter: 501}
	expectHash(t, SwapPayload(1001, id(1), 1, swap), "749a98d9f82c680af957f3ed3db3d38d1dfb1f0ba32c2451c7b7d60539790706")
	run := ExerciseRun{ExerciseSessionKey: id(5), RuntimeExerciseID: 7001, RunIndex: 1, Status: "COMPLETED", InitialAssignmentEventID: id(3), PlannedDurationMS: 1200000, ActiveDurationMS: 620000, StartedAt: ptr(instant("2026-07-11T10:00:00Z")), EndedAt: ptr(instant("2026-07-11T10:10:20Z")), ClientRevision: 9}
	expectHash(t, RunPayload(1001, id(1), 1, run), "7a608663a080529d7e3375891c44bb093d61787de83ff30050d3e087fc29a962")
	report := MistakeReport{ClientReportID: ptr(id(6)), TimelineSource: "TIMELINE", ExerciseID: 7001, Timestamp: instant("2026-07-11T10:05:10.123456Z"), ExerciseOffsetSec: 310, ExerciseOffsetMS: ptr(int64(310000)), ExerciseSessionKey: id(5).String(), AssignmentEventIDAtObservation: ptr(id(4)), CompID: 91, Comment: ptr("Unicode: Привет ✈"), Hashtag: ptr("#CRM"), IsPositive: true}
	manifest := SubmissionManifest{TrainingID: 1001, WriterInstanceID: id(1), WriterEpoch: 1, ExpectedCurrentEventID: id(4), ExpectedClientSequence: 1, CrewEventPayloadHashes: []string{"6630e8e2d49cea87a04cc06ca01401fbcdeb6f216f542a872bf7c5d0d8eda2eb", "749a98d9f82c680af957f3ed3db3d38d1dfb1f0ba32c2451c7b7d60539790706"}, TerminalRunHashes: []TerminalRunHash{{id(5), "7a608663a080529d7e3375891c44bb093d61787de83ff30050d3e087fc29a962"}}, AssessmentBlocks: []AssessmentBlock{{AssessmentID: 502, Grades: Grades{{" com ", " std "}}, Summary: ptr(""), Result: ptr(true)}, {AssessmentID: 501, Grades: Grades{{" com ", " std "}}, MistakeReports: []MistakeReport{report}, Summary: ptr("Summary"), Result: ptr(true)}}, SpeechSessionID: ptr(id(7)), SpeechLastChunkIndex: ptr(int64(3))}
	payload, err := ManifestPayload(manifest)
	if err != nil {
		t.Fatal(err)
	}
	expectHash(t, payload, "6c06b76a6ea72883de263449a2b59f8cf415143b7db2fd44b0a379792b73e5df")
	// Existing frozen submissions with speech fields must retain the old digest
	// even though the target application never starts speech processing.
	manifest.SpeechSessionID = nil
	manifest.SpeechLastChunkIndex = nil
	manifest.CommentContractVersion = ptr(int64(1))
	manifest.TerminalRunHashes = nil
	manifest.AssessmentBlocks[1].MistakeReports = nil
	payload, err = ManifestPayload(manifest)
	if err != nil {
		t.Fatal(err)
	}
	expectHash(t, payload, "92109faa998bb8cf8b2574649252f8e533247cc85fd2b09e78289b957b280d7b")
	catalog := map[string]any{"version": 1, "competencies": []map[string]any{{"id": 91, "code": "COM", "name": "Communication — Связь", "orderIndex": 0, "indicators": []map[string]any{{"id": 501, "code": "OB_1", "shortName": "Clear ✈", "name": "Communicates clearly", "orderIndex": 0}}}}}
	expectHash(t, catalog, "3d10e9bbc33bf7430d4b637515d9ac42237a7998e8355811cedc73ab75fe35d7")
}

func TestJSONMatchesIndependentPythonCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/json-python.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name      string          `json:"name"`
		Input     json.RawMessage `json:"input"`
		Canonical string          `json:"canonical"`
		Hash      string          `json:"hash"`
	}
	if err = json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for _, test := range cases {
		t.Run(test.Name, func(t *testing.T) {
			decoder := json.NewDecoder(strings.NewReader(string(test.Input)))
			decoder.UseNumber()
			var payload map[string]any
			if err := decoder.Decode(&payload); err != nil {
				t.Fatal(err)
			}
			actual, err := JSON(payload)
			if err != nil {
				t.Fatal(err)
			}
			if string(actual) != test.Canonical {
				t.Fatalf("got %s; want %s", actual, test.Canonical)
			}
			expectHash(t, payload, test.Hash)
		})
	}
}
func TestJSONPreservesValidatedWideIntegers(t *testing.T) {
	positive, _ := new(big.Int).SetString("1208925819614629174706176", 10)
	negative := new(big.Int).Neg(positive)
	actual, err := JSON(map[string]any{"ids": []any{positive, *negative, new(big.Int)}})
	if err != nil {
		t.Fatal(err)
	}
	if string(actual) != `{"ids":[1208925819614629174706176,-1208925819614629174706176,0]}` {
		t.Fatalf("wide snapshot IDs lost their exact integer representation: %s", actual)
	}
}

func TestCanonicalRejectsInvalidValuesAndRetainsGradeOrder(t *testing.T) {
	for _, value := range []any{math.NaN(), math.Inf(1), string([]byte{0xff}), map[int]string{1: "x"}, time.Now()} {
		if _, err := JSON(map[string]any{"value": value}); err == nil {
			t.Fatalf("accepted unsupported value %T", value)
		}
	}
	var grades Grades
	for _, invalid := range []string{`{"COM":null}`, `{"COM":1}`, `{"COM":true}`} {
		if err := json.Unmarshal([]byte(invalid), &grades); err == nil {
			t.Fatalf("accepted invalid grade value: %s", invalid)
		}
	}
	if err := json.Unmarshal([]byte(`{" com ":"low","COM":"high"," com ":"updated"}`), &grades); err != nil {
		t.Fatal(err)
	}
	block, err := BlockPayload(AssessmentBlock{AssessmentID: 1, Grades: grades}, false)
	if err != nil {
		t.Fatal(err)
	}
	if block["grades"].(map[string]string)["COM"] != "HIGH" {
		t.Fatal("lost Python insertion-order collision semantics")
	}
	if ValidateExactSwap(CrewMapping{1, 2}, CrewMapping{2, 1}) != nil {
		t.Fatal("valid swap rejected")
	}
	if ValidateExactSwap(CrewMapping{1, 2}, CrewMapping{1, 2}) == nil {
		t.Fatal("non-swap accepted")
	}
}
