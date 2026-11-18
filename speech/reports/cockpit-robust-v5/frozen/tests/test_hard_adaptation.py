import copy
import hashlib
from types import SimpleNamespace

import pytest

from north55_speech.core import SpeechError
from north55_speech.hard_adaptation import validate_population


def row(split):
    p = {'method': 'cockpit_hard_teacher_consensus_v4', 'reviewed_audio': False, 'annotator': None,
        'human_verified': False, 'automatic_training_eligible': True, 'eligibility_reasons': [],
        'target_origin': 'unprompted_medium_en_prediction', 'student_difficulty': {'errors': 3, 'rate': .3},
        'teacher_agreement': {'rate': 0.}, 'publisher_support': {'coverage': 1., 'critical_supported': True}}
    p.update({k: 'c'*64 for k in ('small_sha256', 'medium_sha256', 'large_sha256', 'preparation_plan_sha256')})
    if split == 'dev':
        p.update(method='publisher_columns_and_whisper_dtw_v1', publisher_transcript=True,
            source_sha256='c'*64, alignment_sha256='c'*64, preparation_plan_sha256='c'*64)
    return SimpleNamespace(sample_id=split, split=split, group_id=split, session_id=split,
        recording_id=split, original_utterance_id=split, audio_sha256=split, decoded_audio_sha256=split,
        speaker_ids=[split], transcript_status='weak', reference_text='parking brake set engine masters off',
        primary=False, scope_verified=False, scope='read_cockpit', language='en', clean_control=False,
        speech_origin='recorded_human', rights_confirmed=True, duration_sec=5., variant_of=None,
        annotation_provenance=p, augmentation=None)


def noisy(parent):
    n = copy.deepcopy(parent)
    n.sample_id = 'noisy'
    n.audio_sha256 = n.decoded_audio_sha256 = 'noise-sha'
    n.variant_of = parent.sample_id
    n.augmentation = {'parent_link_status': 'ACOUSTICALLY_CONFIRMED'}
    n.annotation_provenance.update(method='cockpit_hard_paired_noise_v4', local_coherence=.8,
        paired_clean_text_sha256=hashlib.sha256(parent.reference_text.encode()).hexdigest())
    return n


def test_hard_and_exact_paired_noisy_targets_admitted():
    t = row('train')
    validate_population([t, noisy(t)], [row('dev')])


def test_easy_student_example_is_not_admitted_as_hard():
    t = row('train')
    t.annotation_provenance['student_difficulty'] = {'errors': 0, 'rate': 0.}
    with pytest.raises(SpeechError):
        validate_population([t], [row('dev')])


@pytest.mark.parametrize('change', ['text', 'parent', 'speaker', 'link'])
def test_noisy_pair_rejects_wrong_transcript_parent_or_speaker(change):
    t = row('train')
    n = noisy(t)
    if change == 'text':
        n.reference_text += ' on'
    elif change == 'parent':
        n.variant_of = 'absent'
    elif change == 'speaker':
        n.speaker_ids = ['unrelated']
    else:
        n.augmentation['parent_link_status'] = 'REVIEW_REQUIRED'
    with pytest.raises(SpeechError):
        validate_population([t, n], [row('dev')])


def test_known_speaker_leakage_and_test_partition_rejected():
    t, d = row('train'), row('dev')
    d.speaker_ids = t.speaker_ids
    with pytest.raises(SpeechError, match='speaker'):
        validate_population([t], [d])
    d = row('dev')
    d.split = 'test'
    with pytest.raises(SpeechError):
        validate_population([t], [d])
