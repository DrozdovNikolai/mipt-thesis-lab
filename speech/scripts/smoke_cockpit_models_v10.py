"""Technical smoke on one already exposed TRAIN clip; no evaluation references."""
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.cockpit_candidates_v10 import deep_filter, load_canary, transcribe_canary


def main():
    output = Path('/output')
    model = json.loads((output/'model-manifest.json').read_bytes())
    path = Path('/cross/input-audio/fit-269f4ee5cf035f4eb4ca0f9c62101119.wav')
    x, rate = sf.read(path, dtype='float32')
    assert rate == 16000
    y, info = deep_filter(x, Path('/models/deep-filter'))
    assert len(x) == len(y)
    # Determinism with fresh process, and a non-hop-aligned tail.
    again, _ = deep_filter(x, Path('/models/deep-filter'))
    np.testing.assert_array_equal(y, again)
    short, short_info = deep_filter(x[:-7], Path('/models/deep-filter'))
    assert len(short) == len(x)-7
    (output/'dfn-smoke.json').write_text(json.dumps({'full': info, 'partial_hop': short_info,
        'repeat_exact': True}, indent=2)+'\n')
    print({'DFN_smoke': 'PASS', 'samples': len(x), 'details': info}, flush=True)
    started = time.perf_counter()
    canary = load_canary(model['models'][0]['snapshot'])
    result = transcribe_canary(canary, x)
    result['seconds_including_load'] = time.perf_counter()-started
    result['parameter_dtypes'] = sorted({str(p.dtype) for p in canary.parameters()})
    import torch
    inputs = json.loads(Path('/app/reports/cockpit-noise-router-v9/inputs.json').read_bytes())
    longest = max((i for i in inputs if i['id'].startswith('fit-')), key=lambda i: i['duration_sec'])
    long_x, long_rate = sf.read(Path('/cross')/longest['audio_path'], dtype='float32')
    assert long_rate == 16000
    long_result = transcribe_canary(canary, long_x)
    result['long_train_smoke'] = {'id': longest['id'], 'duration_sec': len(long_x)/16000,
        **long_result, 'peak_GPU_bytes': torch.cuda.max_memory_allocated()}
    (output/'canary-smoke.json').write_text(json.dumps(result, indent=2)+'\n')
    print({'Canary_smoke': result}, flush=True)


if __name__ == '__main__':
    main()
