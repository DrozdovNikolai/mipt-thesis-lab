import pytest

from h2.cloud_tuning import replay, workloads


def test_equal_count_batches_expose_duration_blindness_without_modeling_a_saving():
    values = {"pilot-30": 2, "pilot-180": 8, "pilot-900": 34}
    short = replay(workloads()["short"], runtime_by_fixture=values, cold_seconds=400,
                   target_queue=12, idle_tail_seconds=600)
    long = replay(workloads()["long"], runtime_by_fixture=values, cold_seconds=400,
                  target_queue=12, idle_tail_seconds=600)
    assert short["workers"] == long["workers"] == 2
    assert max(short["processing_seconds"]) == 424
    assert max(long["processing_seconds"]) == 808
    assert short["proxy_node_seconds"] == 2048


def test_replay_detects_that_the_cheapest_concurrency_misses_a_deadline():
    result = replay(["long"] * 24, runtime_by_fixture={"long": 34}, cold_seconds=400,
                    target_queue=24, idle_tail_seconds=600)
    assert max(result["processing_seconds"]) == 1216
    assert sum(t <= 900 for t in result["processing_seconds"]) == 14


def test_pilot_and_main_receive_same_duration_trace_but_distinct_audio():
    pilot, main = workloads(), workloads(group="main")
    assert len(pilot["mixed"]) == 24
    assert {x: pilot["mixed"].count(x) for x in set(pilot["mixed"])} == {"pilot-30": 8, "pilot-180": 8, "pilot-900": 8}
    assert [x.split("-")[1] for x in pilot["mixed"]] == [x.split("-")[1] for x in main["mixed"]]
    assert set(pilot["mixed"]).isdisjoint(main["mixed"])


def test_nonfinite_runtime_is_not_treated_as_success():
    with pytest.raises(ValueError, match="runtime"):
        replay(["x"], runtime_by_fixture={"x": float("nan")}, cold_seconds=400,
               target_queue=4, idle_tail_seconds=600)
