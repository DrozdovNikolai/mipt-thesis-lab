from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.audio import RATE, AudioPreprocessor, VadProvider
from north55_speech.core import SpeechError, confined, digest, file_hash, settings
from north55_speech.datasets import decoded_audio_hash, load_manifest, write_manifest
from north55_speech.schemas import VadConfig


def augment(
    manifest: Path, noise_manifest: Path, output: Path, snr_db: float, seed: int = 55
) -> dict:
    """Split-preserving noisy variants using active-speech RMS and permitted noise only."""
    samples, noises = load_manifest(manifest), load_manifest(noise_manifest)
    if any(s.speech_origin != "recorded_human" for s in samples):
        raise SpeechError(
            "HUMAN_SPEECH_REQUIRED", "This augmentation path expects original recorded human speech"
        )
    if any(s.split == "unassigned" or not s.group_id for s in samples):
        raise SpeechError("SPLITS_REQUIRED", "Assign source groups before augmentation")
    if any(
        n.scope != "non_speech" or n.speech_origin != "noise" or not n.scope_verified
        for n in noises
    ):
        raise SpeechError(
            "NOISE_PROVENANCE_REQUIRED",
            "Noise recordings require verified noise-only scope and usage rights",
        )
    rng = np.random.default_rng(seed)
    variants = []
    for sample in samples:
        eligible = [n for n in noises if n.split == sample.split]
        if not eligible:
            raise SpeechError("NOISE_SPLIT_MISSING", f"No permitted noise for {sample.split} split")
        noise = eligible[int(rng.integers(len(eligible)))]
        source = confined(settings.audio_root, sample.audio_path)
        noise_source = confined(settings.audio_root, noise.audio_path)
        if (
            file_hash(source) != sample.audio_sha256
            or file_hash(noise_source) != noise.audio_sha256
        ):
            raise SpeechError("AUDIO_CHECKSUM_MISMATCH", "Source or noise changed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, speech_paths = AudioPreprocessor().prepare(
                source, root / "speech", "separate_channels"
            )
            _, noise_paths = AudioPreprocessor().prepare(noise_source, root / "noise", "mixed")
            speech, _ = sf.read(speech_paths[sample.channel], dtype="float32")
            noise_audio, _ = sf.read(noise_paths[0], dtype="float32")
        intervals = VadProvider().intervals(speech, VadConfig(enabled=True))
        active = np.zeros(len(speech), dtype=bool)
        for start, end in intervals:
            active[start:end] = True
        if not active.any():
            raise SpeechError(
                "NO_ACTIVE_SPEECH", "Active speech RMS is undefined on this recording"
            )
        offset = int(rng.integers(len(noise_audio)))
        aligned = noise_audio[(np.arange(len(speech)) + offset) % len(noise_audio)]
        speech_rms = float(np.sqrt(np.mean(speech[active].astype(np.float64) ** 2)))
        noise_rms = float(np.sqrt(np.mean(aligned[active].astype(np.float64) ** 2)))
        if noise_rms == 0:
            raise SpeechError("SILENT_NOISE", "Noise RMS is zero")
        alpha = speech_rms / (noise_rms * 10 ** (snr_db / 20))
        mixture = speech + alpha * aligned
        gain = min(1, 0.98 / max(float(np.abs(mixture).max()), 1e-12))
        mixture *= gain
        variant_id = digest(
            {
                "parent": sample.sample_id,
                "noise": noise.sample_id,
                "seed": seed,
                "offset": offset,
                "snr_db": snr_db,
            }
        )
        locator = f"datasets/{variant_id}/original.wav"
        destination = confined(settings.audio_root, locator, False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(destination, mixture, RATE, subtype="FLOAT")
        variant = sample.model_copy(deep=True)
        variant.sample_id = variant_id
        variant.variant_of = sample.sample_id
        variant.audio_path = locator
        variant.channel = 0
        variant.audio_sha256 = file_hash(destination)
        variant.decoded_audio_sha256 = decoded_audio_hash([destination])
        variant.acoustic_condition = f"synthetic_noise_{snr_db:g}dB"
        variant.primary = False
        variant.clean_control = False
        variant.transcript_status = "weak"
        variant.entities_status = "weak" if variant.critical_entities is not None else "missing"
        variant.events_status = "weak" if variant.labels is not None else "missing"
        variant.temporal_status = "weak" if variant.events is not None else "missing"
        variant.annotation_provenance = {
            "inherited_from": sample.sample_id,
            "reviewed_audio": False,
            "reason": "Noisy variant must be listened to and verified separately",
        }
        variant.augmentation = {
            "noise_source": noise.sample_id,
            "noise_sha256": noise.audio_sha256,
            "noise_split": noise.split,
            "seed": seed,
            "offset_sample": offset,
            "snr_db": snr_db,
            "alpha": alpha,
            "mixture_gain": gain,
            "active_speech_rms": speech_rms,
            "active_noise_rms": noise_rms,
        }
        variants.append(variant)
    if output.exists():
        raise SpeechError("MANIFEST_EXISTS", "Augmentation writes a new manifest revision")
    write_manifest(output, samples + variants)
    return {
        "variants": len(variants),
        "output": str(output),
        "speech_origin": "recorded_human_with_synthetic_noise",
        "real_flight_generalization": False,
    }
