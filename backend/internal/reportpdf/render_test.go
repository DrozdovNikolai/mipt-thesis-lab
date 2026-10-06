package reportpdf

import (
	"bytes"
	"fmt"
	"strings"
	"sync"
	"testing"
)

func TestRenderNarrowGradeColumns(t *testing.T) {
	// A narrow column can fit a single glyph until padding consumes its printable width.
	for _, count := range []int{30, 40, 50, 55, 58, 60, 65, 120} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			report := Report{Title: "Narrow grade columns"}
			for i := 0; i < count; i++ {
				report.Grades = append(report.Grades, Grade{ID: int64(i + 1), Code: "W", Label: "1"})
			}
			data, err := Render(report)
			if count >= 60 {
				if err == nil {
					t.Fatal("expected an unprintable column error")
				}
				return
			}
			if err != nil || !bytes.HasPrefix(data, []byte("%PDF-")) {
				t.Fatalf("expected a readable PDF: %v", err)
			}
		})
	}
}

func TestRenderUnprintableRow(t *testing.T) {
	_, err := Render(Report{Title: "Oversized summary", Summary: strings.Repeat("Long summary text. ", 3000)})
	if err == nil {
		t.Fatal("expected an oversized row error")
	}
}

func TestRenderConcurrentRequests(t *testing.T) {
	report := Report{Title: "Тренировка — Unicode", Trainee: Person{Name: "Иван Пилот", Signature: []byte("invalid signature")},
		Comments: []Comment{{CompetenceCode: "COM", Positive: true, Text: "Crew coordination & workload management"}}}
	var group sync.WaitGroup
	for i := 0; i < 8; i++ {
		group.Add(1)
		go func(i int) {
			defer group.Done()
			data, err := Render(report)
			if err != nil || !bytes.HasPrefix(data, []byte("%PDF-")) {
				t.Errorf("request %d: %v", i, err)
			}
		}(i)
	}
	group.Wait()
}
