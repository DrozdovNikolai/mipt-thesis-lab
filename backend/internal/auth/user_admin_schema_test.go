package auth

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"reflect"
	"testing"
	"time"

	"north55/backend/internal/platform"
)

func TestUserSchemaPythonOracle(t *testing.T) {
	file, err := os.Open("testdata/user_schema_python.json")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	var data struct {
		Cases []struct {
			Model  string         `json:"model"`
			Input  any            `json:"input"`
			Value  map[string]any `json:"value"`
			Errors []any          `json:"errors"`
		} `json:"cases"`
	}
	decoder := json.NewDecoder(file)
	decoder.UseNumber()
	if err := decoder.Decode(&data); err != nil {
		t.Fatal(err)
	}
	for i, test := range data.Cases {
		t.Run(fmt.Sprintf("%s/%d", test.Model, i), func(t *testing.T) {
			model := userAdminSchema(test.Model == "UserCreate")
			if test.Model == "UserRolesUpdate" {
				model = platform.Schema{Fields: []platform.Field{{Name: "role_ids", Alias: "roleIds", Kind: "list", Required: true, Item: &platform.Field{Kind: "uuid"}}}}
			}
			value, err := platform.ValidateObject(test.Input, []any{}, model)
			var got, want any
			if test.Errors != nil {
				if err == nil {
					t.Fatal("accepted invalid input", test.Input)
				}
				validation, ok := err.(*platform.APIError)
				if !ok {
					t.Fatal(err)
				}
				response := httptest.NewRecorder()
				platform.WriteError(response, validation)
				var wire struct {
					Error struct {
						Details []any `json:"details"`
					} `json:"error"`
				}
				if err := json.Unmarshal(response.Body.Bytes(), &wire); err != nil {
					t.Fatal(err)
				}
				got, want = wire.Error.Details, test.Errors
			} else {
				if err != nil {
					t.Fatal(test.Input, err)
				}
				for key, item := range value {
					if date, ok := item.(time.Time); ok {
						value[key] = date.Format("2006-01-02")
					}
				}
				got, want = value, test.Value
			}
			canonical := func(v any) any {
				b, e := json.Marshal(v)
				if e != nil {
					t.Fatal(e)
				}
				var out any
				if e = json.Unmarshal(b, &out); e != nil {
					t.Fatal(e)
				}
				return out
			}
			if !reflect.DeepEqual(canonical(got), canonical(want)) {
				a, _ := json.Marshal(got)
				b, _ := json.Marshal(want)
				t.Fatalf("input %v\ngot %s\nwant %s", test.Input, a, b)
			}
		})
	}
}
