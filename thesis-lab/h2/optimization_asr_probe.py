"""Short isolated CPU-thread probe; runs inside the frozen ASR image.

The real Firefly processing function and model are retained. Artifact transport
is local for every arm, so these timings are local compute evidence, not cloud
end-to-end timings. No queue or production credentials are used.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def cgroup(name):
    path = Path('/sys/fs/cgroup') / name
    return path.read_text().strip() if path.exists() else None


def main():
    start = time.perf_counter()
    from app.tasks import speech_whisperx as speech
    from scripts import speech_gpu_worker as worker
    speech._get_whisper_model()
    load_seconds = time.perf_counter() - start
    manifest = json.loads(Path('/fixtures/manifest.json').read_text())['fixtures']
    # WAV is already present in the same temporary workdir after preprocessing.
    worker._http_download = lambda url, path: None
    worker._http_put_file = lambda *args, **kwargs: None
    fixtures = ['pilot-30', 'pilot-180', 'pilot-900', 'main-30', 'main-180', 'main-900']
    if os.environ.get('PROBE_PASS') == '1':
        fixtures.reverse()
    rows = []
    for index, fixture in enumerate(['pilot-30'] + fixtures):
        with tempfile.TemporaryDirectory(prefix='h2-cost-probe-') as tmp:
            folder = Path(tmp)
            source = Path('/fixtures') / (fixture + '.wav')
            assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest[fixture]['sha256']
            before = cgroup('cpu.stat')
            started = time.perf_counter()
            speech._ffmpeg_convert_to_wav(source, folder / 'chunk.wav')
            preprocessed = time.perf_counter()
            worker._process_asr_chunk({'session_id': 'cost-probe', 'chunk_index': 0,
                'chunk_start_ms': 0, 'wav_input': {'download_url': 'local://chunk.wav'},
                'asr_output': {'upload_url': 'local://asr.json'}}, folder)
            finished = time.perf_counter()
            result = json.loads((folder / 'asr.json').read_text())
            normalized = {k: result[k] for k in ('language', 'aligned')}
            digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                                ensure_ascii=False).encode()).hexdigest()
            row = {'fixture': fixture, 'warmup': index == 0, 'result_sha': digest,
                'preprocess_seconds': preprocessed - started,
                'asr_seconds': finished - preprocessed, 'total_seconds': finished - started,
                'cpu_before': before, 'cpu_after': cgroup('cpu.stat')}
            rows.append(row)
            print('PROBE_TASK ' + json.dumps(row), flush=True)
    print('PROBE_RESULT ' + json.dumps({'variant': os.environ.get('PROBE_VARIANT'),
        'pass': int(os.environ['PROBE_PASS']), 'cpu_threads': os.environ.get('ASR_CPU_THREADS', 'library_default_4'),
        'load_seconds': load_seconds, 'rows': rows, 'cpu_max': cgroup('cpu.max'),
        'memory_peak': cgroup('memory.peak'), 'memory_events': cgroup('memory.events')}), flush=True)


if __name__ == '__main__':
    main()
