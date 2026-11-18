from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable
from functools import lru_cache

import numpy as np

from north55_speech.audio import RATE
from north55_speech.core import SpeechError, file_hash, settings
from north55_speech.schemas import PipelineConfig, Segment, Word


def local_model_manifest(model: str) -> dict:
    if not model.replace("-", "").isalnum():
        raise SpeechError("UNSAFE_MODEL_PATH", "Model ID must be a simple local name")
    path = settings.model_root / model
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise SpeechError(
            "MODEL_NOT_AVAILABLE", "Run explicit assets fetch before offline inference"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for required in ["model.bin", "config.json", "tokenizer.json"]:
        if required not in manifest.get("files", {}) or not (path / required).is_file():
            raise SpeechError("MODEL_NOT_AVAILABLE", "Local model snapshot is incomplete")
    return manifest


def validated_model_root(model: str):
    """Resolve a complete local snapshot and verify every declared weight file."""
    manifest = local_model_manifest(model)
    root = settings.model_root / model
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != expected:
            raise SpeechError("MODEL_CHECKSUM_MISMATCH", "Local model files changed")
    return root


@lru_cache(maxsize=2)
def load_model(model: str, device: str, precision: str, manifest_hash: str):
    from faster_whisper import WhisperModel

    root = validated_model_root(model)
    try:
        return WhisperModel(
            str(root),
            device=device,
            compute_type=precision,
            local_files_only=True,
            cpu_threads=4,
            num_workers=1,
        )
    except (ValueError, RuntimeError) as e:
        raise SpeechError(
            "MODEL_LOAD_FAILED", "Model/device/precision initialization failed"
        ) from e


class AsrProvider:
    version = "faster_whisper_local_v1"

    def __init__(self, config: PipelineConfig, *, model_loader=None):
        from north55_speech.core import digest

        self.config = config
        self.manifest = local_model_manifest(config.model)
        started = time.perf_counter()
        loader = model_loader or load_model
        previous_hits = loader.cache_info().hits
        self.model = loader(
            config.model, config.device, config.compute_type, digest(self.manifest)
        )
        self.initialization_sec = time.perf_counter() - started
        self.initialization_mode = (
            "warm" if loader.cache_info().hits > previous_hits else "cold"
        )

    def options(self, language: str, retry: bool = False) -> dict:
        c = self.config
        options = {
            name: getattr(c, name)
            for name in (
                "task",
                "beam_size",
                "temperature",
                "best_of",
                "patience",
                "length_penalty",
                "repetition_penalty",
                "no_repeat_ngram_size",
                "condition_on_previous_text",
                "compression_ratio_threshold",
                "log_prob_threshold",
                "no_speech_threshold",
                "suppress_blank",
                "suppress_tokens",
                "max_initial_timestamp",
                "word_timestamps",
                "language_detection_threshold",
                "language_detection_segments",
            )
        }
        options.update(
            language=language if language in ("en", "ru") else None,
            vad_filter=False,
            initial_prompt=None,
            hotwords=c.hotwords,
            prompt_reset_on_temperature=0.5,
            prefix=None,
            without_timestamps=False,
            prepend_punctuations="\"'“¿([{-",
            append_punctuations="\"'.。,，!！?？:：”)]}、",
            max_new_tokens=None,
            chunk_length=None,
            clip_timestamps="0",
            hallucination_silence_threshold=None,
            multilingual=language == "mixed",
        )
        if retry:
            options.update(condition_on_previous_text=False, hotwords=None)
        if language == "mixed":
            # This backend exposes multilingual per-segment detection for multilingual checkpoints.
            options["multilingual"] = True
        available = inspect.signature(self.model.transcribe).parameters
        missing = set(options) - set(available)
        if missing:
            raise SpeechError(
                "UNSUPPORTED_ASR_PARAMETER", f"Backend lacks options: {sorted(missing)}"
            )
        return options

    def transcribe(
        self,
        audio: np.ndarray,
        offset_samples: int,
        language: str,
        prefix: str,
        checkpoint: Callable[[], None],
        retry: bool = False,
    ) -> list[Segment]:
        checkpoint()
        generator, info = self.model.transcribe(audio, **self.options(language, retry))
        output = []
        offset = offset_samples / RATE
        duration = len(audio) / RATE
        for index, segment in enumerate(generator):
            checkpoint()
            start = offset + min(duration, max(0, segment.start))
            end = offset + min(duration, max(segment.start, segment.end))
            words = [
                Word(
                    word=w.word,
                    start_sec=offset + min(duration, max(0, w.start)),
                    end_sec=offset + min(duration, max(w.start, w.end)),
                    probability=w.probability,
                )
                for w in (segment.words or [])
            ]
            output.append(
                Segment(
                    segment_id=f"{prefix}-{index}",
                    start_sec=start,
                    end_sec=end,
                    raw_asr_text=segment.text,
                    language="unknown" if language == "mixed" else info.language or "unknown",
                    words=words,
                    avg_logprob=segment.avg_logprob,
                    no_speech_prob=segment.no_speech_prob,
                )
            )
        return output


def redecode_uncertain(
    provider: AsrProvider,
    original: np.ndarray,
    segments: list[Segment],
    language: str,
    checkpoint: Callable[[], None],
) -> None:
    """One pass, no references; conflicting critical values always retain the first hypothesis."""
    from north55_speech.nlp import EntityExtractor

    for segment in segments:
        if (segment.avg_logprob or 0) >= provider.config.redecode_logprob_threshold:
            continue
        start = max(0, int(segment.start_sec * RATE) - RATE // 4)
        end = min(len(original), int(segment.end_sec * RATE) + RATE // 4)
        if end <= start:
            continue
        alternative = provider.transcribe(
            original[start:end],
            start,
            language,
            segment.segment_id + "-retry",
            checkpoint,
            retry=True,
        )
        text = " ".join(s.raw_asr_text for s in alternative)
        probe = Segment(
            segment_id=segment.segment_id,
            start_sec=segment.start_sec,
            end_sec=segment.end_sec,
            raw_asr_text=text,
        )
        extractor = EntityExtractor()

        def key(e):
            return (e.type, e.canonical_value, e.unit, e.polarity)

        old_entities = [key(e) for e in extractor.extract(segment)]
        new_entities = [key(e) for e in extractor.extract(probe)]
        # No silent replacement of raw model output. Selection is explicit with provenance.
        segment.alternatives.append(
            {
                "text": text,
                "segments": [s.model_dump() for s in alternative],
                "selected": False,
                "policy": "conservative_logprob_v1",
            }
        )
        if old_entities != new_entities:
            segment.risk_reasons.append("critical_value_disagreement")
            segment.risk_level = "high"
        elif (
            alternative
            and sum(s.avg_logprob or -10 for s in alternative) / len(alternative)
            > (segment.avg_logprob or -10) + 0.2
        ):
            original_output = segment.model_dump(exclude={"alternatives"})
            segment.raw_asr_text = text
            segment.words = [w for s in alternative for w in s.words]
            segment.alternatives[-1]["selected"] = True
            segment.alternatives.append({"original_first_pass": original_output, "selected": False})
