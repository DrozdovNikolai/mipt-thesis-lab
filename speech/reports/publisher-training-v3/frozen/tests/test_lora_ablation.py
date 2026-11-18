import pytest
import torch

from north55_speech.core import SpeechError
from north55_speech.lora_ablation import partition_adapter_state


def source():
    return {f'base_model.model.model.{part}.layers.0.self_attn.q_proj.lora_{matrix}.weight':
            torch.arange(6, dtype=torch.float32).reshape((2, 3) if matrix == 'A' else (3, 2)) + 1
            for part in ('encoder', 'decoder') for matrix in ('A', 'B')}


@pytest.mark.parametrize('keep', ['encoder', 'decoder'])
def test_exact_partition_preserves_source_and_retained_delta(keep):
    original = source()
    before = {key: value.clone() for key, value in original.items()}
    result, report = partition_adapter_state(original, keep)
    for part in ('encoder', 'decoder'):
        prefix = f'base_model.model.model.{part}.layers.0.self_attn.q_proj.lora_'
        delta = result[prefix + 'B.weight'] @ result[prefix + 'A.weight']
        expected = before[prefix + 'B.weight'] @ before[prefix + 'A.weight'] if part == keep else torch.zeros_like(delta)
        assert torch.equal(delta, expected)
    assert all(torch.equal(original[k], before[k]) for k in original)
    assert all(original[k].data_ptr() != result[k].data_ptr() for k in original)
    assert len(report['zeroed_B_tensors']) == 1


@pytest.mark.parametrize('defect', ['unknown_weight', 'missing_partner', 'missing_component', 'wrong_rank'])
def test_rejects_unpartitionable_adapter(defect):
    state = source()
    if defect == 'unknown_weight':
        state['embedding.weight'] = torch.ones(2, 3)
    elif defect == 'missing_partner':
        del state[next(iter(state))]
    elif defect == 'missing_component':
        state = {k: v for k, v in state.items() if '.encoder.' in k}
    else:
        state[next(iter(state))] = torch.ones(5, 3)
    with pytest.raises(SpeechError):
        partition_adapter_state(state, 'encoder')
