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
func (s *Service) createTraining(w http.ResponseWriter, r *http.Request) error {
	user, err := s.Auth.Authenticate(r, "training:write")
	if err != nil {
		return err
	}
	o, err := platform.ReadSchema(r, trainingCreateSchema)
	if err != nil {
		return err
	}
	if user.AirlineID == nil {
		return platform.Error(400, "User is not assigned to an airline")
	}
	input := trainingInput(o)
	hash := ""
	if input.ClientCreationID != nil {
		hash, err = canonical.SHA256(canonical.CreatePayload(input))
		if err != nil {
			return err
		}
	}
	ctx := r.Context()
	tx, err := s.Auth.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if input.ClientCreationID != nil {
		response, err := s.idempotentTraining(ctx, tx, user.InternalID, *input.ClientCreationID, hash)
		if err != nil {
			return err
		}
		if response != nil {
			platform.WriteJSON(w, 201, response)
			return nil
		}
	}
	quickGranted := false
	id, err := s.createTrainingInTransaction(ctx, tx, user, o, input, hash, &quickGranted)
	if err != nil {
		var pgError *pgconn.PgError
		if input.ClientCreationID != nil && errors.As(err, &pgError) && pgError.Code == "23505" && pgError.ConstraintName == "uq_training_session_instructor_client_creation" {
			if rollbackErr := tx.Rollback(ctx); rollbackErr != nil {
				return rollbackErr
			}
			response, retryErr := s.idempotentTraining(ctx, s.Auth.DB, user.InternalID, *input.ClientCreationID, hash)
			if retryErr != nil {
				return retryErr
			}
			if response != nil {
				platform.WriteJSON(w, 201, response)
				return nil
			}
		}
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	if quickGranted {
		s.Auth.Config.Metrics.Inc("training_quick_capability_granted_total", strconv.FormatInt(*user.AirlineID, 10))
	}
	platform.LogModule("app.audit", r.Context()).Info("Training created", "action", "assessment.create_training", "training_id", id, "user_id", user.ID.String())
	response, err := s.loadCreateTrainingResponse(ctx, s.Auth.DB, id, user.InternalID)
	if err != nil {
		return err
	}
	platform.WriteJSON(w, 201, response)
	return nil
}
func (s *Service) createTrainingInTransaction(ctx context.Context, tx pgx.Tx, user *auth.User, o platform.Object, input canonical.TrainingCreate, creationHash string, quickGranted *bool) (int64, error) {
	airline := *user.AirlineID
	var gradingID int64
	err := tx.QueryRow(ctx, `SELECT id FROM grading_scheme WHERE airline_id=$1 AND is_active=true ORDER BY version DESC,id DESC LIMIT 1`, airline).Scan(&gradingID)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, platform.Error(400, "Active grading scheme is not configured for airline")
	}
	if err != nil {
		return 0, err
	}
	day, err := resolveTrainingDay(ctx, tx, o, airline)
	if err != nil {
		return 0, err
	}
	if err = lockScenarioSnapshotSource(ctx, tx, day["scenario_id"], false); err != nil {
		return 0, err
	}
	// A content writer can remove the selected day while this request waits.
	// Resolve it again after taking the snapshot lock before loading the graph.
	day, err = resolveTrainingDay(ctx, tx, o, airline)
	if err != nil {
		return 0, err
	}
	scenario, err := loadSourceScenario(ctx, tx, day.number("scenario_id"))
	if err != nil {
		return 0, err
	}
	if scenario.Row.text("status") == "ARCHIVED" || scenario.Row["deleted_at"] != nil {
		return 0, platform.Error(404, "Scenario not found")
	}
	days := map[int64]bool{}
	for _, d := range scenario.Days {
		days[d.number("day_index")] = true
	}
	daysCount := max(1, len(days))
	label := scenario.Row.text("title")
	if daysCount > 1 {
		label += "-DAY " + strconv.FormatInt(day.number("day_index"), 10)
	}
	revision, version, err := ensureScenarioRevision(ctx, tx, scenario, user.InternalID)
	if err != nil {
		return 0, err
	}
	commentVersion := int64(0)
	var catalog, catalogHash any
	if s.commentEntitled(airline, input.Capabilities, ctx) {
		*quickGranted = true
		commentVersion = 1
		catalog, catalogHash, err = evaluationCatalog(ctx, tx, airline)
		if err != nil {
			return 0, err
		}
	}
	var creationKey, storedHash any
	if input.ClientCreationID != nil {
		creationKey = *input.ClientCreationID
		storedHash = creationHash
	}
	id, err := insertSnapshotRecord(ctx, tx, "training_session", record{"instructor_id": user.InternalID, "scenario_id_snapshot": scenario.Row.number("id"), "scenario_title_snapshot": scenario.Row["title"], "scenario_label_snapshot": label, "scenario_revision_id": revision, "scenario_revision_number": version, "scenario_day_module_id": day.number("id"), "day_index_snapshot": day.number("day_index"), "days_count_snapshot": daysCount, "aircraft_id_snapshot": scenario.Row.number("aircraft_id"), "aircraft_code_snapshot": scenario.Row["aircraft_code"], "grading_scheme_id": gradingID, "status": "IN_PROGRESS", "client_creation_id": creationKey, "client_creation_payload_hash": storedHash, "comment_contract_version": commentVersion, "evaluation_catalog_snapshot": catalog, "evaluation_catalog_sha256": catalogHash})
	if err != nil {
		return 0, err
	}
	assessments := map[int64]int64{}
	for index, userID := range []int64{input.CM1ID, input.CM2ID} {
		aid, err := insertSnapshotRecord(ctx, tx, "crew_member_assessment", record{"training_session_id": id, "user_id": userID, "training_role": "cm" + strconv.Itoa(index+1)})
		if err != nil {
			return 0, err
		}
		assessments[int64(index+1)] = aid
	}
	resolutions, err := resolveIndividualExercises(ctx, tx, scenario, day.number("day_index"), input.CM1ID, input.CM2ID)
	if err != nil {
		return 0, err
	}
	if err = buildTrainingSnapshot(ctx, tx, id, scenario, day.number("day_index"), resolutions, assessments); err != nil {
		return 0, err
	}
	writer := uuid.Nil
	if input.WriterInstanceID != nil {
		writer = *input.WriterInstanceID
	} else {
		writer, err = uuid.NewV7()
		if err != nil {
			return 0, err
		}
	}
	entitled := input.Capabilities != nil && s.runtimeEntitled(airline, *input.Capabilities, ctx)
	if _, err = createInitialRuntime(ctx, tx, id, assessments[1], assessments[2], user.InternalID, writer, entitled); err != nil {
		return 0, err
	}
	return id, nil
}
