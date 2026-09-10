package training

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"north55/backend/internal/auth"
	"north55/backend/internal/training/canonical"
)

func validateDraftCatalog(training record) error {
	bad := func() error { return draftError("EVALUATION_CATALOG_SNAPSHOT_INVALID", nil) }
	catalog := jsonMap(training["evaluation_catalog_snapshot"])
	hash := strings.ToLower(pythonTrim(training.text("evaluation_catalog_sha256")))
	computed, err := canonical.SHA256(catalog)
	if catalog == nil || !jsonEqual(catalog["version"], 1) || hash == "" || err != nil || computed != hash {
		return bad()
	}
	competencies, ok := catalog["competencies"].([]any)
	if !ok {
		return bad()
	}
	seenCompetence, seenIndicator := map[int64]bool{}, map[int64]bool{}
	for _, raw := range competencies {
		c := jsonMap(raw)
		if c == nil {
			return bad()
		}
		id, err := draftInteger(c["id"], "", true)
		if err != nil || seenCompetence[id] {
			return bad()
		}
		seenCompetence[id] = true
		order := int64(0)
		if jsonTruthy(c["orderIndex"]) {
			if n, ok := jsonNumeric(c["orderIndex"]); ok {
				order = n.Num().Quo(n.Num(), n.Denom()).Int64()
			} else {
				order, err = draftInteger(c["orderIndex"], "", false)
			}
		}
		if err != nil || order < 0 || pythonTrim(jsonText(c["code"])) == "" || pythonTrim(jsonText(c["name"])) == "" {
			return bad()
		}
		indicators, ok := c["indicators"].([]any)
		if !ok {
			return bad()
		}
		for _, raw := range indicators {
			i := jsonMap(raw)
			if i == nil {
				return bad()
			}
			id, err := draftInteger(i["id"], "", true)
			if err != nil || seenIndicator[id] {
				return bad()
			}
			seenIndicator[id] = true
			code := pythonTrim(jsonText(i["code"]))
			if code == "" || helperPositive(code) || pythonTrim(jsonText(i["name"])) == "" {
				return bad()
			}
		}
	}
	return nil
}

func draftUTCTime(v any, field string) error {
	s := strings.ReplaceAll(pythonTrim(jsonText(v)), "Z", "+00:00")
	if len(s) > 10 {
		s = s[:10] + strings.Replace(s[10:], " ", "T", 1)
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999-0700", "2006-01-02T15:04-07:00", "2006-01-02T15:04:05.999999999-07"} {
		if t, err := time.Parse(layout, s); err == nil {
			_, offset := t.Zone()
			if offset == 0 {
				return nil
			}
		}
	}
	return invalidDraft(field, "must be an ISO-8601 UTC timestamp")
}

func validateQuickComment(q map[string]any, field, slot string, assessment int64) error {
	for _, check := range []struct {
		key      string
		expected any
		reason   string
	}{
		{"state", "PENDING_OB", "must equal PENDING_OB"}, {"kind", "QUICK_COMMENT", "must equal QUICK_COMMENT"}, {"schemaVersion", 1, "must equal 1"},
	} {
		if !jsonEqual(q[check.key], check.expected) {
			return invalidDraft(field+"."+check.key, check.reason)
		}
	}
	id, err := draftInteger(q["participantAssessmentId"], field+".participantAssessmentId", true)
	if err != nil {
		return err
	}
	if id != assessment {
		return invalidDraft(field+".participantAssessmentId", "must match owning participant")
	}
	if strings.ToUpper(jsonText(q["participantInitialSlot"])) != slot {
		return invalidDraft(field+".participantInitialSlot", "must match owning participant slot")
	}
	crew := jsonText(q["crew"])
	if crew == "" {
		crew = slot
	}
	if strings.ToUpper(crew) != slot {
		return invalidDraft(field+".crew", "must match owning participant slot")
	}
	observed := strings.ToUpper(jsonText(q["slotAtObservation"]))
	if observed != "CM1" && observed != "CM2" {
		return invalidDraft(field+".slotAtObservation", "must be CM1 or CM2")
	}
	if q["cmAssessmentId"] != nil {
		value, err := draftInteger(q["cmAssessmentId"], field+".cmAssessmentId", true)
		if err != nil {
			return err
		}
		if value != id {
			return invalidDraft(field+".cmAssessmentId", "must match participantAssessmentId")
		}
	}
	user, err := draftInteger(q["participantUserId"], field+".participantUserId", true)
	if err != nil {
		return err
	}
	if q["userId"] != nil {
		value, err := draftInteger(q["userId"], field+".userId", true)
		if err != nil {
			return err
		}
		if value != user {
			return invalidDraft(field+".userId", "must match participantUserId")
		}
	}
	text := jsonText(q["comment"])
	normalized := pythonTrim(strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n"))
	invalidControl := false
	for _, r := range text {
		if r < 0x20 && r != '\t' && r != '\n' && r != '\r' || r >= 0x7f && r <= 0x9f {
			invalidControl = true
			break
		}
	}
	if normalized == "" || normalized != text || utf8.RuneCountInString(normalized) > 4000 || invalidControl {
		return invalidDraft(field+".comment", "must contain 1 to 4000 normalized Unicode characters")
	}
	positive, ok := q["isPositive"].(bool)
	if !ok {
		return invalidDraft(field+".isPositive", "must be boolean")
	}
	color := "#FF453A"
	if positive {
		color = "#6EA1F2"
	}
	if !jsonEqual(q["color"], color) {
		return invalidDraft(field+".color", "must match sentiment")
	}
	if jsonText(q["hashtag"]) != "" {
		return invalidDraft(field+".hashtag", "must be empty until conversion")
	}
	for _, key := range []string{"compId", "compName", "compDisplayName", "biId", "biName", "indicatorCode"} {
		if q[key] != nil {
			return invalidDraft(field+"."+key, "must be absent until conversion")
		}
	}
	exercise, err := draftInteger(q["exerciseId"], field+".exerciseId", true)
	if err != nil {
		return err
	}
	runtimeID, err := draftInteger(q["runtimeExerciseId"], field+".runtimeExerciseId", true)
	if err != nil {
		return err
	}
	if runtimeID != exercise {
		return invalidDraft(field+".runtimeExerciseId", "must equal exerciseId")
	}
	for _, key := range []string{"exerciseSessionKey", "assignmentEventIdAtObservation"} {
		if _, err := draftUUID(q[key], field+"."+key); err != nil {
			return err
		}
	}
	ms, err := draftInteger(q["exerciseOffsetMs"], field+".exerciseOffsetMs", false)
	if err != nil {
		return err
	}
	sec, err := draftInteger(q["exerciseOffsetSec"], field+".exerciseOffsetSec", false)
	if err != nil {
		return err
	}
	if sec != ms/1000 {
		return invalidDraft(field+".exerciseOffsetSec", "must equal floor(exerciseOffsetMs / 1000)")
	}
	if q["runIndex"] != nil {
		if _, err := draftInteger(q["runIndex"], field+".runIndex", true); err != nil {
			return err
		}
	}
	if !jsonEqual(q["timelineSource"], "TIMELINE") {
		return invalidDraft(field+".timelineSource", "must equal TIMELINE")
	}
	for _, key := range []string{"timestamp", "createdAt", "updatedAt"} {
		if err := draftUTCTime(q[key], field+"."+key); err != nil {
			return err
		}
	}
	return nil
}

func validateRevisionedDraft(ctx context.Context, db runtimeDB, training record, payload map[string]any, revision int64, submitted bool, user *auth.User) error {
	if !jsonEqual(payload["schemaVersion"], 3) {
		return invalidDraft("schemaVersion", "must equal 3")
	}
	if !jsonEqual(payload["draftRevision"], revision) {
		return invalidDraft("draftRevision", "must match request clientRevision")
	}
	id, err := draftInteger(payload["trainingId"], "trainingId", true)
	if err != nil {
		return err
	}
	if id != training.number("id") {
		return invalidDraft("trainingId", "must match route training ID")
	}
	if strings.ToLower(pythonTrim(jsonText(payload["ownerUid"]))) != strings.ToLower(user.ID.String()) {
		return invalidDraft("ownerUid", "must match authenticated instructor")
	}
	if value, ok := payload["submitted"].(bool); !ok || value != submitted {
		return invalidDraft("submitted", "must match request submitted flag")
	}
	contract := training.number("comment_contract_version")
	if !jsonEqual(payload["commentContractVersion"], contract) {
		return invalidDraft("commentContractVersion", "must match persisted training contract")
	}
	if value, ok := payload["quickCommentsEntitled"].(bool); !ok || value != (contract == 1) {
		return invalidDraft("quickCommentsEntitled", "must match persisted training contract")
	}
	if contract == 1 {
		if err := validateDraftCatalog(training); err != nil {
			return err
		}
		catalog := jsonMap(payload["competenciesIndicators"])
		if catalog == nil {
			return invalidDraft("competenciesIndicators", "must contain the immutable training catalog")
		}
		hash := strings.ToLower(jsonText(catalog["evaluationCatalogSha256"]))
		computed, err := canonical.SHA256(jsonMap(catalog["evaluationCatalog"]))
		if !jsonEqual(catalog["evaluationCatalog"], training["evaluation_catalog_snapshot"]) || hash != training.text("evaluation_catalog_sha256") || err != nil || computed != hash {
			return invalidDraft("competenciesIndicators.evaluationCatalog", "must match the immutable training catalog")
		}
	}
	participants, ok := payload["participants"].([]any)
	if !ok {
		return invalidDraft("participants", "must be an array")
	}
	rows, err := db.Query(ctx, `SELECT id FROM crew_member_assessment WHERE training_session_id=$1`, id)
	if err != nil {
		return err
	}
	expected := map[int64]bool{}
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		expected[id] = true
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	received, slots := map[int64]bool{}, map[string]bool{}
	quickIDs, ordinaryIDs := map[string]bool{}, map[string]bool{}
	quickBySlot := map[string]map[string]any{"CM1": {}, "CM2": {}}
	unresolvedIDs := []string{}
	unresolvedAssessments := map[int64]bool{}
	for i, raw := range participants {
		field := fmt.Sprintf("participants[%d]", i)
		p := jsonMap(raw)
		if p == nil {
			return invalidDraft(field, "must be an object")
		}
		assessment, err := draftInteger(p["assessmentId"], field+".assessmentId", true)
		if err != nil {
			return err
		}
		if received[assessment] {
			return invalidDraft(field+".assessmentId", "must be unique")
		}
		received[assessment] = true
		slot := strings.ToUpper(pythonTrim(jsonText(p["initialCrewSlot"])))
		if slot != "CM1" && slot != "CM2" {
			return invalidDraft(field+".initialCrewSlot", "must be CM1 or CM2")
		}
		if slots[slot] {
			return invalidDraft(field+".initialCrewSlot", "must be unique")
		}
		slots[slot] = true
		quick, ok := p["quickComments"].([]any)
		if !ok {
			return invalidDraft(field+".quickComments", "must be an array")
		}
		ordinary, ok := p["mistakeReports"].([]any)
		if !ok {
			return invalidDraft(field+".mistakeReports", "must be an array")
		}
		for j, raw := range ordinary {
			f := fmt.Sprintf("%s.mistakeReports[%d]", field, j)
			report := jsonMap(raw)
			if report == nil {
				return invalidDraft(f, "must be an object")
			}
			value := jsonDefault(report, "clientReportId", report["id"])
			identifier := ""
			if contract == 1 {
				identifier, err = draftUUID(value, f+".clientReportId")
				if err != nil {
					return err
				}
				reportID, err := draftUUID(jsonDefault(report, "id", identifier), f+".id")
				if err != nil {
					return err
				}
				if reportID != identifier {
					return invalidDraft(f+".id", "must equal clientReportId")
				}
				if jsonEqual(report["kind"], "QUICK_COMMENT") || jsonEqual(report["state"], "PENDING_OB") {
					return invalidDraft(f, "must not contain an unresolved Quick Comment")
				}
			} else {
				identifier = strings.ToLower(pythonTrim(jsonText(value)))
				if identifier == "" {
					continue
				}
			}
			if ordinaryIDs[identifier] || quickIDs[identifier] {
				return invalidDraft(f+".clientReportId", "must be unique across participants")
			}
			ordinaryIDs[identifier] = true
		}
		for j, raw := range quick {
			f := fmt.Sprintf("%s.quickComments[%d]", field, j)
			q := jsonMap(raw)
			if q == nil {
				return invalidDraft(f, "must be an object")
			}
			identifier, err := draftUUID(jsonDefault(q, "clientReportId", q["id"]), f+".clientReportId")
			if err != nil {
				return err
			}
			qid, err := draftUUID(jsonDefault(q, "id", identifier), f+".id")
			if err != nil {
				return err
			}
			if qid != identifier {
				return invalidDraft(f+".id", "must equal clientReportId")
			}
			if quickIDs[identifier] || ordinaryIDs[identifier] {
				return invalidDraft(f+".clientReportId", "must be unique across quick and ordinary reports")
			}
			quickIDs[identifier] = true
			if err := validateQuickComment(q, f, slot, assessment); err != nil {
				return err
			}
			quickBySlot[slot][identifier] = q
			unresolvedIDs = append(unresolvedIDs, identifier)
			unresolvedAssessments[assessment] = true
		}
	}
	if len(received) != len(expected) {
		return invalidDraft("participants", "assessment IDs must exactly match the training participants")
	}
	for id := range received {
		if !expected[id] {
			return invalidDraft("participants", "assessment IDs must exactly match the training participants")
		}
	}
	if len(slots) != 2 {
		return invalidDraft("participants", "must contain exactly CM1 and CM2 participant slots")
	}
	for _, slot := range []string{"CM1", "CM2"} {
		key := strings.ToLower(slot) + "QuickComments"
		projection, ok := payload[key].([]any)
		if !ok {
			return invalidDraft(key, "must be an array")
		}
		byID := map[string]any{}
		for i, raw := range projection {
			f := fmt.Sprintf("%s[%d]", key, i)
			q := jsonMap(raw)
			if q == nil {
				return invalidDraft(f, "must be an object")
			}
			id, err := draftUUID(jsonDefault(q, "clientReportId", q["id"]), f+".clientReportId")
			if err != nil {
				return err
			}
			byID[id] = q
		}
		if len(projection) != len(quickBySlot[slot]) || len(byID) != len(projection) {
			return invalidDraft(key, "must equal the participant quick comment projection")
		}
		for id := range byID {
			if _, ok := quickBySlot[slot][id]; !ok {
				return invalidDraft(key, "must equal the participant quick comment projection")
			}
		}
		if !jsonEqual(byID, quickBySlot[slot]) {
			return invalidDraft(key, "must exactly match the participant quick comment projection")
		}
	}
	if contract == 0 && len(quickIDs) > 0 {
		return draftError("QUICK_COMMENT_CAPABILITY_NOT_GRANTED", nil)
	}
	if submitted && len(unresolvedIDs) > 0 {
		assessments := []int64{}
		for id := range unresolvedAssessments {
			assessments = append(assessments, id)
		}
		sort.Slice(assessments, func(i, j int) bool { return assessments[i] < assessments[j] })
		count := len(unresolvedIDs)
		if count > 50 {
			unresolvedIDs = unresolvedIDs[:50]
		}
		return draftError("UNRESOLVED_QUICK_COMMENTS", map[string]any{"count": count, "assessmentIds": assessments, "clientReportIds": unresolvedIDs, "truncated": count > 50})
	}
	return nil
}
