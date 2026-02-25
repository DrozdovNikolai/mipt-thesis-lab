package platform

import (
	"encoding/json"
	"testing"
)

func TestDocsFrozenUnicodeSemantics(t *testing.T) {
	raw, err := apiDocumentation.ReadFile("assets/docs-unicode.json")
	if err != nil {
		t.Fatal(err)
	}
	var value struct {
		Vectors []struct{ Prefix, Operation, Title string }
	}
	if err := json.Unmarshal(raw, &value); err != nil {
		t.Fatal(err)
	}
	for _, vector := range value.Vectors {
		id := "read_" + openAPISanitize("/"+vector.Prefix+"/items/{id}") + "_get"
		if id != vector.Operation || openAPIResponseTitle(id) != vector.Title {
			t.Fatalf("prefix %q: id=%q title=%q want id=%q title=%q", vector.Prefix, id, openAPIResponseTitle(id), vector.Operation, vector.Title)
		}
	}
}
