package auth

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"github.com/google/uuid"
)

func TestMissingRoleUUIDsPythonOracle(t *testing.T) {
	data, err := os.ReadFile("testdata/user_role_sets_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			IDs     []uuid.UUID `json:"ids"`
			Found   []uuid.UUID `json:"found"`
			Missing []string    `json:"missing"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for i, test := range fixture.Cases {
		found := map[uuid.UUID]bool{}
		for _, id := range test.Found {
			found[id] = true
		}
		if actual := userMissingRoleIDs(test.IDs, found); !reflect.DeepEqual(actual, test.Missing) {
			t.Fatalf("case %d: got %v, want %v", i, actual, test.Missing)
		}
	}
}
