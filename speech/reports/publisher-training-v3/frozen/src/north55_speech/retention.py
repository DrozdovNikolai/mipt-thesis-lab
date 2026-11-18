"""Train-only, teacher-anchored adaptation; never an evaluation reference generator."""


def validate_retention_plan(plan):
    expected = {'arms': {'1': 0.0, '2': 1.0}, 'updates_per_arm': 1200,
        'learning_rate': 2e-5, 'temperature': 2.0, 'rank': 8, 'alpha': 16,
        'dropout': .05, 'seed': 55, 'train_rows': 675, 'accumulation': 4,
        'training_precision': 'bfloat16', 'encoder_frozen': True,
        'teacher': 'original_base_disabled_adapter_eval', 'fixed_candidate': 2}
    if plan.get('retention_training') != expected:
        raise ValueError('Retention protocol changed')
    if any(plan.get(k) is not False for k in ('quality_evidence', 'selection_allowed',
                                             'test_accessed', 'release_promoted')):
        raise ValueError('Diagnostic retention study cannot authorize release')
    return expected


def masked_teacher_kl(student_logits, teacher_logits, labels, temperature=2.0):
    """Mean token KL(teacher || student), excluding padding, scaled by T squared.

    Work in FP32 even under autocast. Detach the teacher explicitly; labels only
    define the valid positions and are not changed or replaced by teacher output.
    """
    import torch
    import torch.nn.functional as F

    if temperature <= 0 or student_logits.shape != teacher_logits.shape or student_logits.shape[:-1] != labels.shape:
        raise ValueError('Invalid teacher/student alignment or temperature')
    mask = labels.ne(-100)
    if not mask.any():
        raise ValueError('No supervised tokens')
    student = F.log_softmax(student_logits.float()[mask] / temperature, dim=-1)
    teacher = F.log_softmax(teacher_logits.detach().float()[mask] / temperature, dim=-1)
    loss = F.kl_div(student, teacher, log_target=True, reduction='none').sum(-1).mean() * temperature**2
    if not torch.isfinite(loss):
        raise ValueError('Nonfinite teacher KL')
    return loss


def base_teacher_logits(model, **inputs):
    """Use immutable base weights without adapter or dropout; restore student mode."""
    import torch

    was_training = model.training
    try:
        model.eval()
        with model.disable_adapter(), torch.no_grad():
            return model(**inputs).logits.detach()
    finally:
        model.train(was_training)
