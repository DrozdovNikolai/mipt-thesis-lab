"""Exploratory calibration and resource-lifetime analysis of retained H2 traces.

This never rewrites a source run. The two-minute retirement case is a numerical
counterfactual; ordinary cleanup timings are evidence of API latency, not proof
that an autonomous scale-to-zero controller has been deployed.
"""
from collections import defaultdict
from datetime import datetime, UTC
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def fit_envelope(samples, stage):
    """Small deterministic 2D linear program: nonnegative upper affine bound."""
    points = [(float(r['audio_seconds']), float(r[stage])) for r in samples]
    if not points or any(not math.isfinite(x + y) or x <= 0 or y < 0 for x, y in points):
        raise ValueError('Finite positive durations and nonnegative timings required')
    slopes = {0.0, *(y / x for x, y in points)}
    for x1, y1 in points:
        for x2, y2 in points:
            if x1 != x2 and (y2 - y1) / (x2 - x1) >= 0:
                slopes.add((y2 - y1) / (x2 - x1))
    candidates = [(max(0, max(y - b * x for x, y in points)), b) for b in slopes]
    a, b = min(candidates, key=lambda v: (sum(v[0] + v[1] * x for x, _ in points), v))
    assert all(a + b * x + 1e-9 >= y for x, y in points)
    return {'fixed_seconds': a, 'seconds_per_audio_second': b}


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def retirement_windows(run):
    events = [json.loads(x) for x in (run / 'events.jsonl').read_text().splitlines()]
    result = []
    for e in events:
        label = e.get('label', '')
        if e.get('name') != 'request' or not label.startswith('delete-pool:'):
            continue
        trial = label.removeprefix('delete-pool:')
        cost_path = run / 'trials' / trial / 'cost-summary.json'
        if not cost_path.exists():
            continue
        cost = read(cost_path)
        requested = stamp(e['at'])
        live = [r for r in cost['resources'] if r['last_seen_at'] >= requested]
        if not live or any(r['first_absent_at'] is None for r in live):
            continue
        gone = max(r['first_absent_at'] for r in live)
        result.append({'source': str(run.relative_to(ROOT)), 'trial': trial,
            'request_at': e['at'], 'resources_live_at_request': len(live),
            'request_to_last_resource_absence_seconds_upper': gone - requested,
            'purpose': 'ordinary_cleanup_not_automatic_retirement',
            'source_cost_sha256': hashlib.sha256(cost_path.read_bytes()).hexdigest()})
    return result


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'worktrees/h2-autoscaling/firefly-backend/app/modules/speech/workload_scaling.py'
    spec = importlib.util.spec_from_file_location('h2_frozen_scaling', source)
    scaling = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = scaling
    spec.loader.exec_module(scaling)
    pilot = ROOT / 'results/cloudru-h2-pilot-20261014-a'
    current = ROOT / 'results/cloudru-h2-main-20261016-a'
    fit = read(pilot / 'pilot/stage-calibration.json')
    plan = read(current / 'main/plan.json')
    improved = {s: fit_envelope(fit['samples'], s) for s in ('preprocess', 'asr')}
    configs = {'original': plan['config'],
        'upper_envelope_same_margin': {**plan['config'], 'costs': improved},
        'lean_margin_probe': {**plan['config'], 'costs': improved, 'safety_factor': 1.0,
            'cold_start_seconds': math.ceil(max(r['start_latency_seconds'] for r in
                read(pilot / 'pilot-v2/cold-starts.json'))) + 10}}
    decisions = {}
    for name, cfg in configs.items():
        costs = {k: scaling.StageCost(**v) for k, v in cfg['costs'].items()}
        decisions[name] = {}
        for scenario, fixtures in plan['workloads'].items():
            items = [scaling.WorkItem(str(i), 0, 900, float(f.split('-')[1])) for i, f in enumerate(fixtures)]
            decision = scaling.decide(items, now=0, costs=costs, ready_workers=0,
                cold_start_seconds=cfg['cold_start_seconds'], max_workers=3, safety_factor=cfg['safety_factor'])
            decisions[name][scenario] = {'replicas': decision.replicas, 'predicted_late': decision.predicted_late,
                                         'remaining_seconds': decision.remaining_seconds}
    mechanism = read(current / 'reboot-recovery/primary-result/cost-mechanism.json')
    groups = defaultdict(lambda: defaultdict(float))
    boot, checks = [], []
    for t in mechanism['trials']:
        trial = Path(t['source_run']) / 'trials' / t['trial']
        snapshot = read(trial / 'snapshot.json')
        cost = read(trial / 'cost-summary.json')
        done = max(x['completed_at'] for x in snapshot['tasks'])
        assert all(x['state'] == 'done' for x in snapshot['tasks'])
        vals = {k: cost['estimated_rub_' + k] for k in ('lower', 'upper')}
        for seconds in (0, 120, 180):
            vals['hypothetical_' + str(seconds) + 's'] = sum(max(0, min(r['first_absent_at'], done + seconds)
                - r['created_at']) * r['rate_rub_per_hour'] / 3600 for r in cost['resources'])
        for group in (t['variant'], t['scenario'] + '-' + t['variant']):
            for k, v in vals.items():
                groups[group][k] += v
        for worker in snapshot['workers']:
            metadata = json.loads(worker['metadata'])
            boot.append(metadata['model_load_seconds'])
        checks.append({'trial': t['trial'], 'source_run': t['source_run'],
            'snapshot_sha256': hashlib.sha256((trial / 'snapshot.json').read_bytes()).hexdigest(),
            'cost_sha256': hashlib.sha256((trial / 'cost-summary.json').read_bytes()).hexdigest()})
    for g in groups.values():
        for seconds in (120, 180):
            g['conditional_saving_' + str(seconds) + 's_percent'] = 100 * (1 - g['hypothetical_' + str(seconds) + 's'] / g['lower'])
    cleanup = []
    for directory in (pilot, ROOT / 'results/cloudru-h2-main-20261015-c', current):
        cleanup.extend(retirement_windows(directory))
    result = {'at': datetime.now(UTC).isoformat(), 'exploratory_only': True,
        'calibration_inputs': 'Original six pilot stage measurements only; no main timings fitted',
        'configs': configs, 'initial_batch_decisions': decisions,
        'calibration_interpretation': 'A tighter upper envelope alone may not remove the third VM. Lean margin is a risk probe, not a validated replacement.',
        'resource_cost_counterfactual': groups, 'cleanup_latency_observations': cleanup,
        'cold_model_load_seconds': {'n': len(boot), 'median': statistics.median(boot), 'maximum': max(boot)},
        'inputs': checks, 'sources_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in (Path(__file__), source)},
        'limitations': ['120/180-second retirement is a conditional replay, not measured autonomous scale-to-zero.',
            'Cleanup observations measure deletion, not scale-down of a retained node pool or its restart.',
            'Initial batch decisions do not simulate repeated HPA decisions or cold-start jitter.',
            'Both count and work can benefit from faster resource retirement; full-cluster fixed overhead is excluded.']}
    (output / 'analysis.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'initial_decisions': decisions, 'cleanup_observations': len(cleanup),
        'cleanup_seconds': [r['request_to_last_resource_absence_seconds_upper'] for r in cleanup],
        'model_load': result['cold_model_load_seconds']}, indent=2))


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
