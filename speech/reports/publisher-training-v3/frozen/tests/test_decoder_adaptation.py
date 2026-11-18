import copy

import pytest

from north55_speech.decoder_adaptation import (
    decoder_targets,
    learning_rate_multiplier,
    tensor_hashes,
    validate_decoder_plan,
    verify_trainable_decoder,
)


def plan():
    return {'quality_evidence': False, 'selection_allowed': False, 'test_accessed': False,
        'release_promoted': False, 'decoder_training': {'max_steps': 1200, 'milestones': [240, 1200],
        'initial_lr': 5e-5, 'continuation_lr': 2e-5, 'schedule': 'linear_first_240_then_constant',
        'rank': 8, 'alpha': 16, 'dropout': .05, 'seed': 55, 'train_rows': 675,
        'from_original_base': True, 'encoder_frozen': True}}


@pytest.mark.parametrize('field,value', [('encoder_frozen', False), ('max_steps', 2400),
    ('train_rows', 32), ('milestones', [240, 800]), ('from_original_base', False)])
def test_reject_protocol_drift(field, value):
    data = plan()
    data['decoder_training'][field] = value
    with pytest.raises(ValueError):
        validate_decoder_plan(data)


def test_exact_lr_boundary_and_frozen_budget():
    assert learning_rate_multiplier(0) == 1
    assert learning_rate_multiplier(239) == pytest.approx(1/240)
    assert learning_rate_multiplier(240) == learning_rate_multiplier(1200) == .4
    with pytest.raises(ValueError):
        learning_rate_multiplier(1201)
    data = plan()
    data['release_promoted'] = True
    with pytest.raises(ValueError):
        validate_decoder_plan(data)


def test_real_gradients_save_reload_merge_preserve_encoder(tmp_path):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import WhisperConfig, WhisperForConditionalGeneration

    torch.set_num_threads(2)
    torch.manual_seed(55)
    config = WhisperConfig(num_mel_bins=4, d_model=8, encoder_layers=12, decoder_layers=12,
        encoder_attention_heads=2, decoder_attention_heads=2, encoder_ffn_dim=16, decoder_ffn_dim=16,
        vocab_size=32, max_source_positions=10, max_target_positions=8,
        pad_token_id=0, bos_token_id=1, eos_token_id=2, decoder_start_token_id=1,
        suppress_tokens=[], begin_suppress_tokens=[])
    base = WhisperForConditionalGeneration(config)
    original = copy.deepcopy(base.state_dict())
    encoder = tensor_hashes(base.model.encoder)
    targets = decoder_targets(base)
    assert len(targets) == 48 and all('.decoder.' in name for name in targets)
    model = get_peft_model(base, LoraConfig(r=8, lora_alpha=16, target_modules=targets, lora_dropout=.05, bias='none'))
    assert len(verify_trainable_decoder(model)) == 96
    old_lora = {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=.001)
    for _ in range(3):
        loss = model(input_features=torch.randn(2, 4, 20), labels=torch.tensor([[3, 4, 2], [5, 6, 2]])).loss
        loss.backward()
        assert all(p.grad is None for p in model.get_base_model().model.encoder.parameters())
        optimizer.step()
        optimizer.zero_grad()
    assert tensor_hashes(model.get_base_model().model.encoder) == encoder
    assert any(not torch.equal(old_lora[n], p) for n, p in model.named_parameters() if p.requires_grad)
    model.save_pretrained(tmp_path)
    fresh = WhisperForConditionalGeneration(config)
    fresh.load_state_dict(original)
    restored = PeftModel.from_pretrained(fresh, tmp_path, local_files_only=True)
    merged = restored.merge_and_unload()
    assert tensor_hashes(merged.model.encoder) == encoder
    assert not any('lora_' in n for n, _ in merged.named_parameters())


def test_original_nus_budget_is_still_240():
    from north55_speech.core import SpeechError
    from north55_speech.nus_training import validate_nus_sources
    with pytest.raises(SpeechError, match='240'):
        validate_nus_sources([], [], {'quality_evidence': False, 'selection_allowed': False,
            'max_steps': 1200, 'eval_steps': 1200})
