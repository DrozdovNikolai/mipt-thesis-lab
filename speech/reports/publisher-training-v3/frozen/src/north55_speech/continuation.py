"""Explicitly bounded optimizer continuation, separate from release selection."""


def validate_continuation(plan):
    phase = plan.get('continuation')
    required = {'source_step': 240, 'additional_steps': 400, 'learning_rate': 2e-5,
                'schedule': 'constant', 'milestones': [160, 400], 'restore_optimizer': True,
                'restore_scaler': True, 'unconditional_transfer': True}
    if not isinstance(phase, dict) or any(phase.get(k) != v for k, v in required.items()):
        raise ValueError('Continuation must match the separate fixed 400-step protocol')
    if len(plan.get('selected_ids', [])) != 32 or len(set(plan['selected_ids'])) != 32:
        raise ValueError('Continuation requires the same 32 unique training IDs')
    if not phase.get('source_checkpoint_files') or not phase.get('source_training_sha256'):
        raise ValueError('Source optimizer/checkpoint evidence is required')
    if any(plan.get(k) is not False for k in ('quality_evidence', 'test_accessed', 'release_promoted')):
        raise ValueError('Continuation cannot certify a release')
    return phase


def restart_learning_rate(optimizer, learning_rate=2e-5):
    """Keep Adam moments/steps; change only the declared phase's LR schedule."""
    if learning_rate != 2e-5:
        raise ValueError('Learning rate differs from the frozen continuation')
    for group in optimizer.param_groups:
        group['lr'] = learning_rate
        group['initial_lr'] = learning_rate


def permitted_transfer_steps(plan):
    if plan.get('continuation'):
        validate_continuation(plan)
        return (0, 400)  # Source checkpoint 240 and fixed final checkpoint 640.
    return (240,)
