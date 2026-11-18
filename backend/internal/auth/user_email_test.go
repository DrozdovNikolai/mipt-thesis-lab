package auth

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"north55/backend/internal/platform"
)

func TestUserEmailPythonOracle(t *testing.T) {
	data, err := os.ReadFile("testdata/user_email_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []map[string]any `json:"cases"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, test := range fixture.Cases {
		label, _ := json.Marshal(test["input"])
		t.Run(string(label), func(t *testing.T) {
			body, err := platform.ValidateObject(map[string]any{"email": test["input"]}, nil, platform.Schema{Fields: []platform.Field{userEmailField(true)}})
			if expected, ok := test["normalized"]; ok {
				if err != nil {
					t.Fatal(err)
				}
				if body["email"] != expected {
					t.Fatalf("normalized %q; want %q", body["email"], expected)
				}
				return
			}
			if err == nil {
				t.Fatal("accepted invalid Python email", body)
			}
			validation, ok := err.(*platform.APIError)
			if !ok {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(validation.Extra["details"])
			if err != nil {
				t.Fatal(err)
			}
			var got any
			if err := json.Unmarshal(encoded, &got); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, test["errors"]) {
				t.Fatalf("details %s; want %#v", encoded, test["errors"])
			}
		})
	}
}
