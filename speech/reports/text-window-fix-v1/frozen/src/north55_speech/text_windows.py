"""Text-only decoding with word alignment that cannot reopen a completed window.

This opt-in adapter targets the pinned faster-whisper 1.2.1 private loop. Serving
uses the ordinary model loader unless the caller explicitly selects this loader.
No tokens, words, numbers, or aligned timestamps are removed or rewritten here.
"""

import hashlib
import inspect
from functools import lru_cache
from importlib.metadata import version

from faster_whisper import WhisperModel

from north55_speech.asr import validated_model_root
from north55_speech.core import SpeechError

BACKEND_VERSION = '1.2.1'
LOOP_SHA256 = 'd6594a8b7ab423353af9b464b5383f3d04e8e692d0c8cef89fe640b9123a6be9'


def verify_backend():
    actual = hashlib.sha256(inspect.getsource(WhisperModel.generate_segments).encode()).hexdigest()
    if version('faster-whisper') != BACKEND_VERSION or actual != LOOP_SHA256:
        raise SpeechError('UNSUPPORTED_TEXT_WINDOW_BACKEND',
                          'Text-window adapter requires the audited faster-whisper loop')


class TextWindowWhisperModel(WhisperModel):
    def generate_segments(self, features, tokenizer, options, log_progress, encoder_output=None):
        if not options.without_timestamps or options.hallucination_silence_threshold is not None:
            raise SpeechError('INVALID_TEXT_WINDOW_OPTIONS',
                              'Use text-only decoding without a second seek-changing silence heuristic')
        yield from super().generate_segments(features, tokenizer, options, log_progress, encoder_output)

    def _split_segments_by_timestamps(self, tokenizer, tokens, time_offset,
                                     segment_size, segment_duration, seek):
        if any(token >= tokenizer.timestamp_begin for token in tokens):
            raise SpeechError('UNEXPECTED_TIMESTAMP_TOKEN', 'Text-only decoder returned timestamp tokens')
        segments, next_seek, _ = super()._split_segments_by_timestamps(
            tokenizer, tokens, time_offset, segment_size, segment_duration, seek)
        if next_seek != seek + segment_size:
            raise SpeechError('INVALID_TEXT_WINDOW_ADVANCE', 'Backend did not consume the complete text window')
        # In this pinned loop the third value only prevents alignment from moving
        # seek back to last_word_end. It adds no timestamp token or fake word end.
        # Real word alignment still runs unchanged after text generation.
        return segments, next_seek, True


@lru_cache(maxsize=2)
def load_text_window_model(model: str, device: str, precision: str, manifest_hash: str):
    verify_backend()
    root = validated_model_root(model)
    try:
        return TextWindowWhisperModel(str(root), device=device, compute_type=precision,
                                     local_files_only=True, cpu_threads=4, num_workers=1)
    except (ValueError, RuntimeError) as exc:
        raise SpeechError('MODEL_LOAD_FAILED', 'Text-window model initialization failed') from exc
