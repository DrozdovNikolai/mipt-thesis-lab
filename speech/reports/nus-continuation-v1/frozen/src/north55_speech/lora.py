from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from north55_speech.core import SpeechError, atomic_json, confined, file_hash, settings
from north55_speech.datasets import load_manifest
from north55_speech.training import check_training_partitions


def validate_references(train, dev, config: dict) -> str:
    """A distinct weak-label experiment must never satisfy supervised/gold admission."""
    check_training_partitions(train, dev)
    policy = config.get("reference_policy", "human_verified")
    if policy == "human_verified":
        if any(
            s.reference_text is None or s.transcript_status != "human_verified" for s in train + dev
        ):
            raise SpeechError(
                "MISSING_VERIFIED_TRANSCRIPTS", "ASR adaptation requires verified transcripts"
            )
    elif policy == "publisher_weak_exploratory_v1":
        if (
            config.get("quality_evidence") is not False
            or config.get("selection_allowed") is not False
        ):
            raise SpeechError(
                "EXPLORATORY_ONLY",
                "Weak publisher pairs cannot certify quality or select a release",
            )
        for sample in train + dev:
            provenance = sample.annotation_provenance
            if (
                sample.transcript_status != "weak"
                or not sample.reference_text
                or sample.primary
                or sample.scope_verified
                or sample.scope != "read_cockpit"
                or sample.speech_origin != "recorded_human"
                or not sample.rights_confirmed
                or sample.language != "en"
                or sample.clean_control
                or provenance.get("method") != "publisher_columns_and_whisper_dtw_v1"
                or provenance.get("publisher_transcript") is not True
                or provenance.get("automatic_training_eligible") is not True
                or provenance.get("reviewed_audio") is not False
                or provenance.get("annotator")
                or not provenance.get("source_sha256")
                or not provenance.get("alignment_sha256")
                or not provenance.get("preparation_plan_sha256")
                or provenance.get("eligibility_reasons")
            ):
                raise SpeechError(
                    "INVALID_WEAK_PUBLISHER_PAIR",
                    "Expected traceable, unverified publisher-aligned English training pairs",
                )
        if not 1 <= int(config.get("max_steps", 0)) <= 40:
            raise SpeechError(
                "TRAINING_BUDGET", "Publisher pilot experiment is bounded to 40 optimizer steps"
            )
    elif policy == "mixed_sources_exploratory_v1":
        from north55_speech.retraining import validate_mixed_sources

        validate_mixed_sources(train, dev, config)
    elif policy == "nus_sources_exploratory_v1":
        from north55_speech.nus_training import validate_nus_sources

        validate_nus_sources(train, dev, config)
    else:
        raise SpeechError("UNKNOWN_REFERENCE_POLICY", "Unknown ASR reference policy")
    if any(s.duration_sec > 30 for s in train + dev):
        raise SpeechError(
            "TRAIN_AUDIO_TOO_LONG",
            "Aligned training utterances must be <=30 seconds; no silent truncation",
        )
    return policy


def train_asr(config: dict) -> dict:
    """Real supervised Whisper LoRA, early stopping on dev, merge and CT2 conversion.

    Requires explicit local Transformers weights. No network fallback or test access.
    """
    try:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import (
            EarlyStoppingCallback,
            Seq2SeqTrainer,
            Seq2SeqTrainingArguments,
            WhisperForConditionalGeneration,
            WhisperProcessor,
            WhisperTokenizerFast,
            set_seed,
        )
    except ImportError as e:
        raise SpeechError(
            "TRAINING_DEPENDENCY_MISSING", "Build Dockerfile.train with pinned train extra"
        ) from e
    if not torch.cuda.is_available():
        raise SpeechError("GPU_NOT_AVAILABLE", "LoRA training requires a supported CUDA device")
    if torch.cuda.device_count() != 1:
        raise SpeechError(
            "SINGLE_GPU_REQUIRED",
            "Expose one supported training GPU with CUDA_VISIBLE_DEVICES; implicit DataParallel is not this protocol",
        )
    train_path, dev_path = Path(config["train_manifest"]), Path(config["dev_manifest"])
    if not train_path.exists() or not dev_path.exists():
        raise SpeechError(
            "MISSING_TRAIN_DEV_DATA", "Supply permitted train/dev audio-transcript data"
        )
    train, dev = load_manifest(train_path), load_manifest(dev_path)
    reference_policy = validate_references(train, dev, config)
    # Seed before adapter initialization, not only when Trainer is constructed.
    set_seed(55)
    model_path = confined(settings.model_root, config["base_model"], must_exist=False)
    if not (model_path / "config.json").exists():
        raise SpeechError("MODEL_NOT_AVAILABLE", "Acquire local Transformers base model explicitly")
    if not (model_path / "manifest.json").is_file():
        raise SpeechError(
            "UNVERIFIED_BASE_MODEL", "Local Transformers weights require an acquisition manifest"
        )
    base_manifest = json.loads((model_path / "manifest.json").read_text())
    if not base_manifest.get("files"):
        raise SpeechError("UNVERIFIED_BASE_MODEL", "Base model checksums are missing")
    for name, sha in base_manifest["files"].items():
        if file_hash(confined(model_path, name)) != sha:
            raise SpeechError("MODEL_CHECKSUM_MISMATCH", "Transformers base weights changed")
    processor: Any = WhisperProcessor.from_pretrained(str(model_path), local_files_only=True)
    model: Any = WhisperForConditionalGeneration.from_pretrained(str(model_path), local_files_only=True)
    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            r=int(config.get("rank", 8)),
            lora_alpha=16,
            target_modules=["q_proj", "v_proj"],
            lora_dropout=0.05,
            bias="none",
        ),
    )
    output = confined(settings.model_root, config["output"], must_exist=False)
    if output.exists():
        raise SpeechError("MODEL_VERSION_EXISTS", "Use a new training output directory")

    class AudioDataset(torch.utils.data.Dataset):
        def __init__(self, samples):
            self.samples = samples
            self.seen = Counter()

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, index):
            import librosa

            sample = self.samples[index]
            self.seen[sample.sample_id] += 1
            path = confined(settings.audio_root, sample.audio_path)
            if file_hash(path) != sample.audio_sha256:
                raise SpeechError("AUDIO_CHECKSUM_MISMATCH", "Training audio changed")
            waveform, _ = librosa.load(path, sr=16000, mono=False)
            if waveform.ndim == 2:
                if sample.channel >= len(waveform):
                    raise SpeechError("INVALID_AUDIO_CHANNEL", "Training channel is absent")
                waveform = waveform[sample.channel]
            elif sample.channel != 0:
                raise SpeechError(
                    "INVALID_AUDIO_CHANNEL", "Mono training audio has only channel zero"
                )
            features = processor.feature_extractor(waveform, sampling_rate=16000).input_features[0]
            # Language supplied by training annotations is legitimate for supervised training.
            processor.tokenizer.set_prefix_tokens(
                language=sample.language if sample.language != "mixed" else None, task="transcribe"
            )
            labels = processor.tokenizer(sample.reference_text).input_ids
            return {"input_features": features, "labels": labels}

    decoder_start_token_id = model.config.decoder_start_token_id

    def collate(items):
        features = processor.feature_extractor.pad(
            [{"input_features": x["input_features"]} for x in items], return_tensors="pt"
        )
        labels = processor.tokenizer.pad(
            [{"input_ids": x["labels"]} for x in items], return_tensors="pt"
        )
        targets = labels.input_ids.masked_fill(labels.attention_mask.ne(1), -100)
        if (targets[:, 0] == decoder_start_token_id).all().item():
            targets = targets[:, 1:]
        features["labels"] = targets
        return features

    max_steps = int(config.get("max_steps", 500))
    if not 1 <= max_steps <= 2000:
        raise SpeechError("TRAINING_BUDGET", "Training step budget must be between 1 and 2000")
    args = Seq2SeqTrainingArguments(
        output_dir=str(output / "checkpoints"),
        max_steps=max_steps,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=float(config.get("learning_rate", 1e-4)),
        fp16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        eval_strategy="steps",
        eval_steps=int(config.get("eval_steps", 25)),
        save_steps=int(config.get("eval_steps", 25)),
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        remove_unused_columns=False,
        label_names=["labels"],
        report_to=[],
        seed=55,
        dataloader_num_workers=0,
        predict_with_generate=False,
    )
    train_dataset = AudioDataset(train)
    trainer = Seq2SeqTrainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=AudioDataset(dev),
        data_collator=collate,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    train_result = trainer.train()
    validation = trainer.evaluate()
    atomic_json(output / "training-history.json", trainer.state.log_history)
    model.save_pretrained(output / "adapter")
    merged = model.merge_and_unload()
    merged.save_pretrained(output / "merged", safe_serialization=True)
    processor.save_pretrained(output / "merged")
    # WhisperProcessor may contain the slow tokenizer, which does not save tokenizer.json.
    # faster-whisper needs this local file to avoid any tokenizer download fallback.
    WhisperTokenizerFast.from_pretrained(str(model_path), local_files_only=True).save_pretrained(
        output / "merged"
    )
    from ctranslate2.converters import TransformersConverter

    converter = TransformersConverter(
        str(output / "merged"), copy_files=["tokenizer.json", "preprocessor_config.json"]
    )
    converted_path = confined(settings.model_root, config["output"] + "-ct2", must_exist=False)
    converter.convert(str(converted_path), quantization="float16")
    converted_manifest = {
        "model": converted_path.name,
        "repo": "local_lora_adaptation",
        "revision": file_hash(output / "merged" / "config.json"),
        "source_train_manifest_sha256": file_hash(train_path),
        "files": {p.name: file_hash(p) for p in converted_path.iterdir() if p.is_file()},
        "license": "inherited_base_model_and_training_data_restrictions",
        "model_comparison": "A5_separate_checkpoint",
        "reference_policy": reference_policy,
        "quality_evidence": False,
    }
    atomic_json(converted_path / "manifest.json", converted_manifest)
    # A5 is a separate checkpoint/precision conversion comparison, not an A0–A4 pipeline claim.
    manifest = {
        "kind": "asr_lora_adaptation",
        "reference_policy": reference_policy,
        "quality_evidence": False,
        "selection_allowed": False,
        "label_source": "publisher_text_with_machine_alignment"
        if reference_policy == "publisher_weak_exploratory_v1"
        else ("source_provided_NUS_references_and_publisher_supervised_general_speech"
              if reference_policy == "nus_sources_exploratory_v1"
              else "human_verified" if reference_policy == "human_verified"
              else "weak_cockpit_alignment_and_publisher_supervised_general_speech"),
        "training_coverage": {
            "unique_samples_loaded": len(train_dataset.seen),
            "total_samples": len(train),
            "sample_load_counts": dict(train_dataset.seen),
            "language_counts": dict(Counter(s.language for s in train)),
            "reference_status_counts": dict(Counter(s.transcript_status for s in train)),
            "global_optimizer_steps": trainer.state.global_step,
            "selected_checkpoint": trainer.state.best_model_checkpoint,
            "limitation": "Loader visits include possible prefetch; optimizer steps are recorded separately.",
        },
        "base_model": str(model_path),
        "base_manifest": base_manifest,
        "config": config,
        "train_sha256": file_hash(train_path),
        "dev_sha256": file_hash(dev_path),
        "train_metrics": train_result.metrics,
        "dev_metrics": validation,
        "gpu": torch.cuda.get_device_name(0),
        "converted_precision": "float16",
        "converted_model": converted_manifest,
        "files": {
            str(p.relative_to(output)): file_hash(p) for p in output.rglob("*") if p.is_file()
        },
        "converted_inference": "NOT_RUN",
        "quality_gate": "NEEDS_MORE_DATA" if reference_policy != "human_verified" else "NOT_RUN",
    }
    atomic_json(output / "manifest.json", manifest)
    # Mandatory real inference sanity check of saved converted artifact.
    from faster_whisper import WhisperModel

    del trainer, model, merged
    torch.cuda.empty_cache()
    converted = WhisperModel(
        str(converted_path), device="cuda", compute_type="float16", local_files_only=True
    )
    import librosa

    dev_audio, _ = librosa.load(
        str(confined(settings.audio_root, dev[0].audio_path)), sr=16000, mono=False
    )
    if dev_audio.ndim == 2:
        dev_audio = dev_audio[dev[0].channel]
    predictions, _ = converted.transcribe(dev_audio, beam_size=5, task="transcribe")
    manifest["converted_smoke_text"] = " ".join(segment.text for segment in predictions)
    manifest["converted_inference"] = "executed"
    atomic_json(output / "manifest.json", manifest)
    return manifest
