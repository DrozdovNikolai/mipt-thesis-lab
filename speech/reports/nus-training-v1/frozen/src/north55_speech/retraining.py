"""Admission for the explicitly bounded follow-up; old pilot policy is unchanged."""

import re

from north55_speech.core import SpeechError

SUPPORT_SOURCES = {
    "openslr/librispeech_asr": ("71cacbfb7e2354c4226d01e70d77d5fca3d04ba1", "en"),
    "google/fleurs": ("70bb2e84b976b7e960aa89f1c648e09c59f894dd", "ru"),
}


def validate_mixed_sources(train, dev, config):
    from north55_speech.lora import validate_references

    if config.get("quality_evidence") is not False or config.get("selection_allowed") is not False:
        raise SpeechError("EXPLORATORY_ONLY", "Mixed training cannot certify a release")
    if config.get("max_steps") != 120 or config.get("eval_steps") != 120:
        raise SpeechError("TRAINING_BUDGET", "Follow-up uses one fixed checkpoint at 120 steps")
    weak = [s for s in train if s.transcript_status == "weak"]
    # Reuse every old provenance guard, without changing that pilot's 40-step cap.
    validate_references(weak, dev, {
        "reference_policy": "publisher_weak_exploratory_v1", "max_steps": 40,
        "quality_evidence": False, "selection_allowed": False,
    })
    validate_support_samples([s for s in train if s.transcript_status != "weak"])


def validate_support_samples(samples):
    """Validate the existing pinned EN/RU auxiliary corpora without changing their policy."""
    for s in samples:
        p = s.annotation_provenance
        expected = SUPPORT_SOURCES.get(s.source_dataset)
        hashes = [s.audio_sha256, s.decoded_audio_sha256,
                  p.get("original_audio_sha256"), p.get("acquisition_sha256")]
        if (not expected or (s.source_version, s.language) != expected
                or s.transcript_status != "human_verified" or not s.reference_text
                or s.scope != "general_control" or s.primary or s.scope_verified or s.clean_control
                or s.speech_origin != "recorded_human" or not s.rights_confirmed
                or s.license_id != "CC-BY-4.0"
                or p.get("method") != "publisher_supervised_corpus_import"
                or p.get("annotator") != s.source_dataset or p.get("source_split") != "train"
                or p.get("reviewed_audio") is not False or p.get("local_manual_verification") is not False
                or p.get("verification_scope") != "publisher_provided_human_reference_not_local_audio_audit"
                or not p.get("speaker_partition_basis")
                or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
                or any(v is not None for v in (s.labels, s.events, s.critical_entities, s.salient_for_review))
                or any(v != "missing" for v in (s.events_status, s.entities_status, s.temporal_status))):
            raise SpeechError("INVALID_SUPPORT_PAIR", "Expected pinned, train-only publisher references")
