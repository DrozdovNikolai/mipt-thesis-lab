package platform

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"sync"
	"testing"
	"time"
)

func TestApplicationLoggerMatchesFrozenFormatter(t *testing.T) {
	raw, err := os.ReadFile("testdata/logging_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Levels []struct {
			Input    string
			Accepted bool
			Value    int
		}
		JSON  map[string]any
		Local string
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	for _, vector := range oracle.Levels {
		logger, err := NewApplicationLogger(&bytes.Buffer{}, vector.Input, false)
		if (err == nil) != vector.Accepted {
			t.Fatalf("LOG_LEVEL %q accepted=%v want %v", vector.Input, err == nil, vector.Accepted)
		}
		if err == nil {
			for _, level := range []struct {
				goValue     slog.Level
				pythonValue int
			}{{-4, 10}, {0, 20}, {4, 30}, {8, 40}, {12, 50}} {
				if got := logger.Enabled(context.Background(), level.goValue); got != (level.pythonValue >= vector.Value) {
					t.Fatalf("LOG_LEVEL %q threshold mismatch at %d", vector.Input, level.pythonValue)
				}
			}
		}
	}
	// Oracle local formatting uses the UTC clock in the pinned container.
	oldLocation := time.Local
	time.Local = time.UTC
	defer func() { time.Local = oldLocation }()
	for _, local := range []bool{false, true} {
		var output bytes.Buffer
		logger, err := NewApplicationLogger(&output, "INFO", local)
		if err != nil {
			t.Fatal(err)
		}
		record := slog.NewRecord(time.Date(2026, 1, 2, 3, 4, 5, 123456000, time.UTC), slog.LevelInfo, "Проверка — test", 0)
		record.Add("logger", "north55.test", "request_id", "req-1", "user_id", nil, "method", "GET", "path", "/api/users/me", "status_code", 200, "duration_ms", 1.25, "action", "auth.login", "session_id", "omitted", "training_id", 50, "unexpected", "omitted")
		if err := logger.Handler().Handle(context.Background(), record); err != nil {
			t.Fatal(err)
		}
		if local {
			if output.String() != oracle.Local+"\n" {
				t.Fatalf("local output %q want %q", output.String(), oracle.Local+"\n")
			}
		} else {
			var got map[string]any
			if err := json.Unmarshal(output.Bytes(), &got); err != nil {
				t.Fatal(err)
			}
			expected, _ := json.Marshal(oracle.JSON)
			actual, _ := json.Marshal(got)
			if !bytes.Equal(expected, actual) {
				t.Fatalf("JSON output %s want %s", actual, expected)
			}
		}
	}
}

func TestApplicationLoggerConcurrentRecords(t *testing.T) {
	var output bytes.Buffer
	logger, err := NewApplicationLogger(&output, "INFO", false)
	if err != nil {
		t.Fatal(err)
	}
	var workers sync.WaitGroup
	for i := 0; i < 100; i++ {
		workers.Add(1)
		go func(id int) {
			defer workers.Done()
			logger.With("training_id", id).Info("Accepted")
		}(i)
	}
	workers.Wait()
	decoder := json.NewDecoder(&output)
	seen := map[int]bool{}
	for decoder.More() {
		var record struct {
			TrainingID int `json:"training_id"`
			Message    string
		}
		if err := decoder.Decode(&record); err != nil {
			t.Fatal(err)
		}
		if record.Message != "Accepted" || seen[record.TrainingID] {
			t.Fatal("corrupted concurrent record", record)
		}
		seen[record.TrainingID] = true
	}
	if len(seen) != 100 {
		t.Fatal("missing records", len(seen))
	}
}
