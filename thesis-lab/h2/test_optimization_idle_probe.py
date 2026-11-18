import pytest
from h2.optimization_idle_probe import simulate


def test_single_job_includes_boot_processing_and_retirement():
    result = simulate([0], idle_seconds=120)
    assert result['proxy_node_seconds'] == 450 + 30 + 120
    assert result['boots'] == result['on_time'] == 1


def test_busy_worker_is_not_retired_between_queued_jobs():
    result = simulate([0, 1, 2], idle_seconds=0)
    assert result['boots'] == 1
    assert result['proxy_node_seconds'] == 450 + 3 * 30


def test_repeated_cold_starts_can_make_aggressive_retirement_more_expensive():
    arrivals = [800 * i for i in range(8)]
    fast = simulate(arrivals, idle_seconds=120, cold_seconds=600)
    original = simulate(arrivals, idle_seconds=660, cold_seconds=600)
    assert fast['boots'] > original['boots']
    assert fast['proxy_node_seconds'] > original['proxy_node_seconds']


def test_invalid_arrivals_are_not_reordered_to_improve_result():
    with pytest.raises(ValueError):
        simulate([1, 0], idle_seconds=120)
