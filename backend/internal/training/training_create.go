package training

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"north55/backend/internal/auth"
	"north55/backend/internal/platform"
	"north55/backend/internal/training/canonical"
)

var trainingCreateSchema = platform.Schema{Fields: []platform.Field{
	optionalField(runtimeInt("scenario_day_module_id", "scenarioDayModuleId", 0, true)), optionalField(runtimeInt("scenario_id", "scenarioId", 0, true)), {Name: "scenario_name", Alias: "scenarioName", Kind: "string", Nullable: true}, runtimeInt("cm1_id", "cm1Id", 0, true), runtimeInt("cm2_id", "cm2Id", 0, true), optionalField(runtimeID("client_creation_id", "clientCreationId")), optionalField(runtimeID("writer_instance_id", "writerInstanceId")), {Name: "runtime_client_capabilities", Alias: "runtimeClientCapabilities", Kind: "object", Nullable: true, Schema: &runtimeCapabilitiesSchema},
}, Check: func(o platform.Object) string {
	if o["scenario_day_module_id"] == nil && o["scenario_id"] == nil && strings.TrimSpace(o.String("scenario_name")) == "" {
		return "Either scenario_day_module_id, scenario_id or scenario_name must be provided"
	}
	if o.Int("cm1_id") == o.Int("cm2_id") {
		return "cm1_id and cm2_id must be different users"
	}
	var capability *canonical.Capabilities
	if value, ok := o["runtime_client_capabilities"].(platform.Object); ok {
		c := parseCapabilities(value)
		capability = &c
	}
	durable := capability != nil && capability.OfflineDurabilityReady && (len(capability.LiveCrewSwapVersions) > 0 || len(capability.QuickCommentVersions) > 0)
	if durable && o["writer_instance_id"] == nil {
		return "writer_instance_id is required for durable training capabilities"
	}
	if durable && o["client_creation_id"] == nil {
		return "client_creation_id is required for durable training capabilities"
	}
	if o["client_creation_id"] != nil && o["scenario_day_module_id"] == nil && o["scenario_id"] == nil {
		return "idempotent training creation requires scenario_day_module_id or scenario_id"
	}
	if durable && capability.TransactionalStore == "NONE" {
		return "transactional_store is required for durable training capabilities"
	}
	return ""
}}

func (s *Service) registerTrainings(mux *platform.Router) {
	p := s.Auth.Config.APIPrefix + "/training/trainings"
	mux.HandleFunc("POST "+p, platform.Wrap(s.createTraining))
	mux.HandleFunc("GET "+p+"/{training_id}/exercises", platform.Wrap(s.getTrainingExercises))
	mux.HandleFunc("DELETE "+p+"/{training_id}", platform.Wrap(s.deleteTraining))
}
func trainingInput(o platform.Object) canonical.TrainingCreate {
	c := canonical.TrainingCreate{ScenarioDayModuleID: runtimePtr[int64](o, "scenario_day_module_id"), ScenarioID: runtimePtr[int64](o, "scenario_id"), CM1ID: o.Int("cm1_id"), CM2ID: o.Int("cm2_id"), ClientCreationID: runtimePtr[uuid.UUID](o, "client_creation_id"), WriterInstanceID: runtimePtr[uuid.UUID](o, "writer_instance_id")}
	if v, ok := o["runtime_client_capabilities"].(platform.Object); ok {
		capability := parseCapabilities(v)
		c.Capabilities = &capability
	}
	return c
}
func (s *Service) idempotentTraining(ctx context.Context, db runtimeDB, userID int64, key uuid.UUID, hash string) (map[string]any, error) {
	var id int64
	var stored *string
	err := db.QueryRow(ctx, `SELECT id,client_creation_payload_hash FROM training_session WHERE instructor_id=$1 AND client_creation_id=$2`, userID, key).Scan(&id, &stored)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if stored == nil || !canonical.EqualHash(*stored, hash) {
		return nil, runtimeError("TRAINING_CREATE_IDEMPOTENCY_CONFLICT")
	}
	return s.loadCreateTrainingResponse(ctx, db, id, userID)
}
func resolveTrainingDay(ctx context.Context, db runtimeDB, o platform.Object, airline int64) (record, error) {
	if o["scenario_day_module_id"] != nil {
		day, err := queryRecord(ctx, db, `SELECT to_jsonb(d) FROM scenario_day_module d JOIN scenario s ON s.id=d.scenario_id WHERE d.id=$1 AND s.status<>'ARCHIVED' AND s.deleted_at IS NULL AND ($2::bigint=0 OR s.airline_id=$2)`, o.Int("scenario_day_module_id"), airline)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, platform.Error(404, "Scenario day not found")
		}
		if err != nil {
			return nil, err
		}
		if o["scenario_id"] != nil && day.number("scenario_id") != o.Int("scenario_id") {
			return nil, platform.Error(400, "scenario_day_module_id does not belong to scenario_id")
		}
		return day, nil
	}
	query := `SELECT to_jsonb(s) FROM scenario s WHERE s.status<>'ARCHIVED' AND s.deleted_at IS NULL AND ($1::bigint=0 OR s.airline_id=$1)`
	var selector any
	if o["scenario_id"] != nil {
		query += " AND s.id=$2"
		selector = o.Int("scenario_id")
	} else {
		query += " AND s.title=$2"
		selector = strings.TrimSpace(o.String("scenario_name"))
	}
	scenarios, err := queryRecords(ctx, db, query, airline, selector)
	if err != nil {
		return nil, err
	}
	if len(scenarios) == 0 {
		return nil, platform.Error(404, "Scenario not found")
	}
	if len(scenarios) > 1 {
		return nil, platform.Error(409, "Scenario title is not unique; use scenario_id")
	}
	days, err := queryRecords(ctx, db, `SELECT to_jsonb(d) FROM scenario_day_module d WHERE scenario_id=$1 ORDER BY day_index,order_index,module_id,id`, scenarios[0].number("id"))
	if err != nil {
		return nil, err
	}
	if len(days) == 0 {
		return nil, platform.Error(400, "Scenario does not have any day mapping")
	}
	first := days[0]
	for _, d := range days {
		if d.number("day_index") != first.number("day_index") {
			return nil, platform.Error(409, "Scenario has multiple days; use scenario_day_module_id")
		}
	}
	return first, nil
}
func (s *Service) commentEntitled(airline int64, c *canonical.Capabilities, contexts ...context.Context) bool {
	if !s.Auth.Config.QuickCommentsEnabled || c == nil || !c.OfflineDurabilityReady || c.TransactionalStore == "NONE" {
		return false
	}
	version := false
	for _, v := range c.QuickCommentVersions {
		if v == 1 {
			version = true
		}
	}
	if !version {
		return false
	}
	raw := strings.TrimSpace(s.Auth.Config.QuickCommentsAirlineIDs)
	if raw == "" {
		return true
	}
	allowed := false
	for _, v := range strings.Split(raw, ",") {
		v = strings.TrimSpace(v)
		if v == "" {
			continue
		}
		id, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			platform.LogModule("app.audit", contexts...).Error("Invalid quick comments airline allowlist", "action", "assessment.quick_comments.config_invalid")
			return false
		}
		if id == airline {
			allowed = true
		}
	}
	return allowed
}
func evaluationCatalog(ctx context.Context, db runtimeDB, airline int64) (map[string]any, string, error) {
	competencies, err := queryRecords(ctx, db, `SELECT to_jsonb(c) FROM competence c WHERE airline_id=$1 AND retired_at IS NULL ORDER BY order_index,id`, airline)
	if err != nil {
		return nil, "", err
	}
	ids := []int64{}
	for _, c := range competencies {
		ids = append(ids, c.number("id"))
	}
	indicators, err := queryRecords(ctx, db, `SELECT to_jsonb(b) FROM behavioural_indicator b WHERE competence_id=ANY($1) AND retired_at IS NULL ORDER BY order_index,id`, ids)
	if err != nil {
		return nil, "", err
	}
	byCompetence := map[int64][]map[string]any{}
	for _, b := range indicators {
		if helperPositive(b.text("code")) {
			continue
		}
		item := map[string]any{"id": b.number("id"), "code": b.text("code"), "shortName": b["short_name"], "name": b.text("name"), "orderIndex": b.number("order_index")}
		byCompetence[b.number("competence_id")] = append(byCompetence[b.number("competence_id")], item)
	}
	items := []map[string]any{}
	for _, c := range competencies {
		indicators := byCompetence[c.number("id")]
		if indicators == nil {
			indicators = []map[string]any{}
		}
		items = append(items, map[string]any{"id": c.number("id"), "code": cases.Upper(language.Und).String(strings.TrimSpace(c.text("code"))), "name": c.text("name"), "orderIndex": c.number("order_index"), "indicators": indicators})
	}
	payload := map[string]any{"version": 1, "competencies": items}
	hash, err := canonical.SHA256(payload)
	return payload, hash, err
}
