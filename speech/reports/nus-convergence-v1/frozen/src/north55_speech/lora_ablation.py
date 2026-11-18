"""Partition a saved Whisper attention adapter without modifying its source."""

import re
from collections import Counter

from north55_speech.core import SpeechError

KEY = re.compile(r"base_model\.model\.model\.(encoder|decoder)\.layers\.\d+\.(self_attn|encoder_attn)\.(q_proj|v_proj)\.lora_([AB])\.weight")


def partition_adapter_state(state, keep):
    """Ablate the other component by zeroing B (delta W = B @ A).

    Return independent tensors. Reject unexpected trainable weights so an
    unrecognized embedding, bias or output head cannot silently survive.
    """
    if keep not in ('encoder', 'decoder'):
        raise SpeechError('INVALID_ADAPTER_PARTITION', 'Choose encoder or decoder')
    matches = {key: KEY.fullmatch(key) for key in state}
    if not state or any(match is None for match in matches.values()):
        raise SpeechError('UNSUPPORTED_ADAPTER_KEYS', 'Expected audited Whisper q/v attention LoRA weights')
    if {match[1] for match in matches.values()} != {'encoder', 'decoder'}:
        raise SpeechError('INCOMPLETE_ADAPTER_PARTITION', 'Both components must exist in the source adapter')
    for key, match in matches.items():
        other = key.replace('.lora_A.', '.lora_B.') if match[4] == 'A' else key.replace('.lora_B.', '.lora_A.')
        if other not in state or state[key].ndim != 2:
            raise SpeechError('INCOMPLETE_ADAPTER_PARTITION', 'Every adapter matrix needs its A/B partner')
        if match[4] == 'A' and state[key].shape[0] != state[other].shape[1]:
            raise SpeechError('INVALID_ADAPTER_SHAPE', 'A/B ranks differ')
    result, zeroed = {}, []
    for key, tensor in state.items():
        result[key] = tensor.clone()
        match = matches[key]
        if match[1] != keep and match[4] == 'B':
            result[key].zero_()
            zeroed.append(key)
    return result, {'keep': keep, 'source_tensors': len(state), 'zeroed_B_tensors': zeroed,
                    'source_component_tensors': dict(Counter(m[1] for m in matches.values())),
                    'training_steps': 0, 'source_mutated': False, 'quality_evidence': False}
