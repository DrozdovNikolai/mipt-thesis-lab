"""Text-only decoding that cannot reopen a tail without remaining detected speech.

This opt-in adapter targets the pinned faster-whisper 1.2.1 private loop. Serving
uses the ordinary model loader unless the caller explicitly selects this loader.
No tokens, words, numbers, or aligned timestamps are removed or rewritten here.
"""

import hashlib
import inspect
from contextvars import ContextVar
from functools import lru_cache, wraps
from importlib.metadata import version

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import get_end

from north55_speech.asr import validated_model_root
from north55_speech.audio import RATE, VadProvider
from north55_speech.core import SpeechError
from north55_speech.schemas import VadConfig
from north55_speech.vendor.faster_whisper_loop import generate_segments as guarded_segments

BACKEND_VERSION = '1.2.1'
LOOP_SHA256 = 'd6594a8b7ab423353af9b464b5383f3d04e8e692d0c8cef89fe640b9123a6be9'
TAIL_VAD = dict(enabled=True, threshold=.4, min_speech_duration_ms=50,
                min_silence_duration_ms=400, speech_pad_ms=0, max_speech_duration_s=30.)
_ACTIVE_SPEECH = ContextVar('north55_text_window_speech', default=None)
_ACTIVE_AUDIT = ContextVar('north55_text_window_audit', default=None)


def verify_backend():
    actual = hashlib.sha256(inspect.getsource(WhisperModel.generate_segments).encode()).hexdigest()
    if version('faster-whisper') != BACKEND_VERSION or actual != LOOP_SHA256:
        raise SpeechError('UNSUPPORTED_TEXT_WINDOW_BACKEND',
                          'Text-window adapter requires the audited faster-whisper loop')


class TextWindowWhisperModel(WhisperModel):
    @wraps(WhisperModel.transcribe)
    def transcribe(self, audio, *args, **kwargs):
        if not isinstance(audio, np.ndarray) or audio.ndim != 1 or not np.isfinite(audio).all():
            raise SpeechError('INVALID_TEXT_WINDOW_AUDIO', 'Adapter requires prepared finite mono 16kHz samples')
        intervals = tuple((a / RATE, b / RATE) for a, b in VadProvider().intervals(audio, VadConfig(**TAIL_VAD))) if len(audio) else ()
        generator, info = super().transcribe(audio, *args, **kwargs)
        audit = {'tail_vad': TAIL_VAD.copy(), 'speech_intervals_sec': intervals, 'decisions': []}
        if info is not None:
            info.north55_text_window_audit = audit

        def scoped():
            # Set/reset around each next(), so interleaved generators and threads
            # never share audio state. The cached backend itself is not patched.
            try:
                while True:
                    token = _ACTIVE_SPEECH.set(intervals)
                    audit_token = _ACTIVE_AUDIT.set(audit)
                    try:
                        segment = next(generator)
                    except StopIteration:
                        return
                    finally:
                        _ACTIVE_SPEECH.reset(token)
                        _ACTIVE_AUDIT.reset(audit_token)
                    yield segment
            finally:
                generator.close()
        return scoped(), info

    def generate_segments(self, features, tokenizer, options, log_progress, encoder_output=None):
        if not options.without_timestamps or options.hallucination_silence_threshold is not None:
            raise SpeechError('INVALID_TEXT_WINDOW_OPTIONS',
                              'Use text-only decoding without a second seek-changing silence heuristic')
        yield from guarded_segments(self, features, tokenizer, options, log_progress, encoder_output)

    def tail_contains_speech(self, segments, window_end_frames):
        intervals = _ACTIVE_SPEECH.get()
        if intervals is None:
            raise SpeechError('MISSING_TEXT_WINDOW_CONTEXT', 'Call transcribe() to bind the input speech intervals')
        last_end = get_end(segments)
        if last_end is None:
            return False  # The upstream loop cannot seek by absent word alignment.
        window_end = window_end_frames / self.frames_per_second
        remaining = any(end > last_end and start < window_end for start, end in intervals)
        audit = _ACTIVE_AUDIT.get()
        if audit is not None:
            audit['decisions'].append({'last_aligned_word_end_sec': last_end,
                                      'window_end_sec': window_end, 'reopen_for_remaining_speech': remaining})
        return remaining


@lru_cache(maxsize=2)
def load_text_window_model(model: str, device: str, precision: str, manifest_hash: str):
    verify_backend()
    root = validated_model_root(model)
    try:
        return TextWindowWhisperModel(str(root), device=device, compute_type=precision,
                                     local_files_only=True, cpu_threads=4, num_workers=1)
    except (ValueError, RuntimeError) as exc:
        raise SpeechError('MODEL_LOAD_FAILED', 'Text-window model initialization failed') from exc
