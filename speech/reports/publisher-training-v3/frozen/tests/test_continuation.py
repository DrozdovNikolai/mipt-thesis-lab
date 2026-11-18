import copy

import pytest

from north55_speech.continuation import (
    permitted_transfer_steps,
    restart_learning_rate,
    validate_continuation,
)


def plan():
    return {'selected_ids': list(range(32)), 'quality_evidence': False, 'test_accessed': False,
            'release_promoted': False, 'continuation': {'source_step': 240, 'additional_steps': 400,
            'learning_rate': 2e-5, 'schedule': 'constant', 'milestones': [160, 400],
            'restore_optimizer': True, 'restore_scaler': True, 'unconditional_transfer': True,
            'source_checkpoint_files': {'optimizer.pt': 'source-hash'}, 'source_training_sha256': 'source'}}


@pytest.mark.parametrize('field,value', [('additional_steps', 401), ('learning_rate', .001),
    ('restore_optimizer', False), ('milestones', [80, 400]), ('unconditional_transfer', False)])
def test_reject_changed_phase(field, value):
    value_plan = plan()
    value_plan['continuation'][field] = value
    with pytest.raises(ValueError):
        validate_continuation(value_plan)


def test_source_and_final_only_and_original_protocol_preserved():
    assert permitted_transfer_steps(plan()) == (0, 400)
    assert permitted_transfer_steps({}) == (240,)


def test_lr_restart_preserves_real_adam_moments_and_steps():
    import torch
    parameter = torch.nn.Parameter(torch.ones(2))
    optimizer = torch.optim.AdamW([parameter], lr=5e-5)
    parameter.square().sum().backward()
    optimizer.step()
    before = copy.deepcopy(optimizer.state_dict()['state'])
    restart_learning_rate(optimizer)
    after = optimizer.state_dict()['state']
    for key in before:
        for field in before[key]:
            assert torch.equal(before[key][field], after[key][field])
    assert all(g['lr'] == 2e-5 and g['initial_lr'] == 2e-5 for g in optimizer.param_groups)


def test_no_implicit_release_or_changed_training_membership():
    value = plan()
    value['release_promoted'] = True
    with pytest.raises(ValueError):
        validate_continuation(value)
    value = plan()
    value['selected_ids'][-1] = value['selected_ids'][0]
    with pytest.raises(ValueError):
        validate_continuation(value)
