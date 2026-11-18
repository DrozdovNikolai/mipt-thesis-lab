import hashlib

import numpy as np
import pytest

from scripts import research_audio_evidence as evidence


@pytest.fixture
def request_pair(monkeypatch):
    audio = np.array([.25, -.125, 0.], dtype='float32')
    pcm = hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()
    item = {'id': 'clip', 'audio_path': 'clip.wav', 'audio_sha256': 'a'*64,
            'duration_sec': 3/16000, 'input_language': 'en', 'gain_db': 0.}
    record = {k: v for k,v in item.items() if k != 'gain_db'}
    record['config'] = {'vad': {'enabled': False}, 'denoise': {'enabled': False}, 'redecode': False}
    monkeypatch.setattr(evidence, 'load_audio', lambda value: audio)
    evidence.LEGACY.clear()
    return item, record, pcm


@pytest.mark.parametrize('matches', [False, True])
def test_existing_pcm_measurement_is_compared_without_reconstruction(request_pair, monkeypatch, matches):
    item, record, pcm = request_pair
    record['effective_waveform_sha256'] = pcm if matches else 'b'*64
    monkeypatch.setattr(evidence, 'load_audio', lambda value: pytest.fail('unexpected reconstruction'))
    assert evidence.same_waveform(item, record, pcm) is matches


def test_legacy_verification_never_fabricates_historical_measurement(request_pair):
    item, record, pcm = request_pair
    assert evidence.same_waveform(item, record, pcm)
    assert 'effective_waveform_sha256' not in record
    assert evidence.LEGACY['clip']['historical_runtime_pcm_recorded'] is False


def test_missing_pcm_on_gain_variant_is_rejected(request_pair):
    item, record, pcm = request_pair
    item['gain_db'] = record['gain_db'] = -12.
    with pytest.raises(ValueError, match='amplitude variant'):
        evidence.same_waveform(item, record, pcm)


def test_reconstructed_pcm_mismatch_is_rejected(request_pair):
    item, record, _ = request_pair
    with pytest.raises(ValueError, match='New runtime PCM differs'):
        evidence.same_waveform(item, record, 'b'*64)


@pytest.mark.parametrize('stage', ['vad', 'denoise', 'redecode'])
def test_legacy_transformation_without_pcm_is_rejected(request_pair, stage):
    item, record, pcm = request_pair
    record['config'][stage] = True if stage == 'redecode' else {'enabled': True}
    with pytest.raises(ValueError, match='transformed audio'):
        evidence.same_waveform(item, record, pcm)


@pytest.mark.parametrize('key', ['audio_path', 'audio_sha256', 'duration_sec', 'input_language'])
def test_source_identity_mismatch_is_rejected(request_pair, key):
    item, record, pcm = request_pair
    record[key] = 'changed'
    with pytest.raises(ValueError, match='Historical audio request differs'):
        evidence.same_waveform(item, record, pcm)
