"""Deterministic workload stress probe for retirement policies (no cloud costs).

Node-seconds are a simulation proxy, never Billing or measured cost. The
schedule-aware arm is only applicable when future arrivals are explicitly
announced by the application; it is not a generic workload predictor.
"""
import json
from pathlib import Path
import sys


def simulate(arrivals, *, idle_seconds, cold_seconds=450, service_seconds=30,
             announced_schedule=False, slo_seconds=900):
    if any(a < 0 for a in arrivals) or arrivals != sorted(arrivals):
        raise ValueError('Chronological nonnegative arrivals required')
    if min(idle_seconds, cold_seconds, service_seconds, slo_seconds) < 0 or service_seconds == 0:
        raise ValueError('Invalid timing')
    ready, born, ends = None, None, None
    node_seconds, boots = 0., 0
    latencies = []
    for index, arrival in enumerate(arrivals):
        if ready is None or arrival > ends:
            if ready is not None:
                node_seconds += ends - born
            born, ready = arrival, arrival + cold_seconds
            boots += 1
        ready = max(arrival, ready) + service_seconds
        retention = idle_seconds
        if announced_schedule and index + 1 < len(arrivals):
            gap = max(0, arrivals[index + 1] - ready)
            # Retain only when less node-time than shutting down and starting.
            if gap <= cold_seconds:
                retention = max(retention, gap)
        ends = ready + retention
        latencies.append(ready - arrival)
    if born is not None:
        node_seconds += ends - born
    return {'boots': boots, 'proxy_node_seconds': node_seconds, 'tasks': len(arrivals),
            'max_latency_seconds': max(latencies, default=0),
            'mean_latency_seconds': sum(latencies) / len(latencies) if latencies else 0,
            'on_time': sum(x <= slo_seconds for x in latencies)}


def run(output):
    output.mkdir(exist_ok=False)
    policies = {'current_tail_660s': {'idle_seconds': 660},
                'fast_tail_120s': {'idle_seconds': 120},
                'announced_schedule_120s': {'idle_seconds': 120, 'announced_schedule': True}}
    results = []
    for interval in (150, 300, 600, 800, 1200):
        for cold in (450, 600):
            arrivals = [interval * n for n in range(8)]
            cases = {name: simulate(arrivals, cold_seconds=cold, **kwargs) for name, kwargs in policies.items()}
            base = cases['current_tail_660s']['proxy_node_seconds']
            for row in cases.values():
                row['proxy_saving_percent'] = 100 * (1 - row['proxy_node_seconds'] / base)
            results.append({'interval_seconds': interval, 'cold_seconds': cold, 'arrivals': arrivals, 'policies': cases})
    (output / 'simulation.json').write_text(json.dumps({'basis': 'synthetic_simulation_not_cloud_benchmark',
        'single_worker_service_seconds': 30, 'all_scenarios_retained': True,
        'announced_schedule_requires_known_future_arrivals': True, 'cases': results}, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    run(Path(sys.argv[1]))
