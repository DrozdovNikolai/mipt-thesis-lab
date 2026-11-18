from __future__ import annotations

import json
import platform
import resource
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import soundfile as sf

from north55_speech.asr import AsrProvider, local_model_manifest, redecode_uncertain
from north55_speech.audio import RATE, AudioPreprocessor, VadProvider, channel_crosstalk, denoise
from north55_speech.core import SpeechError, atomic_json, confined, digest, file_hash, settings
from north55_speech.diarization import DiarizationProvider
from north55_speech.nlp import EpisodeBuilder, TextNormalizer
from north55_speech.schemas import InferenceRequest, PipelineConfig, Segment


def run_pipeline(
    request: InferenceRequest,
    config: PipelineConfig,
    work_dir: Path,
    progress: Callable[[str, float], None],
) -> dict:
    start = time.perf_counter()
    source = confined(settings.audio_root, request.audio_locator)
    if file_hash(source) != request.audio_sha256:
        raise SpeechError("AUDIO_CHECKSUM_MISMATCH", "Original audio checksum changed")
    manifest = local_model_manifest(config.model)
    progress("audio_validation", 0.02)
    mode = "separate_channels" if request.audio_channel is not None else request.channel_mode
    info, paths = AudioPreprocessor().prepare(source, work_dir / "prepared", mode)
    if request.audio_channel is not None and request.audio_channel >= len(paths):
        raise SpeechError("INVALID_AUDIO_CHANNEL", "Requested source channel does not exist")
    if any(i >= info.channels for i in request.channel_mapping):
        raise SpeechError("INVALID_CHANNEL_MAPPING", "Mapping refers to an absent channel")
    progress("model_loading", 0.08)
    provider = AsrProvider(config)
    source_root = Path(__file__).parent
    component_hashes = {
        name: file_hash(source_root / name)
        for name in (
            "audio.py",
            "asr.py",
            "nlp.py",
            "diarization.py",
            "pipeline.py",
            "training.py",
            "schemas.py",
        )
    }
    classifier_manifest = None
    if config.classifier_artifact:
        classifier_path = (
            confined(settings.model_root, config.classifier_artifact, must_exist=False)
            / "manifest.json"
        )
        if classifier_path.exists():
            classifier_manifest = file_hash(classifier_path)
    cache_key = digest(
        {
            "audio": request.audio_sha256,
            "config": config.model_dump(),
            "model": manifest,
            "stage": "pipeline_v1",
            "component_hashes": component_hashes,
            "classifier_manifest_sha256": classifier_manifest,
            "request": request.model_dump(),
        }
    )
    cache_root = work_dir.parent / "cache"
    cache = cache_root / f"pipeline-{cache_key}.json"
    if cache.is_file():
        progress("cached", 0.9)
        return json.loads(cache.read_text(encoding="utf-8")) | {"cache_hit": True}
    cross = channel_crosstalk(paths)
    redundant = {x["channels"][1] for x in cross}
    segments, intervals_log, asr_sec = [], [], 0.0
    for channel, path in enumerate(paths):
        if request.audio_channel is not None and channel != request.audio_channel:
            continue
        if channel in redundant and request.audio_channel is None:
            continue
        audio, _ = sf.read(path, dtype="float32")
        progress("vad", 0.1)
        intervals = VadProvider().intervals(audio, config.vad)
        asr_audio = denoise(audio, config.denoise)
        if config.denoise.enabled:
            sf.write(work_dir / f"denoised-{channel}.wav", asr_audio, RATE, subtype="FLOAT")
        for index, (begin, end) in enumerate(intervals):
            stage_progress = 0.1 + 0.7 * (channel + end / max(1, len(audio))) / len(paths)

            def checkpoint(p=stage_progress):
                progress("asr", p)

            before = time.perf_counter()
            chunk_key = digest(
                {
                    "pipeline": cache_key,
                    "stage": "asr_chunk_v1",
                    "channel": channel,
                    "begin": begin,
                    "end": end,
                }
            )
            chunk_cache = cache_root / f"chunk-{chunk_key}.json"
            checkpoint()
            if chunk_cache.exists():
                found = [Segment.model_validate(s) for s in json.loads(chunk_cache.read_text())]
            else:
                found = provider.transcribe(
                    asr_audio[begin:end],
                    begin,
                    request.language,
                    f"ch{channel}-chunk{index}",
                    checkpoint,
                )
                atomic_json(chunk_cache, [s.model_dump() for s in found])
                checkpoint()
            asr_sec += time.perf_counter() - before
            intervals_log.append(
                {
                    "channel": channel,
                    "start_sample_16k": begin,
                    "end_sample_16k": end,
                    "original_start_sec": begin / RATE,
                    "original_end_sec": end / RATE,
                    "original_sample_rate": info.sample_rate,
                }
            )
            for segment in found:
                segment.channel = channel if mode != "mixed" else None
                identity = request.channel_mapping.get(channel)
                if identity:
                    segment.speaker_id = identity.speaker_id
                    segment.role = identity.role
                    segment.role_provenance = identity.provenance
                if cross:
                    segment.risk_reasons.append("crosstalk_detected")
                if info.channel_diagnostics[channel]["clipping_fraction"] > 0.01:
                    segment.risk_reasons.append("clipping")
            if config.redecode:
                before = time.perf_counter()
                redecode_uncertain(provider, asr_audio, found, request.language, checkpoint)
                asr_sec += time.perf_counter() - before
            segments.extend(found)
        del audio, asr_audio
    progress("diarization", 0.82)
    if request.diarization == "pyannote_local" and len(paths) > 1 and request.audio_channel is None:
        diarization = {
            "status": "blocked",
            "reason": "LOCAL_DIARIZATION_REQUIRES_MIXED_OR_SELECTED_CHANNEL",
            "der": None,
            "jer": None,
        }
    else:
        diarization = DiarizationProvider().apply(
            paths[request.audio_channel or 0], segments, request.diarization
        )
    progress("nlp", 0.88)
    for segment in segments:
        TextNormalizer().normalize(segment)
    classifier = None
    classifier_status = {
        "status": "baseline",
        "version": "rules_v1",
        "trained": False,
        "reason": "missing_event_labels_or_trained_artifact",
    }
    if config.classifier == "tfidf_logreg_v1":
        from north55_speech.training import TrainedEventClassifier

        classifier = TrainedEventClassifier.load(config.classifier_artifact)
        classifier_status = {"status": "completed", "version": classifier.version, "trained": True}
    events = EpisodeBuilder().build(segments, config, classifier)
    elapsed = time.perf_counter() - start
    hardware = {
        "cpu_count": psutil.cpu_count(),
        "memory_total_bytes": psutil.virtual_memory().total,
    }
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        hardware["cpu_model"] = next(
            (
                line.split(":", 1)[1].strip()
                for line in cpuinfo.read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        )
    if config.device == "cuda":
        try:
            gpu = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,uuid,driver_version,memory.used",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            hardware["gpu_inventory_and_observed_memory"] = gpu.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            hardware["gpu_inventory_and_observed_memory"] = "unavailable"
    result = {
        "schema_version": "1.0",
        "sample_id": request.sample_id,
        "pipeline_version": "0.1.0",
        "config_hash": config.config_hash,
        "quality_gate_status": "NOT_RUN",
        "deployment_candidate": "baseline" if config.name == "baseline" else "research_preview",
        "validated_scope": [],
        "revision": 0,
        "component_statuses": {
            "asr": {"status": "completed"},
            "diarization": diarization,
            "nlp": classifier_status,
        },
        "segments": [s.model_dump() for s in sorted(segments, key=lambda s: s.start_sec)],
        "events": [e.model_dump() for e in events],
        "audio": info.model_dump(),
        "timeline": intervals_log,
        "crosstalk": cross,
        "effective_config": config.model_dump(),
        "effective_asr_options": provider.options(request.language),
        "model_manifest": manifest,
        "component_hashes": component_hashes,
        "cache_key": cache_key,
        "cache_hit": False,
        "timing": {
            "end_to_end_sec": elapsed,
            "asr_sec": asr_sec,
            "model_initialization_sec": provider.initialization_sec,
            "initialization_mode": provider.initialization_mode,
            "end_to_end_rtf": elapsed / info.duration_sec,
            "asr_rtf": asr_sec / info.duration_sec,
        },
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "device": config.device,
            "precision": config.compute_type,
            "rss_bytes": psutil.Process().memory_info().rss,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "hardware": hardware,
        },
        "summary": f"{len(events)} draft speech episodes; human review required.",
    }
    progress("persisting", 0.95)
    atomic_json(cache, result)
    progress("persisting", 0.98)
    return result
