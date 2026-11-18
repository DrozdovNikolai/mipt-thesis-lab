"""Admission and decisions for a train-only memorization diagnostic, never release."""

import math


def select_training_subset(samples, count=32):
    nus = [s for s in samples if s['source_dataset'] == 'NUS-SIA/CDE4301-VR-401']
    if count != 32 or len(nus) != 275:
        raise ValueError('Expected fixed 32-of-275 NUS diagnostic')
    if len({s['sample_id'] for s in nus}) != 275 or len({s['decoded_audio_sha256'] for s in nus}) != 275:
        raise ValueError('Duplicate NUS training originals')
    for sample in nus:
        if (sample['split'] != 'train' or sample['transcript_status'] != 'weak'
                or not sample['reference_text'] or not sample['rights_confirmed']
                or sample['language'] != 'en' or sample['input_language'] != 'en'
                or sample['primary'] or sample['scope_verified'] or sample['speaker_ids']
                or sample['annotation_provenance']['source_reference_conflict']
                or sample['annotation_provenance']['radio_text_indicator']):
            raise ValueError('Expected unchanged, admitted, weak NUS training pairs')
    return sorted(nus, key=lambda s: (s['audio_sha256'], s['sample_id']))[:count]


def convergence_decision(curve):
    """Only final prespecified step triggers transfer; earlier fits cannot select it."""
    if sorted(curve) != [0, 40, 120, 240]:
        raise ValueError('Incomplete prespecified learning curve')
    for value in curve.values():
        if value['runtime_failures'] or value['N'] <= 0 or not math.isfinite(value['wer_lexical_corpus']):
            return {'train_fit': 'FAIL', 'run_transfer': False, 'reason': 'invalid_or_failed_fit',
                    'release_allowed': False}
    passed = curve[240]['wer_lexical_corpus'] <= .10
    return {'train_fit': 'PASS' if passed else 'FAIL', 'run_transfer': passed,
            'reason': 'fixed_final_train_WER_at_most_0.10' if passed else 'fixed_final_train_WER_above_0.10',
            'evaluated_step': 240, 'release_allowed': False}
