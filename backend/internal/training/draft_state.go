package training

import (
	"encoding/json"
	"strings"
)

const draftStateFields = "trainingId ownerUid draftRevision submitted commentContractVersion quickCommentsEntitled trainingActivated scenarioId scenarioDayModuleId speechSessionId speechChunkSeconds speechLastChunkIndex"
const draftParticipantFields = "assessmentId userId initialCrewSlot grades mistakeReports quickComments summary result signature"
const draftReportFields = "clientReportId compId biId comment isPositive hashtag timestamp timelineSource runtimeExerciseId exerciseSessionKey exerciseOffsetMs assignmentEventIdAtObservation plannedDurationMs runIndex kind state schemaVersion slotAtObservation createdAt updatedAt participantUserId"

func projectJSON(source map[string]any, fields string) map[string]any {
	out := map[string]any{}
	for _, key := range strings.Fields(fields) {
		if v, ok := source[key]; ok {
			out[key] = jsonCopy(v)
		}
	}
	return out
}
func compactVersion(p map[string]any) int {
	// Transport version must be an actual integer, not bool or a JSON float.
	if v, ok := p["syncStateVersion"].(json.Number); ok {
		if v == "1" {
			return 1
		}
		if v == "2" {
			return 2
		}
	}
	if v, ok := p["syncStateVersion"].(int); ok && v >= 1 && v <= 2 {
		return v
	}
	return 0
}

// The source projection iterates JSON containers before validating participants.
// Preserve its distinction between malformed iteration and unsupported fields.
func projectionItems(v any) ([]any, bool) {
	if a, ok := v.([]any); ok {
		return a, true
	}
	if s, ok := v.(string); ok {
		out := []any{}
		for _, r := range s {
			out = append(out, string(r))
		}
		return out, true
	}
	if m := jsonMap(v); m != nil {
		out := []any{}
		for key := range m {
			out = append(out, key)
		}
		return out, true
	}
	return nil, false
}
func projectDraftItem(v any, fields string) (map[string]any, error) {
	if m := jsonMap(v); m != nil {
		return projectJSON(m, fields), nil
	}
	items, ok := projectionItems(v)
	if !ok {
		return nil, invalidDraft("participants", "invalid state")
	}
	for _, field := range strings.Fields(fields) {
		if s, ok := v.(string); ok && strings.Contains(s, field) {
			return nil, invalidDraft("participants", "invalid state")
		}
		for _, item := range items {
			if jsonEqual(item, field) {
				return nil, invalidDraft("participants", "invalid state")
			}
		}
	}
	return map[string]any{}, nil
}
func compactDraft(source map[string]any, version int) (map[string]any, error) {
	catalog := jsonMap(source["competenciesIndicators"])
	projection := jsonMap(source["crewRuntimeProjection"])
	result := projectJSON(source, draftStateFields)
	result["schemaVersion"] = 3
	result["syncStateVersion"] = version
	result["evaluationCatalogSha256"] = jsonDefault(source, "evaluationCatalogSha256", jsonDefault(catalog, "evaluationCatalogSha256", ""))
	if version != 2 {
		result["requiredRuntimeEventId"] = jsonDefault(projection, "currentEventId", jsonDefault(source, "requiredRuntimeEventId", ""))
	}
	raw := jsonDefault(source, "participants", []any{})
	participants, ok := projectionItems(raw)
	if !ok {
		return nil, invalidDraft("participants", "invalid state")
	}
	items := make([]any, 0, len(participants))
	for _, raw := range participants {
		out, err := projectDraftItem(raw, draftParticipantFields)
		if err != nil {
			return nil, err
		}
		if version == 2 && jsonEqual(source["commentContractVersion"], 1) {
			for _, key := range []string{"mistakeReports", "quickComments"} {
				if values, present := out[key]; present {
					list, ok := projectionItems(values)
					if !ok {
						return nil, invalidDraft("participants", "invalid state")
					}
					reports := make([]any, 0, len(list))
					for _, raw := range list {
						report, err := projectDraftItem(raw, draftReportFields)
						if err != nil {
							return nil, err
						}
						reports = append(reports, report)
					}
					out[key] = reports
				}
			}
		}
		items = append(items, out)
	}
	result["participants"] = items
	return result, nil
}
func expandDraft(state map[string]any, training record) map[string]any {
	out := jsonCopy(state).(map[string]any)
	out["competenciesIndicators"] = map[string]any{"evaluationCatalog": training["evaluation_catalog_snapshot"], "evaluationCatalogSha256": training["evaluation_catalog_sha256"]}
	participants, _ := out["participants"].([]any)
	for _, raw := range participants {
		p := jsonMap(raw)
		if compactVersion(state) == 2 && jsonEqual(state["commentContractVersion"], 1) {
			for _, key := range []string{"mistakeReports", "quickComments"} {
				reports, _ := p[key].([]any)
				if reports == nil {
					reports = []any{}
				}
				for _, raw := range reports {
					r := jsonMap(raw)
					r["id"] = r["clientReportId"]
					r["exerciseId"] = r["runtimeExerciseId"]
					r["crew"] = p["initialCrewSlot"]
					r["cmAssessmentId"] = p["assessmentId"]
					r["color"] = "#FF453A"
					if jsonTruthy(r["isPositive"]) {
						r["color"] = "#6EA1F2"
					}
					if n, ok := r["exerciseOffsetMs"].(json.Number); ok && !strings.ContainsAny(string(n), ".eE") {
						if v, err := n.Int64(); err == nil {
							sec := v / 1000
							if v < 0 && v%1000 != 0 {
								sec--
							}
							r["exerciseOffsetSec"] = sec
						}
					}
					if jsonEqual(r["kind"], "QUICK_COMMENT") {
						r["participantAssessmentId"] = p["assessmentId"]
						r["participantInitialSlot"] = p["initialCrewSlot"]
					}
				}
				p[key] = reports
			}
		}
		out[strings.ToLower(pythonString(jsonDefault(p, "initialCrewSlot", "")))+"QuickComments"] = jsonDefault(p, "quickComments", []any{})
	}
	return out
}
