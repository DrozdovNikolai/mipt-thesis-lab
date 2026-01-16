package platform

import "testing"

func TestLegacyContractOptionalBoolean(t *testing.T) {
	for _, tc := range []struct {
		value                     string
		nilValue, result, invalid bool
	}{
		{"", true, false, false}, {" \u00a0\x1c", true, false, false}, {"true", false, true, false}, {"YeS", false, true, false}, {"ON", false, true, false}, {"0", false, false, false}, {"false", false, false, false}, {"n", false, false, false}, {" true ", false, false, true}, {"2", false, false, true},
	} {
		t.Run(tc.value, func(t *testing.T) {
			value, err := configOptionalBool(tc.value)
			if (err != nil) != tc.invalid {
				t.Fatalf("error: %v", err)
			}
			if tc.invalid {
				return
			}
			if (value == nil) != tc.nilValue || (value != nil && *value != tc.result) {
				t.Fatalf("wrong optional bool: %v", value)
			}
		})
	}
}

func TestLegacyContractAndMediaConfiguration(t *testing.T) {
	for _, environment := range []string{"prod", "test", "local"} {
		t.Run(environment, func(t *testing.T) {
			t.Setenv("ENVIRONMENT", environment)
			t.Setenv("SCENARIO_REQUIRE_LEGACY_CONTENT_CONTRACT", "")
			t.Setenv("FILE_STORAGE_BACKEND", "local")
			t.Setenv("MEDIA_EXERCISE_IMAGE_MAX_FILES", "20")
			t.Setenv("MEDIA_EXERCISE_IMAGE_MAX_FILE_BYTES", "10485760")
			t.Setenv("MEDIA_SCENARIO_PDF_MAX_FILES", "20")
			t.Setenv("MEDIA_SCENARIO_PDF_MAX_FILE_BYTES", "52428800")
			c, err := LoadConfig()
			if err != nil {
				t.Fatal(err)
			}
			if c.ScenarioRequireLegacyContentContract != nil || c.MediaExerciseImageMaxFiles != 20 || c.MediaExerciseImageMaxFileBytes != 10485760 {
				t.Fatalf("unexpected config: %+v", c)
			}
			if c.MediaScenarioPDFMaxFiles != 20 || c.MediaScenarioPDFMaxFileBytes != 52428800 || c.MediaScenarioPDFMaxFilesText != "20" || c.MediaScenarioPDFMaxFileBytesText != "52428800" {
				t.Fatal("PDF defaults or configured spelling lost")
			}
			t.Setenv("SCENARIO_REQUIRE_LEGACY_CONTENT_CONTRACT", "off")
			t.Setenv("MEDIA_EXERCISE_IMAGE_MAX_FILES", "2.0")
			t.Setenv("MEDIA_EXERCISE_IMAGE_MAX_FILE_BYTES", "999999999999999999999999999999")
			c, err = LoadConfig()
			if err != nil {
				t.Fatal(err)
			}
			if c.ScenarioRequireLegacyContentContract == nil || *c.ScenarioRequireLegacyContentContract || c.MediaExerciseImageMaxFiles != 2 || c.MediaExerciseImageMaxFileBytes != 9223372036854775807 {
				t.Fatal("explicit override or wide limit lost")
			}
			if c.MediaExerciseImageMaxFilesText != "2" || c.MediaExerciseImageMaxFileBytesText != "999999999999999999999999999999" {
				t.Fatal("canonical configured limits lost")
			}
			t.Setenv("MEDIA_EXERCISE_IMAGE_MAX_FILE_BYTES", "-999999999999999999999999999999")
			c, err = LoadConfig()
			if err != nil || c.MediaExerciseImageMaxFileBytes != -9223372036854775808 || c.MediaExerciseImageMaxFileBytesText != "-999999999999999999999999999999" {
				t.Fatal("negative limit spelling or effective bound lost", err)
			}
			t.Setenv("MEDIA_SCENARIO_PDF_MAX_FILES", "0")
			t.Setenv("MEDIA_SCENARIO_PDF_MAX_FILE_BYTES", "999999999999999999999999999999")
			c, err = LoadConfig()
			if err != nil || c.MediaScenarioPDFMaxFiles != 0 || c.MediaScenarioPDFMaxFileBytes != 9223372036854775807 || c.MediaScenarioPDFMaxFileBytesText != "999999999999999999999999999999" {
				t.Fatal("PDF limits lost", err)
			}
		})
	}
}
