package platform

import (
	"encoding/json"
	"testing"
)

func TestUnboundedDecimalKeepsExponentCompact(t *testing.T) {
	field := Field{Kind: "decimal", Decimal: &DecimalConstraints{Unbounded: true}}
	for _, test := range []struct {
		input any
		want  string
	}{
		{"1e999999999999999999", "1e999999999999999999"},
		{"1e-999999999999999999", "1e-999999999999999999"},
		{"-1.234567890123456789", "-1234567890123456789e-18"},
		{json.Number("0.100000000000000005"), "1e-1"},
	} {
		got, details := validateDecimal(test.input, []any{"body", "scoreNumeric"}, field)
		if len(details) != 0 || got != test.want {
			t.Fatalf("%v: got %v, details %v", test.input, got, details)
		}
	}
	field.GreaterThanZero = true
	for _, input := range []string{"0", "-0.0000", "-1e-999999999999999999"} {
		_, details := validateDecimal(input, nil, field)
		if len(details) != 1 || details[0].(map[string]any)["type"] != "greater_than" {
			t.Fatalf("%s must fail positive weight validation: %v", input, details)
		}
	}
	if _, details := validateDecimal("1e-999999999999999999", nil, field); len(details) != 0 {
		t.Fatalf("small positive weight must reach SQL without precision validation: %v", details)
	}
}
