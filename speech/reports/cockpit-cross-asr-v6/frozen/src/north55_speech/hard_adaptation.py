"""Training admission for hard teacher pairs and acoustically linked noisy copies."""

import hashlib

from north55_speech.core import SpeechError
from north55_speech.publisher_pairs import (
    PHRASE_POLICY,
    RECOVERY_POLICY,
    validate_phrase_references,
)
from north55_speech.training import check_training_partitions

ARMS = {
    'decoder-kl': {'encoder_lora': False, 'kl_weight': 1.0},
    'decoder-ce': {'encoder_lora': False, 'kl_weight': 0.0},
    'full-ce': {'encoder_lora': True, 'kl_weight': 0.0},
}
TRAINING = {'updates': 240, 'accumulation': 4, 'learning_rate': 2e-5, 'temperature': 2.0,
    'rank': 8, 'alpha': 16, 'dropout': .05, 'seed': 55, 'precision': 'bfloat16', 'arms': ARMS,
    'checkpoint_selection': 'fixed_final_for_every_arm', 'fixed_candidate': 'full-ce'}


def validate_population(train, dev):
    check_training_partitions(train, dev)
    by_id = {s.sample_id: s for s in train}
    old = [s for s in train if s.annotation_provenance.get('method') in (PHRASE_POLICY, RECOVERY_POLICY)]
    validate_phrase_references(old, dev, {'reference_policy': RECOVERY_POLICY,
        'quality_evidence': False, 'selection_allowed': False})
    for s in train:
        p = s.annotation_provenance
        if (s.transcript_status != 'weak' or not s.reference_text or s.primary or s.scope_verified
                or s.scope != 'read_cockpit' or s.language != 'en' or s.clean_control
                or s.speech_origin != 'recorded_human' or p.get('reviewed_audio') is not False
                or p.get('annotator') or p.get('automatic_training_eligible') is not True
                or p.get('eligibility_reasons') or not 0 < s.duration_sec <= 30):
            raise SpeechError('INVALID_HARD_PAIR', 'Require traceable, unverified train-only aviation pairs')
        method = p.get('method')
        if method in (PHRASE_POLICY, RECOVERY_POLICY):
            continue
        if method == 'cockpit_hard_teacher_consensus_v4':
            if (s.variant_of or p.get('target_origin') != 'unprompted_medium_en_prediction'
                    or p.get('human_verified') is not False or p['student_difficulty']['errors'] < 2
                    or p['student_difficulty']['rate'] < .12 or p['teacher_agreement']['rate'] > .08
                    or p['publisher_support']['coverage'] < .9 or not p['publisher_support']['critical_supported']
                    or not all(len(p.get(k, '')) == 64 for k in ('small_sha256', 'medium_sha256', 'large_sha256', 'preparation_plan_sha256'))):
                raise SpeechError('INVALID_HARD_PAIR', 'Missing hard-example teacher evidence')
        elif method == 'cockpit_hard_paired_noise_v4':
            parent = by_id.get(s.variant_of)
            if (parent is None or parent.variant_of or parent.reference_text != s.reference_text
                    or parent.speaker_ids != s.speaker_ids or parent.recording_id != s.recording_id
                    or abs(parent.duration_sec-s.duration_sec) > .001
                    or (s.augmentation or {}).get('parent_link_status') != 'ACOUSTICALLY_CONFIRMED'
                    or p.get('local_coherence', 0.) < .2
                    or p.get('paired_clean_text_sha256') != hashlib.sha256(s.reference_text.encode()).hexdigest()):
                raise SpeechError('INVALID_NOISY_PAIR', 'Noisy target must preserve its linked clean parent')
        else:
            raise SpeechError('INVALID_HARD_PAIR', 'Unknown pair provenance')


def targets(model, encoder):
    names = [n for n, _ in model.named_modules() if n.startswith('model.decoder.layers.')
        and n.endswith(('.q_proj', '.v_proj'))]
    if encoder:
        names += [n for n, _ in model.named_modules() if n.startswith('model.encoder.layers.')
            and n.endswith(('.q_proj', '.v_proj'))]
    if len(names) != (72 if encoder else 48):
        raise ValueError('Unexpected Whisper-small attention architecture')
    return names
