package training

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

func TestPerformanceNumbersMatchFrozenPython(t *testing.T) {
	raw, err := os.ReadFile("testdata/performance_numbers_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Vectors []struct {
			Kind   string
			Args   []any
			Value  string
			Error  string
			SHA256 string
			Length int
		}
	}
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	for i, vector := range fixture.Vectors {
		t.Run(fmt.Sprintf("%s/%d", vector.Kind, i), func(t *testing.T) {
			arg := func(i int) string { value, _ := vector.Args[i].(string); return value }
			var value string
			var err error
			switch vector.Kind {
			case "signed":
				value = formatSigned(arg(0))
			case "wind":
				value = formatWind(arg(0), arg(1), arg(2))
			case "clouds":
				value = formatClouds(arg(0), vector.Args[1])
			case "weight":
				value, err = formatGrossWeight(arg(0), arg(1))
			default:
				t.Fatal("unknown oracle kind")
			}
			if vector.Error != "" {
				if err == nil {
					t.Fatalf("expected %s for %v, got %q", vector.Error, vector.Args, value)
				}
				return
			}
			if err != nil {
				t.Fatalf("%v: %v", vector.Args, err)
			}
			if vector.SHA256 != "" {
				if len(value) != vector.Length || fmt.Sprintf("%x", sha256.Sum256([]byte(value))) != vector.SHA256 {
					t.Fatalf("long result mismatch for %v; length %d expected %d", vector.Args, len(value), vector.Length)
				}
			} else if value != vector.Value {
				t.Fatalf("%v: got %q expected %q", vector.Args, value, vector.Value)
			}
		})
	}
}
