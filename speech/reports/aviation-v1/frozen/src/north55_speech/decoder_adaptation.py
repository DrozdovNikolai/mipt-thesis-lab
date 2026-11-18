"""Bounded fresh decoder-only adaptation; admission is separate from release evidence."""

import hashlib


def decoder_targets(model):
    targets = [name for name, _ in model.named_modules()
               if name.startswith('model.decoder.layers.') and name.endswith(('.q_proj', '.v_proj'))]
    if len(targets) != 48:
        raise ValueError('Expected 48 Whisper-small decoder attention projections')
    return targets


def verify_trainable_decoder(model):
    names = [name for name, value in model.named_parameters() if value.requires_grad]
    if len(names) != 96 or any('.decoder.layers.' not in n or '.lora_' not in n or '.encoder.' in n for n in names):
        raise ValueError('Only 96 decoder LoRA tensors may be trainable')
    if any(p.requires_grad for p in model.get_base_model().model.encoder.parameters()):
        raise ValueError('Encoder is not frozen')
    return names


def tensor_hashes(module):
    return {name: hashlib.sha256(t.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
            for name, t in module.state_dict().items()}


def learning_rate_multiplier(completed_steps):
    if completed_steps < 0 or completed_steps > 1200:
        raise ValueError('Outside the fixed 1200-step trajectory')
    return 1 - completed_steps / 240 if completed_steps < 240 else .4


def validate_decoder_plan(plan):
    phase = plan.get('decoder_training', {})
    expected = {'max_steps': 1200, 'milestones': [240, 1200], 'initial_lr': 5e-5,
                'continuation_lr': 2e-5, 'schedule': 'linear_first_240_then_constant',
                'rank': 8, 'alpha': 16, 'dropout': .05, 'seed': 55, 'train_rows': 675,
                'from_original_base': True, 'encoder_frozen': True}
    if any(phase.get(k) != v for k, v in expected.items()):
        raise ValueError('Decoder-only run differs from its separate frozen protocol')
    if any(plan.get(k) is not False for k in ('quality_evidence', 'selection_allowed', 'test_accessed', 'release_promoted')):
        raise ValueError('This diagnostic cannot select or certify a release')
    return phase
