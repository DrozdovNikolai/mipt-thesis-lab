from h2.cloudru_tuning import select_actual


def row(threshold, scenario, cost, on_time=1):
    return {"target_queue": threshold, "scenario": scenario, "cost_upper_rub": cost,
            "accepted": 24, "correct": 24, "on_time_rate": on_time, "lifecycle_complete": True}


def test_actual_vm_cost_can_reverse_nominal_worker_count_ranking():
    rows = [row(q, s, cost) for q, cost in ((8, 1), (12, 2)) for s in ("short", "long", "mixed")]
    chosen, _ = select_actual(rows, [8, 12])
    assert chosen["target_queue"] == 8


def test_a_cheap_baseline_missing_the_deadline_cannot_be_selected():
    rows = [row(q, s, cost) for q, cost in ((8, 2), (12, 1)) for s in ("short", "long", "mixed")]
    rows[-2]["on_time_rate"] = .9
    chosen, _ = select_actual(rows, [8, 12])
    assert chosen["target_queue"] == 8


def test_incomplete_scenario_set_does_not_look_artificially_cheap():
    rows = [row(8, s, 2) for s in ("short", "long", "mixed")] + [row(12, "short", 1)]
    chosen, rankings = select_actual(rows, [8, 12])
    assert chosen["target_queue"] == 8 and not rankings[1]["eligible"]
