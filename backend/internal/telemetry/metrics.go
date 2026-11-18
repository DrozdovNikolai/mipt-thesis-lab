// Package telemetry owns the retained Prometheus metrics; AI/speech/Celery
// collectors are intentionally absent. Domain recording is independent of
// whether the HTTP export endpoint is enabled.
package telemetry

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	dto "github.com/prometheus/client_model/go"
	"github.com/prometheus/common/expfmt"
	"google.golang.org/protobuf/proto"
)

//go:embed catalog.json
var catalogJSON []byte

var integerBucketLabel = regexp.MustCompile(`le="(-?[0-9]+)"`)

type definition struct {
	Name    string    `json:"name"`
	Help    string    `json:"help"`
	Kind    string    `json:"kind"`
	Labels  []string  `json:"labels"`
	Buckets []float64 `json:"buckets"`
}
type family struct {
	definition
	counter   *prometheus.CounterVec
	histogram *prometheus.HistogramVec
	summary   *prometheus.SummaryVec
	created   *prometheus.GaugeVec
	mu        sync.Mutex
	seen      map[string]bool
}
type Metrics struct {
	registry *prometheus.Registry
	families map[string]*family
}

func New(includeHTTP bool) *Metrics {
	var catalog struct{ Domain, HTTP []definition }
	if err := json.Unmarshal(catalogJSON, &catalog); err != nil {
		panic(err)
	}
	m := &Metrics{registry: prometheus.NewRegistry(), families: map[string]*family{}}
	m.registry.MustRegister(prometheus.NewGoCollector(), prometheus.NewProcessCollector(prometheus.ProcessCollectorOpts{}))
	definitions := catalog.Domain
	if includeHTTP {
		definitions = append(definitions, catalog.HTTP...)
	}
	for _, d := range definitions {
		f := &family{definition: d, seen: map[string]bool{}}
		switch d.Kind {
		case "counter":
			f.counter = prometheus.NewCounterVec(prometheus.CounterOpts{Name: d.Name, Help: d.Help}, d.Labels)
			m.registry.MustRegister(f.counter)
		case "histogram":
			f.histogram = prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: d.Name, Help: d.Help, Buckets: d.Buckets}, d.Labels)
			m.registry.MustRegister(f.histogram)
		case "summary":
			f.summary = prometheus.NewSummaryVec(prometheus.SummaryOpts{Name: d.Name, Help: d.Help, Objectives: map[float64]float64{}}, d.Labels)
			m.registry.MustRegister(f.summary)
		default:
			panic("unknown metric type: " + d.Kind)
		}
		createdName := strings.TrimSuffix(d.Name, "_total") + "_created"
		f.created = prometheus.NewGaugeVec(prometheus.GaugeOpts{Name: createdName, Help: d.Help}, d.Labels)
		m.registry.MustRegister(f.created)
		m.families[d.Name] = f
		if len(d.Labels) == 0 {
			f.child(nil)
		}
	}
	return m
}
func (f *family) child(labels []string) {
	encoded, _ := json.Marshal(labels)
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.seen[string(encoded)] {
		return
	}
	f.seen[string(encoded)] = true
	f.created.WithLabelValues(labels...).Set(float64(time.Now().UnixNano()) / 1e9)
	switch f.Kind {
	case "counter":
		f.counter.WithLabelValues(labels...)
	case "histogram":
		f.histogram.WithLabelValues(labels...)
	case "summary":
		f.summary.WithLabelValues(labels...)
	}
}
func (m *Metrics) Inc(name string, labels ...string) {
	if m == nil {
		return
	}
	f := m.families[name]
	if f == nil || f.counter == nil {
		panic("unknown counter: " + name)
	}
	f.child(labels)
	f.counter.WithLabelValues(labels...).Inc()
}
func (m *Metrics) Observe(name string, value float64, labels ...string) {
	if m == nil {
		return
	}
	f := m.families[name]
	if f == nil {
		panic("unknown observer: " + name)
	}
	f.child(labels)
	if f.histogram != nil {
		f.histogram.WithLabelValues(labels...).Observe(value)
	} else if f.summary != nil {
		f.summary.WithLabelValues(labels...).Observe(value)
	} else {
		panic("counter cannot observe: " + name)
	}
}

// Export HELP/TYPE even before a labelled family gets its first child.
// Preserve those declarations around the official Go collectors, as well as
// the *_created series. Counters/histograms remain library-managed.
func (m *Metrics) Gather() ([]*dto.MetricFamily, error) {
	result, err := m.registry.Gather()
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	for _, f := range result {
		seen[f.GetName()] = true
	}
	for _, f := range m.families {
		if seen[f.Name] {
			continue
		}
		typ := map[string]dto.MetricType{"counter": dto.MetricType_COUNTER, "histogram": dto.MetricType_HISTOGRAM, "summary": dto.MetricType_SUMMARY}[f.Kind]
		result = append(result, &dto.MetricFamily{Name: proto.String(f.Name), Help: proto.String(f.Help), Type: &typ})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].GetName() < result[j].GetName() })
	return result, nil
}

func (m *Metrics) Handler(w http.ResponseWriter, r *http.Request) {
	families, err := m.Gather()
	if err != nil {
		http.Error(w, "metrics collection failed", 500)
		return
	}
	var out bytes.Buffer
	for _, f := range families {
		if len(f.Metric) == 0 {
			help := strings.NewReplacer("\\", "\\\\", "\n", "\\n").Replace(f.GetHelp())
			fmt.Fprintf(&out, "# HELP %s %s\n# TYPE %s %s\n", f.GetName(), help, f.GetName(), strings.ToLower(f.GetType().String()))
			continue
		}
		if _, err = expfmt.MetricFamilyToText(&out, f); err != nil {
			http.Error(w, "metrics encoding failed", 500)
			return
		}
	}
	// Histogram bounds are formatted as floating-point numbers.
	content := integerBucketLabel.ReplaceAll(out.Bytes(), []byte(`le="${1}.0"`))
	// Instrumentator.expose ignores Accept/Accept-Encoding and does not gzip.
	w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	w.Header().Set("Content-Length", fmt.Sprint(len(content)))
	_, _ = w.Write(content)
}

func (m *Metrics) HTTP(method, handler string, status int, requestSize, responseSize int64, duration float64) {
	if m == nil {
		return
	}
	m.Inc("http_requests_total", method, fmt.Sprintf("%dxx", status/100), handler)
	m.Observe("http_request_size_bytes", float64(requestSize), handler)
	m.Observe("http_response_size_bytes", float64(responseSize), handler)
	m.Observe("http_request_duration_highr_seconds", duration)
	m.Observe("http_request_duration_seconds", duration, method, handler)
}
