"""Select an existing English ASR hypothesis by a frozen acoustic rescoring rule."""
from __future__ import annotations

import math

from north55_speech.metrics import lexical_normalizer_v1

POLICY = {
    'version': 'medium-acoustic-selection-v8',
    'switch_margin_nats_per_token': 0.10,
    'normalizer': 'lexical_normalizer_v1',
    'empty_parakeet': 'return_empty',
    'tie': 'whisper',
    'maximum_audio_seconds': 30,
}


def token_log_mean(probabilities):
    if not probabilities or any(not math.isfinite(p) or p < 0 or p > 1 for p in probabilities):
        raise ValueError('Expected nonempty finite token probabilities in [0, 1]')
    return math.fsum(math.log(max(p, 1e-30)) for p in probabilities) / len(probabilities)


def shortcut(whisper: str, parakeet: str | None, language: str):
    """No sample identifiers, cohort labels, references or noise settings are accepted."""
    if language != 'en':
        return {'selected': 'whisper', 'reason': 'non_english_passthrough'}
    if parakeet is None:
        raise ValueError('An actual Parakeet response is required for English')
    if not parakeet.strip():
        return {'selected': 'parakeet', 'reason': 'parakeet_empty'}
    if not whisper.strip():
        return {'selected': 'parakeet', 'reason': 'whisper_empty'}
    if lexical_normalizer_v1(whisper) == lexical_normalizer_v1(parakeet):
        return {'selected': 'whisper', 'reason': 'same_normalized_text'}
    return None


def select_scores(scores):
    valid = {name: value for name, value in scores.items() if value is not None}
    if not valid or any(not math.isfinite(v) for v in valid.values()):
        raise ValueError('No valid finite candidate score')
    if len(valid) == 1:
        return {'selected': next(iter(valid)), 'reason': 'only_scoreable_candidate'}
    margin = scores['parakeet'] - scores['whisper']
    selected = 'parakeet' if margin > POLICY['switch_margin_nats_per_token'] else 'whisper'
    return {'selected': selected, 'reason': 'acoustic_score', 'parakeet_margin': margin}


class AcousticSelector:
    def __init__(self, model_path, device='cuda', compute_type='float32'):
        from faster_whisper import WhisperModel
        from faster_whisper.tokenizer import Tokenizer

        self.model = WhisperModel(str(model_path), device=device, device_index=0,
            compute_type=compute_type, cpu_threads=4, num_workers=1, local_files_only=True)
        self.tokenizer = Tokenizer(self.model.hf_tokenizer, self.model.model.is_multilingual,
            task='transcribe', language='en')

    def choose(self, waveform, whisper, parakeet, language='en'):
        import numpy as np
        from faster_whisper.audio import pad_or_trim

        route = shortcut(whisper, parakeet, language)
        candidates = {'whisper': whisper, 'parakeet': parakeet}
        if route:
            return {**route, 'hypothesis': candidates[route['selected']], 'scores': {},
                'encoder_calls': 0, 'alignment_calls': 0}
        if waveform.ndim != 1 or not np.isfinite(waveform).all() or not 0 < len(waveform) <= 480000:
            raise ValueError('Rescoring requires finite mono 16 kHz audio, at most 30 seconds')
        features = self.model.feature_extractor(waveform)
        frames = min(features.shape[-1], 3000)
        encoded = self.model.encode(pad_or_trim(features))
        scores, calls = {}, 0
        limit = self.model.max_length - len(self.tokenizer.sot_sequence) - 2
        for name, text in candidates.items():
            normalized = lexical_normalizer_v1(text)
            tokens = self.tokenizer.encode(' ' + normalized) if normalized else []
            if not tokens or len(tokens) > limit:
                scores[name] = {'mean_log_probability': None, 'normalized_text': normalized,
                    'token_ids': tokens, 'reason': 'empty_or_over_context_limit'}
                continue
            result = self.model.model.align(encoded, self.tokenizer.sot_sequence,
                [tokens], frames, median_filter_width=7)[0]
            probabilities = list(result.text_token_probs)
            if len(probabilities) != len(tokens):
                raise ValueError('Alignment probability count differs from target tokens')
            scores[name] = {'normalized_text': normalized, 'token_ids': tokens,
                'token_probabilities': probabilities, 'mean_log_probability': token_log_mean(probabilities)}
            calls += 1
        route = select_scores({k: v['mean_log_probability'] for k, v in scores.items()})
        return {**route, 'hypothesis': candidates[route['selected']], 'scores': scores,
            'encoder_calls': 1, 'alignment_calls': calls}
