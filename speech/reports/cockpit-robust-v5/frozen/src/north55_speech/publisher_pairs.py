"""Training admission for traceable publisher-supported ASR pseudo-transcripts."""

from north55_speech.core import SpeechError

PHRASE_POLICY = "publisher_phrase_consensus_v2"
RECOVERY_POLICY = "publisher_template_recovery_v3"


def validate_phrase_references(train, dev, config):
    if config.get("quality_evidence") is not False or config.get("selection_allowed") is not False:
        raise SpeechError("EXPLORATORY_ONLY", "Machine agreement cannot certify cockpit quality")
    for sample in train + dev:
        p = sample.annotation_provenance
        if (sample.transcript_status != "weak" or not sample.reference_text or sample.primary
                or sample.scope_verified or sample.scope != "read_cockpit"
                or sample.speech_origin != "recorded_human" or not sample.rights_confirmed
                or sample.language != "en" or sample.clean_control or p.get("reviewed_audio") is not False
                or p.get("annotator") or p.get("automatic_training_eligible") is not True
                or p.get("eligibility_reasons")):
            raise SpeechError("INVALID_WEAK_PUBLISHER_PAIR", "Expected unverified exploratory cockpit pairs")
        if sample.split == "train":
            recovery = p.get("method") == RECOVERY_POLICY
            allowed = {PHRASE_POLICY, RECOVERY_POLICY} if config.get("reference_policy") == RECOVERY_POLICY else {PHRASE_POLICY}
            origin = ("cached_medium_word_span_with_two_fresh_audio_rechecks" if recovery
                      else "unprompted_medium_en_prediction")
            if (p.get("method") not in allowed or p.get("publisher_supported") is not True
                    or p.get("publisher_transcript") is not False or p.get("language_verified") is not False
                    or p.get("target_origin") != origin
                    or not all(p.get(k) for k in ("source_sha256", "document_bundle_sha256", "selection_plan_sha256",
                                                  "small_prediction_sha256", "medium_prediction_sha256"))
                    or not sample.decoded_audio_sha256):
                raise SpeechError("INVALID_WEAK_PUBLISHER_PAIR", "Missing model or publisher provenance")
            if recovery:
                match = p.get("publisher_match", {})
                if (p.get("recheck_passed") is not True or p.get("numeric_value_human_verified") is not False
                        or not all(p.get(k) for k in ("fresh_medium_sha256", "fresh_large_sha256", "parent_clip_id"))
                        or match.get("mode") not in {"literal", "alias_whole", "numeric_slot", "repeated_response", "spoken_heading"}
                        or (match.get("mode") == "numeric_slot" and
                            (not match.get("slot_numbers") or match.get("document_confirms_value") is not False))):
                    raise SpeechError("INVALID_WEAK_PUBLISHER_PAIR", "Missing fresh audio or numeric-slot evidence")
        elif (p.get("method") != "publisher_columns_and_whisper_dtw_v1"
              or p.get("publisher_transcript") is not True
              or not all(p.get(k) for k in ("source_sha256", "alignment_sha256", "preparation_plan_sha256"))):
            raise SpeechError("INVALID_WEAK_PUBLISHER_PAIR", "Expected the unchanged publisher development set")
