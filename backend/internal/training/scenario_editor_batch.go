package training

import (
	"context"
	"fmt"
	"sort"
)

// loadEditorScenarioList reads all nested editor data in batches. The list
// handler already selected visible scenario IDs and owns their response order.
func loadEditorScenarioList(ctx context.Context, db runtimeDB, ids []int64) ([]sourceScenario, error) {
	graphs := make([]sourceScenario, len(ids))
	if len(ids) == 0 {
		return graphs, nil
	}
	index := make(map[int64]int, len(ids))
	for i, id := range ids {
		index[id] = i
	}
	scenarios, err := queryRecords(ctx, db, `SELECT to_jsonb(s)||jsonb_build_object('aircraft_code',a.code) FROM scenario s LEFT JOIN aircraft_airline a ON a.id=s.aircraft_id WHERE s.id=ANY($1::bigint[])`, ids)
	if err != nil {
		return nil, err
	}
	for _, row := range scenarios {
		graphs[index[row.number("id")]].Row = row
	}
	for _, graph := range graphs {
		if graph.Row == nil {
			return nil, fmt.Errorf("scenario disappeared while loading editor list")
		}
	}

	// The single-scenario editor orders days by module ID rather than day index.
	days, err := queryRecords(ctx, db, `SELECT to_jsonb(d)||jsonb_build_object('__owner_scenario_id',m.scenario_id) FROM scenario_day_module d JOIN module m ON m.id=d.module_id WHERE m.scenario_id=ANY($1::bigint[]) ORDER BY m.scenario_id,m.id`, ids)
	if err != nil {
		return nil, err
	}
	for _, day := range days {
		owner := day.number("__owner_scenario_id")
		delete(day, "__owner_scenario_id")
		graphs[index[owner]].Days = append(graphs[index[owner]].Days, day)
	}
	pdfs, err := queryRecords(ctx, db, `SELECT to_jsonb(p) FROM scenario_pdf p WHERE p.scenario_id=ANY($1::bigint[]) ORDER BY p.scenario_id,p.order_index,p.id`, ids)
	if err != nil {
		return nil, err
	}
	for _, pdf := range pdfs {
		i := index[pdf.number("scenario_id")]
		graphs[i].Pdfs = append(graphs[i].Pdfs, pdf)
	}
	modules, err := queryRecords(ctx, db, `SELECT to_jsonb(m)||jsonb_build_object('content_subcolumn_name',c.name,'content_subcolumn',to_jsonb(c)) FROM module m LEFT JOIN scenario_content_subcolumn c ON c.id=m.content_subcolumn_id WHERE m.scenario_id=ANY($1::bigint[]) ORDER BY m.scenario_id,m.order_index,m.id`, ids)
	if err != nil {
		return nil, err
	}
	type moduleLocation struct{ scenario, module int }
	moduleIndex := make(map[int64]moduleLocation, len(modules))
	moduleIDs := make([]int64, 0, len(modules))
	for _, row := range modules {
		i := index[row.number("scenario_id")]
		moduleIndex[row.number("id")] = moduleLocation{i, len(graphs[i].Modules)}
		moduleIDs = append(moduleIDs, row.number("id"))
		graphs[i].Modules = append(graphs[i].Modules, sourceModule{Row: row, Exercises: []*sourceExercise{}})
	}
	rows, err := queryRecords(ctx, db, `SELECT to_jsonb(e) FROM exercise e WHERE e.module_id=ANY($1::bigint[])`, moduleIDs)
	if err != nil {
		return nil, err
	}
	exercises := make([]*sourceExercise, 0, len(rows))
	for _, row := range rows {
		location := moduleIndex[row.number("module_id")]
		exercise := &sourceExercise{Row: row}
		exercises = append(exercises, exercise)
		module := &graphs[location.scenario].Modules[location.module]
		module.Exercises = append(module.Exercises, exercise)
	}
	for i := range graphs {
		for j := range graphs[i].Modules {
			exercises := graphs[i].Modules[j].Exercises
			sort.SliceStable(exercises, func(a, b int) bool {
				return exercises[a].Row.number("order_index") < exercises[b].Row.number("order_index")
			})
		}
	}
	if err := loadExerciseAssetsMode(ctx, db, exercises, false, true); err != nil {
		return nil, err
	}
	return graphs, nil
}
