package training

import (
	"testing"
	"time"
)

func TestCommanderAgeDateBoundaries(t *testing.T) {
	for _, test := range []struct {
		day   string
		years int64
		want  string
	}{
		{"2024-02-29", 1, "2023-02-28"}, {"2024-02-29", 4, "2020-02-29"},
		{"2025-03-01", 1, "2024-03-01"}, {"2024-02-29", 0, "2024-02-29"},
		{"2026-09-15", 40, "1986-09-15"},
	} {
		day, _ := time.Parse("2006-01-02", test.day)
		got, err := commanderSubtractYears(day, test.years)
		if err != nil || got.Format("2006-01-02") != test.want {
			t.Fatalf("%s minus %d: %s, %v", test.day, test.years, got, err)
		}
	}
	day, _ := time.Parse("2006-01-02", "2024-02-29")
	if _, err := commanderSubtractYears(day, 2024); err == nil {
		t.Fatal("year zero must fail like Python date")
	}
}
