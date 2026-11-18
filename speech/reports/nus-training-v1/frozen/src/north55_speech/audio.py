from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy import signal

from north55_speech.core import SpeechError, StrictModel, file_hash, settings
from north55_speech.schemas import DenoiseConfig, VadConfig

RATE = 16000


class AudioInfo(StrictModel):
    sample_rate: int
    channels: int
    duration_sec: float
    container: str
    sha256: str
    channel_diagnostics: list[dict[str, Any]] = []


def probe(path: Path) -> AudioInfo:
    if path.stat().st_size > settings.max_upload_bytes:
        raise SpeechError("AUDIO_TOO_LARGE", "Audio exceeds configured byte limit")
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        meta = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        raise SpeechError("INVALID_AUDIO", "Container is corrupt or undecodable") from e
    streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise SpeechError("NO_AUDIO_TRACK", "Container has no audio track")
    if len(streams) > 1:
        raise SpeechError("MULTIPLE_AUDIO_TRACKS", "Select one audio track before upload")
    container = meta["format"].get("format_name", "")
    if not set(container.split(",")) & {"wav", "flac", "mp3", "mov", "mp4", "m4a", "ogg"}:
        raise SpeechError("UNSUPPORTED_CONTAINER", "Container is not WAV/FLAC/MP3/M4A/OGG")
    stream = streams[0]
    duration = float(stream.get("duration", meta["format"].get("duration", 0)))
    channels = int(stream.get("channels", 0))
    if not 0 < duration <= settings.max_duration_sec:
        raise SpeechError("INVALID_DURATION", "Audio duration is empty, unknown or exceeds limit")
    if not 0 < channels <= settings.max_channels:
        raise SpeechError("INVALID_CHANNELS", "Audio channel count exceeds configured limit")
    return AudioInfo(
        sample_rate=int(stream["sample_rate"]),
        channels=channels,
        duration_sec=duration,
        container=container,
        sha256=file_hash(path),
    )


class AudioPreprocessor:
    version = "ffmpeg_pcm16k_v1"

    def prepare(
        self, source: Path, output: Path, channel_mode: str
    ) -> tuple[AudioInfo, list[Path]]:
        info = probe(source)
        output.mkdir(parents=True, exist_ok=True)
        paths = []
        # Decode each channel independently, keeping originals intact and bounding peak memory.
        count = 1 if channel_mode == "mixed" else info.channels
        for channel in range(count):
            destination = output / f"channel-{channel}.wav"
            filters = [] if channel_mode == "mixed" else ["-af", f"pan=mono|c0=c{channel}"]
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-nostdin",
                        "-y",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-i",
                        str(source),
                        "-map",
                        "0:a:0",
                        *filters,
                        "-ac",
                        "1",
                        "-ar",
                        str(RATE),
                        "-t",
                        str(settings.max_duration_sec + 1),
                        "-c:a",
                        "pcm_f32le",
                        str(destination),
                    ],
                    capture_output=True,
                    check=True,
                    timeout=max(60, info.duration_sec * 2),
                )
            except subprocess.TimeoutExpired as e:
                raise SpeechError("DECODE_TIMEOUT", "Decode exceeded time limit") from e
            except subprocess.CalledProcessError as e:
                raise SpeechError("DECODE_FAILED", "Audio stream is corrupt or undecodable") from e
            with sf.SoundFile(destination) as f:
                if len(f) > (settings.max_duration_sec * RATE) or not len(f):
                    raise SpeechError(
                        "INVALID_DURATION", "Decoded duration exceeds limit or is empty"
                    )
                peak, square_sum, clipped, samples = 0.0, 0.0, 0, 0
                for block in f.blocks(blocksize=RATE * 30, dtype="float32"):
                    if not np.isfinite(block).all():
                        raise SpeechError("NONFINITE_AUDIO", "Audio contains nonfinite values")
                    peak = max(peak, float(np.abs(block).max(initial=0)))
                    square_sum += float(np.dot(block.astype(np.float64), block))
                    clipped += int(np.count_nonzero(np.abs(block) >= 0.999))
                    samples += len(block)
                info.channel_diagnostics.append(
                    {
                        "channel": channel,
                        "peak": peak,
                        "rms": (square_sum / max(samples, 1)) ** 0.5,
                        "clipping_fraction": clipped / max(samples, 1),
                        "prepared_rate": RATE,
                        "prepared_samples": samples,
                        "original_offset_sec": 0,
                        "timeline_mapping": "original_sample = prepared_sample * original_rate / 16000",
                    }
                )
            paths.append(destination)
        return info, paths


class VadProvider:
    version = "faster_whisper_silero_onnx_v1"

    def intervals(self, audio: np.ndarray, config: VadConfig) -> list[tuple[int, int]]:
        if not config.enabled:
            return [(0, len(audio))] if len(audio) else []
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        opts = VadOptions(**config.model_dump(exclude={"enabled"}))
        intervals = get_speech_timestamps(audio, opts, sampling_rate=RATE)
        # Do not concatenate separated utterances. Absolute sample indices survive every cut.
        return [(int(x["start"]), int(x["end"])) for x in intervals]


def denoise(audio: np.ndarray, config: DenoiseConfig) -> np.ndarray:
    """Conservative spectral gate, no clean reference; zero phase STFT reconstruction.

    Noise is estimated from the quiet spectral percentile of this input only.
    Blocked 30s processing keeps long recordings within bounded temporary memory.
    """
    if not config.enabled or len(audio) < 512 or not np.any(audio):
        return audio.copy()
    result = np.empty_like(audio)
    block_samples, halo = RATE * 30, 512
    for start in range(0, len(audio), block_samples):
        end = min(len(audio), start + block_samples)
        left, right = max(0, start - halo), min(len(audio), end + halo)
        _, _, stft = signal.stft(
            audio[left:right], fs=RATE, nperseg=512, noverlap=384, boundary="zeros", padded=True
        )
        magnitude = np.abs(stft)
        estimate = np.percentile(magnitude, config.noise_percentile, axis=1, keepdims=True)
        gain = np.maximum(config.floor, 1 - config.strength * estimate / (magnitude + 1e-8))
        _, cleaned = signal.istft(stft * gain, fs=RATE, nperseg=512, noverlap=384, boundary=True)
        result[start:end] = cleaned[start - left : end - left]
    return result


def channel_crosstalk(paths: list[Path]) -> list[dict[str, Any]]:
    """Detect exact/near-identical tracks; no speaker identity inference."""
    flags = []
    for a in range(len(paths)):
        for b in range(a):
            with sf.SoundFile(paths[a]) as fa, sf.SoundFile(paths[b]) as fb:
                dot = norm_a = norm_b = 0.0
                for x, y in zip(fa.blocks(RATE * 30), fb.blocks(RATE * 30), strict=False):
                    n = min(len(x), len(y))
                    dot += float(np.dot(x[:n], y[:n]))
                    norm_a += float(np.dot(x[:n], x[:n]))
                    norm_b += float(np.dot(y[:n], y[:n]))
            correlation = dot / max((norm_a * norm_b) ** 0.5, 1e-10)
            if correlation > 0.995:
                flags.append(
                    {
                        "channels": [b, a],
                        "correlation": correlation,
                        "action": "recognize_once_preserve_channel_evidence",
                    }
                )
    return flags
