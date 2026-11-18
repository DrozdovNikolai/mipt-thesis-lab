# north55_speech: actual delivery assessment

| Gate | Status |
|---|---|
| engineering_gate | PASS |
| asr_quality_gate | NEEDS_MORE_DATA |
| nlp_quality_gate | NEEDS_MORE_DATA |
| temporal_event_gate | NEEDS_MORE_DATA |

Executed code tests: 78; integration cases: 9. See final-tests.xml.

No primary cockpit benchmark was executed. WER/F1/CI are unmeasured, not zero. Candidate is not selected; baseline remains active; release is not promoted. No EN/RU/mixed cockpit quality is validated.

The two lawful human LibriSpeech controls, generated unit fixtures, repeated long audio and GPU/CPU smoke timings are engineering evidence only. They do not satisfy the scientific gate.

```json
{
  "gates": {
    "engineering_gate": {
      "status": "PASS",
      "reasons": [],
      "checks": {
        "require_valid_cpu_compose": "PASS",
        "require_gpu_override_config_validation": "PASS",
        "require_cpu_integration_execution": "PASS",
        "require_real_asr_smoke_execution": "PASS",
        "require_migrations_and_queue_recovery_tests": "PASS",
        "require_review_audit_and_original_audio_preservation": "PASS",
        "require_privacy_and_unsafe_correction_tests": "PASS",
        "require_offline_inference_after_prefetch": "PASS"
      },
      "code_hash": "3ebe06c6b5e3d924e96623be9a6829076844c701b9692cb02eed154824ea749f",
      "test_cases": 78,
      "integration_cases": 9
    },
    "asr_quality_gate": {
      "status": "NEEDS_MORE_DATA",
      "reasons": [
        "independent_groups: 0 < 20",
        "distinct_original_human_utterances: 0 < 300",
        "reference_words: 0 < 3000",
        "human_verified_critical_entity_occurrences: 0 < 100",
        "clean_control_utterances: 0 < 50",
        "non_speech_control_minutes: 0 < 5"
      ]
    },
    "nlp_quality_gate": {
      "status": "NEEDS_MORE_DATA",
      "reasons": [
        "insufficient_evidence:independent_groups",
        "insufficient_evidence:human_verified_episodes_or_utterances",
        "insufficient_positive_support:CHECKLIST",
        "insufficient_positive_support:CONFIGURATION_MENTION",
        "insufficient_positive_support:CREW_COORDINATION",
        "insufficient_evidence:salience_positives",
        "insufficient_evidence:salience_negatives",
        "missing_human_event_labels"
      ]
    },
    "temporal_event_gate": {
      "status": "NEEDS_MORE_DATA",
      "reasons": [
        "missing_human_temporal_annotations_on_continuous_recordings"
      ]
    }
  },
  "benchmark_executed": false,
  "benchmark_execution_status": "NOT_RUN",
  "validated_scope": [],
  "supported_input_modes": [
    "en",
    "ru",
    "mixed",
    "auto"
  ],
  "deployment_candidate": "baseline",
  "release_promoted": false,
  "baseline": {
    "schema_version": "1.0",
    "name": "baseline",
    "model": "small",
    "compute_type": "int8",
    "device": "cpu",
    "task": "transcribe",
    "beam_size": 5,
    "temperature": 0.0,
    "best_of": 5,
    "patience": 1.0,
    "length_penalty": 1.0,
    "repetition_penalty": 1.0,
    "no_repeat_ngram_size": 0,
    "condition_on_previous_text": true,
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "suppress_blank": true,
    "suppress_tokens": [
      -1
    ],
    "max_initial_timestamp": 1.0,
    "word_timestamps": true,
    "language_detection_threshold": 0.5,
    "language_detection_segments": 1,
    "vad": {
      "enabled": false,
      "threshold": 0.5,
      "min_speech_duration_ms": 100,
      "min_silence_duration_ms": 400,
      "speech_pad_ms": 200,
      "max_speech_duration_s": 30.0
    },
    "denoise": {
      "enabled": false,
      "strength": 0.5,
      "floor": 0.3,
      "noise_percentile": 10.0
    },
    "hotwords": null,
    "glossary_version": null,
    "redecode": false,
    "max_redecode_passes": 1,
    "redecode_logprob_threshold": -0.8,
    "episode_gap_sec": 2.0,
    "episode_max_sec": 30.0,
    "episode_max_tokens": 100,
    "classifier": "rules_v1",
    "classifier_artifact": null
  },
  "candidate": null,
  "measurements": {
    "baseline_lexical_wer": null,
    "candidate_lexical_wer": null,
    "relative_wer_reduction": null,
    "paired_cluster_ci": null,
    "critical_entity_f1": null,
    "clean_control_wer": null,
    "nlp_rules_f1": null,
    "nlp_trained_f1": null,
    "temporal_precision": null,
    "temporal_recall": null
  },
  "admitted_primary_test_evidence": {
    "independent_groups": 0,
    "distinct_original_human_utterances": 0,
    "reference_words": 0,
    "human_verified_critical_entity_occurrences": 0,
    "clean_control_utterances": 0,
    "non_speech_control_minutes": 0
  },
  "engineering_controls": {
    "source": "LibriSpeech dev-clean CC-BY-4.0",
    "original_human_utterances": 2,
    "independent_groups": 1,
    "not_quality_evidence": true
  },
  "optional_execution": {
    "gpu": "PASS",
    "lora_dependencies": {
      "status": "PASS",
      "executed": true,
      "gpu": "NVIDIA GeForce RTX 5070 Ti",
      "torch": "2.8.0+cu128",
      "transformers": "4.57.1",
      "peft": "0.17.1",
      "trainer_import": "Seq2SeqTrainer",
      "finite_loss": true,
      "gradient_update": true,
      "adapter_save_merge": true,
      "fixture": "random_tiny_model_and_tensors",
      "real_asr_adaptation_executed": false,
      "quality_evidence": false
    },
    "lora_training": {
      "status": "BLOCKED",
      "error": {
        "code": "MISSING_TRAIN_DEV_DATA",
        "message": "Supply permitted train/dev audio-transcript data",
        "retryable": false
      },
      "executed": false
    },
    "pyannote": {
      "status": "BLOCKED",
      "reason": "accepted_terms_and_local_weights_not_supplied",
      "der": null,
      "jer": null
    }
  },
  "code_hash": "3ebe06c6b5e3d924e96623be9a6829076844c701b9692cb02eed154824ea749f",
  "scorer_hash": "987cf5b3f4f9c189b5ea31b43fb2125185918646e1b1633f1b6aee824e6ad79b",
  "acceptance_sha256": "32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071",
  "evidence_files": {
    "final-tests.xml": "5ac913bf4c4b058818dfbc1002caca9b2dc7cea119bf47876b50d1aacc804fc0",
    "final-static.log": "137dbe7ba11e30423fef2c5077462765893deff350e8aec2bce6847321bc8934",
    "migration-tests.json": "757b85379c2acc603aa11d70a9afffa8d6bbc96fa31fd767b1c93dee7f7c390f",
    "selftest-short-result.json": "a784b4af7d24cb7ecfa37ca5e9e899bb8d789727b75de437fde73e6896fb2312",
    "selftest-long-result.json": "f8a3b716f243743adabbed09291fa115841583b46be834e4a2b4ad81ed7dc12f",
    "offline-asr-smoke.json": "99787d12dfe4a1550ac5cb16b743854673f35937cdf30ff40d63b9783c0a74e4",
    "real-asr-smoke-gpu-final.json": "941dfb174ad92b9149144fc3f45dab51ce939f1d2312b39be208245d68e8ae2e",
    "compose-validation.json": "ff8d38677abd73ca819a246c4b0eaed138dc4edbf58e24aefe971fd92f139d06",
    "cli-verification.json": "22fecaed5cd1333e78bd237c5e899431a76a199f09484d0a90d2debfc7d08497",
    "data-workflow.json": "332883a9ad7beb2fde87585ba63c6f88734a477e650f60d5697b10bdf5b2b632",
    "lora-runtime.json": "b6caca361a6e3791ecfda201dbcdf50e449a4af3541d8b839c9bd79e4a216662",
    "asr-training-status.json": "2a8d619d511221e292502f397c033e2528ca6182c0389cab3f785a07b2b880fa",
    "dev-search-status.json": "5946cc0f117ebf921faf789edffd39f11aa70f606fbc7e1e53659970cd982c30",
    "baseline.lock.json": "6505e7a5004b59a0aa8ce8e7ee435363b904cd38252e10f71ce30a9823d30581"
  },
  "limitations": [
    "No independent admitted cockpit train/dev/test or human event/entity labels",
    "No final test answers opened and no dev candidate selected",
    "RU mode on English control does not validate RU ASR; no cockpit language is validated",
    "LoRA adaptation and trained NLP product quality remain unverified",
    "Browser login page inspected; authenticated workflows covered by API integration tests"
  ]
}
```
