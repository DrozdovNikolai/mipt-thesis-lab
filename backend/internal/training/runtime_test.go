package training

import (
	"net/http/httptest"
	"strings"
	"testing"

	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

func TestRuntimeEntitlementRequiresDurabilityVersionAndAirline(t *testing.T) {
	cfg := platform.Config{LiveCrewSwapEnabled: true, LiveCrewSwapVersion: 1}
	capability := canonical.Capabilities{OfflineDurabilityReady: true, TransactionalStore: "INDEXED_DB", LiveCrewSwapVersions: []int64{1}}
	for _, test := range []struct {
		name, allowlist, store string
		enabled, durable       bool
		versions               []int64
		want                   bool
	}{
		{"defaults", "", "INDEXED_DB", true, true, []int64{1}, true},
		{"allowed", " 1, 2 ", "SQLITE", true, true, []int64{1}, true},
		{"other airline", "2", "SQLITE", true, true, []int64{1}, false},
		{"invalid allowlist fails closed", "1,invalid", "SQLITE", true, true, []int64{1}, false},
		{"flag disabled", "", "SQLITE", false, true, []int64{1}, false},
		{"durability missing", "", "SQLITE", true, false, []int64{1}, false},
		{"no transactional store", "", "NONE", true, true, []int64{1}, false},
		{"version unsupported", "", "SQLITE", true, true, []int64{2}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			local := cfg
			local.LiveCrewSwapEnabled = test.enabled
			local.LiveCrewSwapAirlineIDs = test.allowlist
			c := capability
			c.TransactionalStore = test.store
			c.OfflineDurabilityReady = test.durable
			c.LiveCrewSwapVersions = test.versions
			s := Service{Auth: &auth.Service{Config: local}}
			if got := s.runtimeEntitled(1, c); got != test.want {
				t.Fatalf("entitlement=%v want=%v", got, test.want)
			}
		})
	}
}

func TestWriterEpochDoesNotOverflowDuringValidation(t *testing.T) {
	request := httptest.NewRequest("POST", "/", strings.NewReader(`{"newWriterInstanceId":"01900000-0000-7000-8000-000000000100","expectedWriterEpoch":18446744073709551616,"explicitConfirmation":true}`))
	object, err := platform.ReadSchema(request, runtimeTakeoverSchema)
	if err != nil {
		t.Fatal(err)
	}
	if object.CompareInteger("expected_writer_epoch", 1) <= 0 {
		t.Fatal("unbounded epoch lost precision")
	}
	request = httptest.NewRequest("POST", "/", strings.NewReader(`{"newWriterInstanceId":"01900000-0000-7000-8000-000000000100","expectedWriterEpoch":-18446744073709551616,"explicitConfirmation":true}`))
	if _, err = platform.ReadSchema(request, runtimeTakeoverSchema); err == nil {
		t.Fatal("negative epoch accepted")
	}
}
