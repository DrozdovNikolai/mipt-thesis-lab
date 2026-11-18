"""Verify legacy source identity without inventing a historical PCM measurement."""

import hashlib
import json
from pathlib import Path

from scripts.decoding_diagnostics import load_audio

LEGACY = {}


def same_waveform(item, record, expected_pcm):
    for key in ('audio_path', 'audio_sha256', 'duration_sec', 'input_language'):
        if record[key] != item[key]:
            raise ValueError('Historical audio request differs: ' + key)
    if record.get('gain_db', 0.) != item['gain_db']:
        raise ValueError('Historical amplitude differs')
    if 'effective_waveform_sha256' in record:
        return record['effective_waveform_sha256'] == expected_pcm
    if item['gain_db'] != 0 or record.get('gain_db', 0.) != 0:
        raise ValueError('Missing historical PCM evidence for an amplitude variant')
    config = record['config']
    if config['vad']['enabled'] or config['denoise']['enabled'] or config['redecode']:
        raise ValueError('Cannot reconstruct legacy transformed audio')
    # The legacy request contains file hash/path, not the hash of its runtime
    # buffer. Verify the retained file and reconstruct the declared preparation.
    # This deliberately does not claim that the old runtime measured PCM.
    waveform = load_audio(item)
    actual = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
    if actual != expected_pcm:
        raise ValueError('New runtime PCM differs from the legacy source file')
    LEGACY[item['id']] = {'source_audio_sha256': item['audio_sha256'],
        'reconstructed_declared_pcm_sha256': actual, 'historical_runtime_pcm_recorded': False,
        'evidence': 'Frozen source file identity and declared zero-gain preparation; reconstructed at scoring.'}
    return True


def write_legacy_evidence(path):
    Path(path).write_text(json.dumps({'records': LEGACY, 'historical_predictions_modified': False},
                                    ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
