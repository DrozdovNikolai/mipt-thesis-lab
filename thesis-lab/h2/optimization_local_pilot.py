"""Bounded real-ASR microbenchmark without rebuilding images or touching services."""
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

IMAGE = 'sha256:42c385b2ab9b4fedd7b6702abe7955b3ef31305c9ba254f2ba326797ad5bd302'
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'worktrees/h2-cost-pilot/firefly-backend/app/tasks/speech_whisperx.py'
PROBE = ROOT / 'h2/optimization_asr_probe.py'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    refs_path = ROOT / 'results/cloudru-h2-main-20261016-a/main/references.json'
    refs = json.loads(refs_path.read_text())
    order = [(0, 'default', None), (0, 'threads1', 1), (0, 'threads2', 2),
             (1, 'threads2', 2), (1, 'threads1', 1), (1, 'default', None)]
    plan = {'at': datetime.now(UTC).isoformat(), 'basis': 'local_real_ASR_pilot_not_cloud_benchmark',
        'image': IMAGE, 'cpus': 1.5, 'memory_bytes': 2 * 1024**3, 'network': 'none',
        'order': order, 'full_cloud_series_authorized': False,
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (SOURCE, PROBE, Path(__file__))},
        'reference_sha256': hashlib.sha256(refs_path.read_bytes()).hexdigest(),
        'maximum_seconds': 1200, 'one_container_at_a_time': True,
        'comparison': 'Only ASR_CPU_THREADS changes; OMP/MKL/OpenBLAS stay at frozen 3.',
        'model_quality_settings_unchanged': True}
    save(output / 'plan.json', plan)
    runs, started = [], time.monotonic()
    try:
        for index, (block, variant, threads) in enumerate(order):
            remaining = 1200 - (time.monotonic() - started)
            if remaining < 60:
                raise TimeoutError('Bounded local pilot window exhausted')
            name = f'ff-h2-cost-probe-1016-{index}'
            cmd = ['docker', 'run', '--rm', '--name', name, '--network', 'none',
                '--cpus', '1.5', '--memory', '2g', '--memory-swap', '2g',
                '--mount', f'type=bind,src={SOURCE},dst=/app/app/tasks/speech_whisperx.py,readonly',
                '--mount', f'type=bind,src={PROBE},dst=/probe.py,readonly',
                '-e', 'PYTHONPATH=/app', '-e', 'PROBE_VARIANT=' + variant, '-e', 'PROBE_PASS=' + str(block)]
            if threads:
                cmd += ['-e', 'ASR_CPU_THREADS=' + str(threads)]
            cmd += ['--entrypoint', 'python', IMAGE, '/probe.py']
            print(json.dumps({'phase': 'start', 'index': index, 'variant': variant, 'pass': block}), flush=True)
            try:
                completed = subprocess.run(cmd, capture_output=True, text=True, timeout=min(300, remaining))
                (output / f'{index}-{variant}.log').write_text(completed.stdout + completed.stderr)
                if completed.returncode:
                    raise RuntimeError(f'Probe failed ({completed.returncode}): see {index}-{variant}.log')
                values = [json.loads(line.removeprefix('PROBE_RESULT ')) for line in completed.stdout.splitlines()
                          if line.startswith('PROBE_RESULT ')]
                if len(values) != 1:
                    raise ValueError('Missing or ambiguous probe result')
                value = values[0]
                for row in value['rows']:
                    row['cloud_reference_match'] = row['result_sha'] == refs[row['fixture']]['sha256']
                runs.append(value)
                save(output / 'runs.json', runs)
                print(json.dumps({'phase': 'completed', 'index': index, 'variant': variant,
                    'parity': all(x['cloud_reference_match'] for x in value['rows']),
                    'long_seconds': [x['total_seconds'] for x in value['rows'] if x['fixture'].endswith('-900')],
                    'memory_peak': value['memory_peak']}), flush=True)
            finally:
                # Exact owned container only. --rm normally already removed it.
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=20)
        summaries = {}
        for variant in ('default', 'threads1', 'threads2'):
            group = [r for run in runs if run['variant'] == variant for r in run['rows'] if not r['warmup']]
            summaries[variant] = {'tasks': len(group), 'parity': all(x['cloud_reference_match'] for x in group),
                'by_audio_seconds': {str(d): {'median_seconds': statistics.median(x['total_seconds'] for x in group
                    if x['fixture'].endswith('-' + str(d))),
                    'samples_seconds': [x['total_seconds'] for x in group if x['fixture'].endswith('-' + str(d))]}
                    for d in (30, 180, 900)}}
        save(output / 'summary.json', {'completed': True, 'elapsed_seconds': time.monotonic() - started,
            'basis': plan['basis'], 'variants': summaries,
            'all_results_equal_cloud_reference': all(v['parity'] for v in summaries.values())})
    except BaseException as exc:
        save(output / 'failure.json', {'type': type(exc).__name__, 'error': str(exc)})
        raise


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
