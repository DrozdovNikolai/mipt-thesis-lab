import copy

import pytest

from north55_speech.retention import base_teacher_logits, masked_teacher_kl, validate_retention_plan


def test_kl_direction_mask_temperature_and_detachment():
    import torch
    s = torch.tensor([[[1., 2., 3.], [90., -90., 0.]]], requires_grad=True)
    t = torch.tensor([[[3., 2., 1.], [-90., 90., 0.]]], requires_grad=True)
    labels = torch.tensor([[2, -100]])
    actual = masked_teacher_kl(s, t, labels, 2.)
    p = (t.detach()[0, 0] / 2).softmax(-1)
    expected = (p * (p.log() - (s[0, 0] / 2).log_softmax(-1))).sum() * 4
    assert actual.item() == pytest.approx(expected.item())
    actual.backward()
    assert t.grad is None and s.grad[0, 0].abs().sum() > 0
    assert s.grad[0, 1].abs().sum() == 0
    assert masked_teacher_kl(s.detach(), s.detach(), labels).item() == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize('mode', ['empty', 'shape', 'temperature', 'nan'])
def test_reject_invalid_kl(mode):
    import torch
    s, t, labels, temp = torch.zeros(1, 2, 3), torch.zeros(1, 2, 3), torch.ones(1, 2), 2.
    if mode == 'empty':
        labels.fill_(-100)
    elif mode == 'shape':
        t = t[:, :1]
    elif mode == 'temperature':
        temp = 0
    else:
        s.fill_(float('nan'))
    with pytest.raises(ValueError):
        masked_teacher_kl(s, t, labels, temp)


def test_teacher_stays_original_after_real_adapter_updates():
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperConfig, WhisperForConditionalGeneration

    from north55_speech.decoder_adaptation import (
        decoder_targets,
        tensor_hashes,
        verify_trainable_decoder,
    )

    torch.set_num_threads(2)
    torch.manual_seed(55)
    config = WhisperConfig(num_mel_bins=4, d_model=8, encoder_layers=12, decoder_layers=12,
        encoder_attention_heads=2, decoder_attention_heads=2, encoder_ffn_dim=16, decoder_ffn_dim=16,
        vocab_size=32, max_source_positions=10, max_target_positions=8,
        pad_token_id=0, bos_token_id=1, eos_token_id=2, decoder_start_token_id=1,
        suppress_tokens=[], begin_suppress_tokens=[])
    base = WhisperForConditionalGeneration(config)
    original = copy.deepcopy(base).eval()
    before = tensor_hashes(base.model.encoder)
    model = get_peft_model(base, LoraConfig(r=8, lora_alpha=16,
        target_modules=decoder_targets(base), lora_dropout=.05, bias='none'))
    verify_trainable_decoder(model)
    inputs = {'input_features': torch.randn(1, 4, 20), 'labels': torch.tensor([[3, 4, 2]])}
    with torch.no_grad():
        expected = original(**inputs).logits
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=.01)
    model.train()
    for _ in range(3):
        teacher = base_teacher_logits(model, **inputs)
        assert model.training and not teacher.requires_grad
        torch.testing.assert_close(teacher, expected, rtol=0, atol=0)
        output = model(**inputs)
        (output.loss + masked_teacher_kl(output.logits, teacher, inputs['labels'])).backward()
        optimizer.step()
        optimizer.zero_grad()
    assert tensor_hashes(model.get_base_model().model.encoder) == before
    assert all(p.grad is None for p in model.parameters() if not p.requires_grad)
    assert {float(v['step']) for v in optimizer.state.values()} == {3.}
    model.eval()
    assert not torch.equal(model(**inputs).logits, expected)
    torch.testing.assert_close(base_teacher_logits(model, **inputs), expected, rtol=0, atol=0)
    assert not model.training


@pytest.mark.parametrize('field,value', [('release_promoted', True), ('updates_per_arm', 1201),
    ('fixed_candidate', 1), ('temperature', 1), ('arms', {'1': 0., '2': .5})])
def test_no_release_or_budget_extension(field, value):
    plan = {'quality_evidence': False, 'selection_allowed': False, 'test_accessed': False,
        'release_promoted': False, 'retention_training': {'arms': {'1': 0.0, '2': 1.0},
        'updates_per_arm': 1200, 'learning_rate': 2e-5, 'temperature': 2.0,
        'rank': 8, 'alpha': 16, 'dropout': .05, 'seed': 55, 'train_rows': 675,
        'accumulation': 4, 'training_precision': 'bfloat16', 'encoder_frozen': True,
        'teacher': 'original_base_disabled_adapter_eval', 'fixed_candidate': 2}}
    validate_retention_plan(plan)
    if field == 'release_promoted':
        plan[field] = value
    else:
        plan['retention_training'][field] = value
    with pytest.raises(ValueError):
        validate_retention_plan(plan)
