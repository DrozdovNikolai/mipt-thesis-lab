"""Prepare the complete publisher-speech-removed noise as dev-only diagnostics.

This does not grant the human-verified noise admission required by normal training
augmentation. All derived files retain provisional scope and source restrictions.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from north55_speech.core import atomic_json, file_hash, settings

NOISE_SHA256 = "dd3793b6108007b50ef10da363ef9e18b68a0953bc3f0a09ed6548b9aedde6e2"


def mix_at_snr(speech, noise, active, snr):
    if speech.shape != noise.shape or speech.shape != active.shape or not active.any():
        raise ValueError("Mixture requires aligned audio and nonempty active speech")
    rms_speech = float(np.sqrt(np.mean(speech[active].astype(np.float64) ** 2)))
    rms_noise = float(np.sqrt(np.mean(noise[active].astype(np.float64) ** 2)))
    if min(rms_speech, rms_noise) <= 0:
        raise ValueError("SNR is undefined for a silent component")
    alpha = rms_speech / rms_noise / 10 ** (snr / 20)
    mixture = speech + alpha * noise
    gain = min(1., .98 / max(float(np.max(np.abs(mixture))), 1e-12))
    actual = 20 * np.log10(rms_speech / (alpha * rms_noise))
    return (gain * mixture).astype(np.float32), {"target_snr_db": snr, "actual_active_snr_db": float(actual),
            "alpha": alpha, "mixture_gain": gain, "active_speech_rms": rms_speech, "active_noise_rms": rms_noise}


def main():
    output = Path("/voici-diagnostic")
    if (output / "plan.json").exists():
        raise ValueError("Preserve the frozen noise plan")
    source = next(Path("/voici").glob("*.wav"))
    acquisition = json.loads((Path("/voici") / "acquisition.json").read_text())
    metadata = json.loads((Path("/voici") / "source-metadata.json").read_text())
    if file_hash(source) != NOISE_SHA256 or metadata['metadata']['license']['id'] != 'cc-by-sa-4.0':
        raise ValueError("Noise checksum or license differs from inspected source")
    if acquisition['source_role'] != 'noise_only':
        raise ValueError("Unexpected source role")
    output.mkdir(parents=True, exist_ok=True)
    items = []
    with sf.SoundFile(source) as stream:
        if stream.samplerate != 48000 or stream.channels != 1:
            raise ValueError("Unexpected original audio format")
        total = stream.frames
        for start in range(0, total, 48000 * 20):
            stream.seek(start)
            original = stream.read(min(48000 * 20, total - start), dtype='float32')
            audio = resample_poly(original, 1, 3).astype(np.float32)
            if not np.isfinite(audio).all():
                raise ValueError("Invalid noise samples")
            sample_id = f"voici-2660112-{start // 48000:04d}"
            path = settings.audio_root / 'voici-diagnostic-v1' / f'{sample_id}.wav'
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                previous, rate = sf.read(path, dtype='float32')
                if rate != 16000 or not np.array_equal(previous, audio):
                    raise ValueError("Existing diagnostic audio differs")
            else:
                sf.write(path, audio, 16000, subtype='FLOAT')
            items.append({'id': sample_id, 'audio_path': str(path.relative_to(settings.audio_root)),
                          'audio_sha256': file_hash(path), 'decoded_sha256': hashlib.sha256(audio.tobytes()).hexdigest(),
                          'original_start_sec': start / 48000, 'original_end_sec': (start + len(original)) / 48000,
                          'duration_sec': len(audio) / 16000, 'rms': float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))),
                          'peak': float(np.max(np.abs(audio))), 'group_id': 'voici-original-2660112',
                          'split': 'dev', 'reference_kind': 'publisher_declared_speech_removed', 'input_language': 'auto',
                          'scope_verified': False, 'primary': False, 'human_verified': False,
                          'license_id': 'CC-BY-SA-4.0', 'condition': 'voici_noise_only'})
    atomic_json(output / 'plan.json', {
        'source': 'VOICI Zenodo 2660112', 'source_url': 'https://zenodo.org/records/2660112',
        'attribution': 'Tor Arne Reinen, SINTEF, 2019', 'license_id': 'CC-BY-SA-4.0',
        'source_sha256': NOISE_SHA256, 'source_acquisition_sha256': file_hash(Path('/voici/acquisition.json')),
        'script_sha256': file_hash(Path(__file__)), 'method': 'all_nonoverlapping_20sec_windows_including_final_tail_resample_poly_48k_to_16k',
        'source_samples': total, 'source_rate': 48000, 'duration_sec': total / 48000, 'items': items,
        'source_partition': 'dev_only_no_training_or_test_use', 'scope_basis': 'publisher says pilot, ATC and aircraft speech removed',
        'local_human_audio_verification': False, 'normal_training_augmentation_admitted': False,
        'quality_evidence': False, 'limitations': ['One noise recording from one flight', 'Publisher speech removal has no new human audit',
                                               'ASR insertions are diagnostic under the publisher empty-reference assumption']})
    print(json.dumps({'noise_chunks': len(items), 'duration_sec': total / 48000, 'group_count': 1, 'training_admitted': False}))


if __name__ == '__main__':
    main()
