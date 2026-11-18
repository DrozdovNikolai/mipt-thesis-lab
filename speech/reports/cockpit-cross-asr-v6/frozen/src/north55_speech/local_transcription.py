"""Run a measured, explicit-language recipe on a local file without a database."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from uuid import uuid4

from north55_speech.core import atomic_json, digest, file_hash, settings
from north55_speech.schemas import InferenceRequest, PipelineConfig


def config_for_language(recipe: dict[str, Any], language: str) -> PipelineConfig:
    if language not in {"auto", "en", "ru", "mixed"}:
        raise ValueError("Use auto, en, ru or mixed")
    if recipe.get("schema_version") != "1.0":
        raise ValueError("Unsupported recognition recipe")
    if "allowed_languages" in recipe and language not in recipe["allowed_languages"]:
        raise ValueError(f"This profile requires an explicit language from {recipe['allowed_languages']}")
    # This decision never reads transcripts, audio filenames or evaluation cohorts.
    return PipelineConfig.model_validate(recipe["by_language"].get(language, recipe["default"]))


def main() -> None:
    import json

    from north55_speech.asr import local_model_manifest
    from north55_speech.pipeline import run_pipeline

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--language", choices=["auto", "en", "ru", "mixed"], default="auto")
    parser.add_argument("--recipe", type=Path, default=Path("/recipe/selected.json"))
    parser.add_argument("--output", type=Path, default=Path("/output"))
    parser.add_argument("--cpu", action="store_true", help="Explicit CPU/int8 mode, different from the GPU benchmark")
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    if not source.is_file():
        raise ValueError("Input must be an audio file")
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    config = config_for_language(recipe, args.language)
    if digest(local_model_manifest(config.model)) != recipe["model_manifest_digests"][config.model]:
        raise ValueError("Recipe model manifest differs from the measured model")
    if args.cpu:
        config = config.model_copy(update={"device": "cpu", "compute_type": "int8"})
    # Settings are process-local. The pipeline still confines the locator to this folder.
    settings.audio_root = source.parent
    run_id = uuid4().hex
    work = args.output / run_id
    work.mkdir(parents=True, exist_ok=False)
    request = InferenceRequest(sample_id=run_id, audio_locator=source.name,
                               audio_sha256=file_hash(source), language=args.language)
    result = run_pipeline(request, config, work, lambda *_: None)
    result["recognition_recipe"] = {
        "sha256": file_hash(args.recipe), "source_plan_sha256": recipe["source_plan_sha256"],
        "evaluation_scope": recipe["evaluation_scope"], "explicit_language": args.language,
        "precision_matches_benchmark": not args.cpu,
    }
    atomic_json(work / "result.json", result)
    text = "\n".join(s["raw_asr_text"].strip() for s in result["segments"])
    (work / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"run_id": run_id, "model": config.model, "result": str(work / "result.json"),
                      "text": text}, ensure_ascii=False))


if __name__ == "__main__":
    main()
