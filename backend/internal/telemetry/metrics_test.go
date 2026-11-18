package telemetry

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"

	dto "github.com/prometheus/client_model/go"
	"github.com/prometheus/common/expfmt"
	"github.com/prometheus/common/model"
)

func exported(t *testing.T, m *Metrics) string {
	t.Helper()
	response := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/metrics", nil)
	request.Header.Set("Accept", "application/openmetrics-text")
	request.Header.Set("Accept-Encoding", "gzip")
	m.Handler(response, request)
	if response.Code != 200 || response.Header().Get("Content-Type") != "text/plain; version=0.0.4; charset=utf-8" || response.Header().Get("Content-Encoding") != "" {
		t.Fatal(response.Code, response.Header(), response.Body.String())
	}
	return response.Body.String()
}

func sampleKey(name string, labels map[string]string) string {
	if le, ok := labels["le"]; ok {
		bound, _ := strconv.ParseFloat(le, 64)
		labels["le"] = strconv.FormatFloat(bound, 'g', -1, 64)
	}
	value, _ := json.Marshal(struct {
		Name   string
		Labels map[string]string
	}{name, labels})
	return string(value)
}

func TestFrozenPythonCollectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/metrics_python.json")
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Operations []struct {
			Name, Kind string
			Labels     []string
			Values     []float64
		}
		Families []struct {
			Name, Type, Help string
			Samples          []struct {
				Name   string
				Labels map[string]string
				Value  *float64
			}
		}
	}
	if err = json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	m := New(true)
	if len(oracle.Operations) != 23 {
		t.Fatal("incomplete oracle")
	}
	for _, op := range oracle.Operations {
		for _, value := range op.Values {
			if op.Kind == "counter" {
				m.Inc(op.Name, op.Labels...)
			} else {
				m.Observe(op.Name, value, op.Labels...)
			}
		}
	}
	parser := expfmt.NewTextParser(model.UTF8Validation)
	families, err := parser.TextToMetricFamilies(strings.NewReader(exported(t, m)))
	if err != nil {
		t.Fatal(err)
	}
	samples, err := expfmt.ExtractSamples(&expfmt.DecodeOptions{}, mapsToSlice(families)...)
	if err != nil {
		t.Fatal(err)
	}
	actual := map[string]float64{}
	for _, s := range samples {
		labels := map[string]string{}
		for k, v := range s.Metric {
			if k != model.MetricNameLabel {
				labels[string(k)] = string(v)
			}
		}
		actual[sampleKey(string(s.Metric[model.MetricNameLabel]), labels)] = float64(s.Value)
	}
	for _, family := range oracle.Families {
		name := family.Name
		if family.Type == "counter" {
			name += "_total"
		}
		f := families[name]
		if f == nil || strings.ToLower(f.GetType().String()) != family.Type || f.GetHelp() != family.Help {
			t.Fatalf("metadata %s: %v", name, f)
		}
		for _, sample := range family.Samples {
			value, present := actual[sampleKey(sample.Name, sample.Labels)]
			if !present || sample.Value == nil && value <= 0 || sample.Value != nil && value != *sample.Value {
				t.Fatalf("sample %s %v: got %g (present %v), expected %v", sample.Name, sample.Labels, value, present, sample.Value)
			}
		}
	}
	for name := range families {
		if strings.Contains(name, "speech") || strings.Contains(name, "ai_") || strings.Contains(name, "celery") {
			t.Fatal("excluded collector", name)
		}
	}
}

func TestEmptyAndDisabledHTTPExport(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		m := New(enabled)
		text := exported(t, m)
		if !strings.Contains(text, "# TYPE training_draft_v3_save_total counter") {
			t.Fatal("missing unused family metadata")
		}
		if strings.Contains(text, "# TYPE http_requests_total counter") != enabled {
			t.Fatal("HTTP flag")
		}
		if strings.Contains(text, "training_draft_v3_save_total{") {
			t.Fatal("fabricated label child")
		}
		m.Inc("training_draft_v3_save_total", "succeeded")
		if !strings.Contains(exported(t, m), `training_draft_v3_save_total{result="succeeded"} 1`) {
			t.Fatal("domain recording disabled with export")
		}
	}
}

func TestConcurrentRecordingAndScraping(t *testing.T) {
	m := New(false)
	var workers sync.WaitGroup
	for i := 0; i < 16; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for j := 0; j < 100; j++ {
				m.Inc("training_draft_v3_save_total", "succeeded")
				m.Observe("training_draft_v3_save_seconds", .01, "succeeded")
				if _, err := m.Gather(); err != nil {
					t.Error(err)
					return
				}
			}
		}()
	}
	workers.Wait()
	text := exported(t, m)
	for _, sample := range []string{`training_draft_v3_save_total{result="succeeded"} 1600`, `training_draft_v3_save_seconds_count{result="succeeded"} 1600`} {
		if !strings.Contains(text, sample) {
			t.Fatal("lost concurrent sample", sample)
		}
	}
}

func mapsToSlice(families map[string]*dto.MetricFamily) []*dto.MetricFamily {
	result := make([]*dto.MetricFamily, 0, len(families))
	for _, f := range families {
		result = append(result, f)
	}
	return result
}
