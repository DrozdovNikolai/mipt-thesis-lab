"""NUS source screening and explicit user-confirmed research admission, never gold."""

import re
from collections import defaultdict

from north55_speech.core import SpeechError
from north55_speech.retraining import validate_support_samples

SOURCE = "NUS-SIA/CDE4301-VR-401"
REVISION = "0c520edbcd345cb9005cc77c3345eedbfef7147b"
RIGHTS = "user-confirmed-project-research-2026-09-14"
GROUP = "nus-vr-entire-source-v1"
RADIO = re.compile(r"\b(?:towers?|singapore|frequency|contact|cleared|clearance)\b", re.I)


def select_nus_rows(records):
    """Conservative reference-text screening; it is not human audio-scope annotation."""
    grouped = defaultdict(list)
    for row in records:
        grouped[row["pcm_sha256"]].append(row)
    selected, excluded = [], []
    for pcm, rows in sorted(grouped.items()):
        reasons = []
        if len({row["normalized_text_sha256"] for row in rows}) > 1:
            reasons.append("conflicting_source_references")
        if any(RADIO.search(row["source_reference_text"]) for row in rows):
            reasons.append("explicit_radio_reference_indicator")
        if any(not 1 <= row["duration_sec"] <= 30 or row["sample_rate"] != 16000
               or row["channels"] != 1 or row["peak"] == 0 for row in rows):
            reasons.append("audio_contract")
        if reasons:
            excluded.append({"pcm_sha256": pcm, "rows": [row["row_id"] for row in rows],
                             "reasons": reasons})
        else:
            selected.append(min(rows, key=lambda row: row["row_id"]))
    return selected, excluded


def validate_nus_sources(train, dev, config):
    if config.get("quality_evidence") is not False or config.get("selection_allowed") is not False:
        raise SpeechError("EXPLORATORY_ONLY", "NUS source references cannot certify a release")
    if config.get("max_steps") != 240 or config.get("eval_steps") != 240:
        raise SpeechError("TRAINING_BUDGET", "One prespecified NUS checkpoint at 240 steps")
    permission = config.get("permission_evidence_sha256", "")
    validate_nus_pair_population(train, dev, permission)


def validate_nus_pair_population(train, dev, permission):
    """Check source admission independently of any particular training budget."""
    if not re.fullmatch(r"[0-9a-f]{64}", permission):
        raise SpeechError("RIGHTS_EVIDENCE_MISSING", "Record the user's source-use confirmation")
    nus = [sample for sample in train if sample.source_dataset == SOURCE]
    if not nus or any(sample.source_dataset == SOURCE for sample in dev):
        raise SpeechError("NUS_PARTITION", "The entire exposed NUS source belongs to train only")
    validate_support_samples([sample for sample in train if sample.source_dataset != SOURCE])
    for sample in nus:
        p = sample.annotation_provenance
        if (sample.source_version != REVISION or sample.license_id != RIGHTS
                or not sample.rights_confirmed or sample.transcript_status != "weak"
                or not sample.reference_text or sample.primary or sample.clean_control
                or sample.scope_verified or sample.scope != "unknown" or sample.language != "en"
                or sample.speech_origin != "recorded_human" or sample.speaker_ids
                or sample.session_id != GROUP or sample.recording_id != GROUP
                or p.get("method") != "nus_source_reference_import_v1"
                or p.get("permission_evidence_sha256") != permission
                or p.get("rights_basis") != "explicit_user_confirmation"
                or p.get("public_license_found") is not False or p.get("reviewed_audio") is not False
                or p.get("source_interval_known") is not False
                or p.get("source_start_sec") is not None or p.get("source_end_sec") is not None
                or p.get("source_reference_conflict") is not False
                or p.get("radio_text_indicator") is not False or RADIO.search(sample.reference_text)
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(p.get(key, ""))) for key in
                       ("acquisition_sha256", "private_index_sha256", "source_parquet_sha256"))
                or any(value is not None for value in
                       (sample.labels, sample.events, sample.critical_entities, sample.salient_for_review))
                or any(value != "missing" for value in
                       (sample.events_status, sample.entities_status, sample.temporal_status))):
            raise SpeechError("INVALID_NUS_PAIR", "Expected traceable, unverified, screened NUS train pair")
    # This run retains the exact pre-existing BLeRIOT dev manifest (hash checked by the driver).
    # A single final loss measurement does not turn those weak labels into human gold.
    if any(sample.transcript_status != "weak" or not sample.reference_text
           or not sample.rights_confirmed or sample.scope != "read_cockpit"
           or sample.primary or sample.scope_verified
           or sample.annotation_provenance.get("method") != "publisher_columns_and_whisper_dtw_v1"
           for sample in dev):
        raise SpeechError("INVALID_NUS_DEV", "Keep the prior weak development labels explicit")
