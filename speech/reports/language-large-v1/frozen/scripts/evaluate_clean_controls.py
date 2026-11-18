"""Frozen general-English control for the existing A5 checkpoint adaptation.

Publisher LibriSpeech references are separate from inference inputs. This is
neither a cockpit final test nor permission to select or promote a model.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import tarfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider, local_model_manifest
from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now, read_yaml, settings
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from north55_speech.reporting import write_csv
from north55_speech.schemas import PipelineConfig

ARCHIVE_SHA256 = "76f87d090650617fca0cac8f88b9416e0ebf80350acb97b343a85fa903728ab3"
ARCHIVE_MD5 = "42e2234ba48799c1f50f24a7926300a1"
MODELS = {"parent": "whisper-small-publisher-base-ct2", "adapted": "whisper-small-publisher-lora-v2-ct2"}
MEMBER = re.compile(r"LibriSpeech/dev-clean/(\d+)/(\d+)/(\d+)-(\d+)-(\d+)\.flac")
EXCLUDED_SPEAKERS = {"2277"}  # The reader used in the two earlier smoke controls.


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def member_id(name):
    match = MEMBER.fullmatch(name)
    if not match or match[1] != match[3] or match[2] != match[4]:
        raise ValueError(f"Unsafe or inconsistent corpus audio member: {name}")
    return f"{match[3]}-{match[4]}-{match[5]}"


def choose_ids(ids, count=50):
    """Deterministic speaker-balanced sampling, without text/duration/ASR access."""
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate corpus utterance IDs")
    def rank(value):
        return hashlib.sha256(f"55:{value}".encode()).hexdigest()
    groups = defaultdict(list)
    for sample_id in ids:
        speaker = sample_id.split("-")[0]
        if speaker not in EXCLUDED_SPEAKERS:
            groups[speaker].append(sample_id)
    speakers = sorted(groups, key=rank)
    for speaker in speakers:
        groups[speaker].sort(key=rank)
    if sum(map(len, groups.values())) < count:
        raise ValueError("Insufficient eligible controls; do not substitute another cohort")
    selected, index = [], 0
    while len(selected) < count:
        for speaker in speakers:
            if index < len(groups[speaker]):
                selected.append(groups[speaker][index])
                if len(selected) == count:
                    break
        index += 1
    return selected


def identity():
    return {"script_sha256": file_hash(Path(__file__)), "code_sha256": code_hash(),
            "scorer_sha256": scorer_hash(), "acceptance_sha256": file_hash(Path("/app/ACCEPTANCE.yaml")),
            "baseline_yaml_sha256": file_hash(Path("/app/configs/baseline.yaml")),
            "uv_lock_sha256": file_hash(Path("/app/uv.lock"))}


def prepare(args):
    destination = settings.audio_root / "clean-controls-v1"
    if args.dataset.exists() or destination.exists():
        raise ValueError("Preparation is immutable; preserve existing controls and use their frozen plan")
    archive = settings.audio_root / "smoke/dev-clean.tar.gz"
    provenance = read(settings.audio_root / "smoke/provenance.json")
    if file_hash(archive) != ARCHIVE_SHA256 or provenance["acquisition"]["sha256"] != ARCHIVE_SHA256:
        raise ValueError("Cached archive differs from the previously acquired source")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "md5").hexdigest() != ARCHIVE_MD5:
            raise ValueError("Publisher archive checksum mismatch")
    config = PipelineConfig.model_validate(read_yaml(Path("/app/configs/baseline.yaml")))
    config.device, config.compute_type = "cuda", "float16"
    models = {}
    for system, name in MODELS.items():
        manifest = local_model_manifest(name)
        root = settings.model_root / name
        for filename, expected in manifest["files"].items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root.resolve()) or file_hash(path) != expected:
                raise ValueError("Model file checksum mismatch")
        models[system] = {"name": name, "manifest_sha256": file_hash(root / "manifest.json"), "manifest": manifest}
    # These weights have already been trained; this cohort cannot change them.
    adaptation = read(settings.model_root / "whisper-small-publisher-lora-v2/manifest.json")
    if adaptation["reference_policy"] != "publisher_weak_exploratory_v1":
        raise ValueError("Unexpected adaptation provenance")
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if m.name.endswith(".flac")]
        if any(not m.isfile() for m in members):
            raise ValueError("Audio archive member is not a regular file")
        ids = [member_id(m.name) for m in members]
        selected = choose_ids(ids)  # Freeze IDs before opening any transcript.
        lookup = dict(zip(ids, members, strict=True))
        args.dataset.mkdir(parents=True)
        destination.mkdir(parents=True)
        metadata = {}
        for name in ("LICENSE.TXT", "README.TXT", "SPEAKERS.TXT", "CHAPTERS.TXT", "BOOKS.TXT"):
            member = tar.getmember("LibriSpeech/" + name)
            if not member.isfile():
                raise ValueError("Metadata is not a regular file")
            path = args.dataset / name
            path.write_bytes(tar.extractfile(member).read())
            metadata[name] = file_hash(path)
        if "Attribution 4.0" not in (args.dataset / "LICENSE.TXT").read_text():
            raise ValueError("Source license differs from the inspected CC BY 4.0 license")
        speakers = {}
        for line in (args.dataset / "SPEAKERS.TXT").read_text().splitlines():
            if line.strip() and not line.startswith(";"):
                fields = [f.strip() for f in line.split("|")]
                speakers[fields[0]] = fields[2]
        items, references, transcript_metadata = [], {}, {}
        decoded_hashes = set()
        for sample_id in selected:
            speaker, chapter, _ = sample_id.split("-")
            if speakers[speaker] != "dev-clean":
                raise ValueError("Reader is outside the declared development subset")
            transcript_name = f"LibriSpeech/dev-clean/{speaker}/{chapter}/{speaker}-{chapter}.trans.txt"
            if transcript_name not in transcript_metadata:
                member = tar.getmember(transcript_name)
                if not member.isfile():
                    raise ValueError("Transcript is not a regular file")
                contents = tar.extractfile(member).read()
                transcript_metadata[transcript_name] = hashlib.sha256(contents).hexdigest()
                (args.dataset / f"{speaker}-{chapter}.trans.txt").write_bytes(contents)
                for line in contents.decode().splitlines():
                    key, text = line.split(" ", 1)
                    if key in references:
                        raise ValueError("Duplicate publisher transcript key")
                    references[key] = text
            path = destination / f"{sample_id}.flac"
            path.write_bytes(tar.extractfile(lookup[sample_id]).read())
            audio, rate = sf.read(path, dtype="float32")
            if rate != 16000 or audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
                raise ValueError("Control audio is not finite, nonempty 16 kHz mono")
            decoded_hash = hashlib.sha256(audio.tobytes()).hexdigest()
            if decoded_hash in decoded_hashes:
                raise ValueError("Decoded audio duplicate; preserve the failure without replacing its ID")
            decoded_hashes.add(decoded_hash)
            if not references.get(sample_id, "").strip():
                raise ValueError("Missing publisher reference; preserve the failure")
            items.append({"id": sample_id, "speaker_id": speaker, "chapter_id": chapter,
                          "group_id": f"librispeech-reader-{speaker}", "original_id": sample_id,
                          "audio_path": f"clean-controls-v1/{sample_id}.flac", "audio_sha256": file_hash(path),
                          "decoded_float32_sha256": decoded_hash, "duration_sec": len(audio) / rate,
                          "input_language": "en", "scope": "general_control", "primary": False})
    atomic_json(args.dataset / "references.json", {i["id"]: references[i["id"]] for i in items})
    atomic_json(args.dataset / "source.json", {
        "source": "LibriSpeech dev-clean / OpenSLR 12", "source_url": "https://www.openslr.org/12/",
        "checksum_url": "https://www.openslr.org/resources/12/md5sum.txt", "publisher_page_checked": "2026-09-14",
        "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": provenance["attribution"], "acquisition": provenance["acquisition"],
        "archive_md5_verified": ARCHIVE_MD5, "archive_sha256_verified": ARCHIVE_SHA256,
        "reference_kind": "publisher_aligned_transcript", "local_human_audio_verification": False,
        "primary": False, "scope": "general_control", "original_audio_modified": False,
        "metadata_sha256": metadata, "transcript_sha256": transcript_metadata})
    acceptance = read_yaml(Path("/app/ACCEPTANCE.yaml"))["asr_quality_gate"]
    plan = {"created_at": now().isoformat(), **identity(), "items": items, "models": models,
            "inference_config": config.model_dump(), "input_language": "en",
            "selection": {"method": "seed55_sha256_rank_speaker_round_robin_v1", "count": 50,
                          "excluded_readers": sorted(EXCLUDED_SPEAKERS), "eligible_corpus_utterances": len(ids),
                          "no_text_duration_or_asr_based_filter": True},
            "dataset_files": {p.name: file_hash(p) for p in args.dataset.iterdir() if p.is_file()},
            "guardrail": {"maximum_clean_wer_absolute_increase": acceptance["guardrails"]["maximum_clean_wer_absolute_increase"],
                          "minimum_utterances": acceptance["minimum_evidence"]["clean_control_utterances"],
                          "maximum_runtime_failures": 0},
            "uncertainty": acceptance["uncertainty"],
            "adaptation_manifest_sha256": file_hash(settings.model_root / "whisper-small-publisher-lora-v2/manifest.json"),
            "selection_allowed": False, "release_promoted": False, "cockpit_test_accessed": False,
            "limitations": ["General English audiobook speech; no cockpit, RU or mixed-language claim.",
                            "Publisher-aligned references; no new independent human listening audit.",
                            "Frozen diagnostic cohort after adaptation; no tuning on these controls.",
                            "Whisper pretraining overlap is unknown; this is not a novel-data accuracy claim."]}
    atomic_json(args.dataset / "plan.json", plan)
    print(json.dumps({"status": "FROZEN", "count": len(items), "speakers": len({i['speaker_id'] for i in items}),
                      "duration_sec": sum(i['duration_sec'] for i in items), "plan_sha256": file_hash(args.dataset / "plan.json")}))


def validate_plan(dataset):
    plan = read(dataset / "plan.json")
    if any(plan[k] != v for k, v in identity().items()):
        raise ValueError("Code, scorer, config, dependencies or acceptance changed after freeze")
    for filename, checksum in plan["dataset_files"].items():
        if Path(filename).name != filename or file_hash(dataset / filename) != checksum:
            raise ValueError("Frozen control data changed")
    for model in plan["models"].values():
        if file_hash(settings.model_root / model["name"] / "manifest.json") != model["manifest_sha256"]:
            raise ValueError("Frozen model changed")
    for item in plan["items"]:
        path = (settings.audio_root / item["audio_path"]).resolve()
        if not path.is_relative_to(settings.audio_root.resolve()) or file_hash(path) != item["audio_sha256"]:
            raise ValueError("Frozen evaluation audio changed")
    return plan


def validate_record(record, item, system, name, plan_hash):
    expected = {**item, "system": system, "model": name, "plan_sha256": plan_hash}
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("Prediction has a different frozen input or model")
    if record["runtime_failure"] is not None and record["hypothesis"] != "":
        raise ValueError("A failed run must be scored as an empty hypothesis")


def infer(args):
    plan = validate_plan(args.dataset)
    plan_hash = file_hash(args.dataset / "plan.json")
    runtime = {"plan_sha256": plan_hash, "python": platform.python_version(), "platform": platform.platform(),
               "packages": {p: importlib.metadata.version(p) for p in ("faster-whisper", "ctranslate2", "numpy", "soundfile", "jiwer")}}
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True, check=False)
    runtime["gpu_inventory"] = gpu.stdout.strip()
    runtime["cuda_visible_devices"] = __import__("os").environ.get("CUDA_VISIBLE_DEVICES")
    runtime_path = args.output / "runtime.json"
    if runtime_path.exists() and read(runtime_path) != runtime:
        raise ValueError("Resume requires the same runtime identity")
    atomic_json(runtime_path, runtime)
    for system, model in plan["models"].items():
        config = PipelineConfig.model_validate(plan["inference_config"]).model_copy(update={"model": model["name"]})
        provider, load_failure = None, None
        try:
            provider = AsrProvider(config)
            if provider.model.model.compute_type != config.compute_type or provider.model.model.device != config.device:
                raise ValueError("Actual CTranslate2 precision/device differs from the frozen comparison")
        except Exception as exc:
            provider = None
            load_failure = {"type": type(exc).__name__, "message": str(exc)}
        for item in plan["items"]:
            record_path = args.output / "predictions" / f"{system}-{item['id']}.json"
            if record_path.exists():
                validate_record(read(record_path), item, system, model["name"], plan_hash)
                continue
            started = time.perf_counter()
            record = {**item, "system": system, "model": model["name"], "plan_sha256": plan_hash,
                      "runtime_failure": load_failure, "hypothesis": "", "segments": [],
                      "effective_config": config.model_dump(), "effective_options": provider.options("en") if provider else None}
            if provider:
                try:
                    audio, rate = sf.read(settings.audio_root / item["audio_path"], dtype="float32")
                    if rate != 16000 or hashlib.sha256(audio.tobytes()).hexdigest() != item["decoded_float32_sha256"]:
                        raise ValueError("Decoded input differs from the frozen input")
                    segments = provider.transcribe(audio, 0, "en", "clean-control", lambda: None)
                    record.update(hypothesis=" ".join(s.raw_asr_text.strip() for s in segments), segments=[s.model_dump() for s in segments])
                except Exception as exc:
                    record["runtime_failure"] = {"type": type(exc).__name__, "message": str(exc)}
            record["elapsed_sec"] = time.perf_counter() - started
            atomic_json(record_path, record)
            print(json.dumps({"system": system, "id": item["id"], "failure": record["runtime_failure"]}), flush=True)
    atomic_json(args.output / "execution.json", {"plan_sha256": plan_hash,
                "prediction_sha256": {p.name: file_hash(p) for p in sorted((args.output / "predictions").glob("*.json"))}})


def clean_guardrail(parent, adapted, count, failures, guardrail):
    if count < guardrail["minimum_utterances"] or parent is None or adapted is None:
        return "NEEDS_MORE_DATA"
    if failures > guardrail["maximum_runtime_failures"] or adapted - parent > guardrail["maximum_clean_wer_absolute_increase"]:
        return "FAIL"
    return "PASS"


def score(args):
    plan = validate_plan(args.dataset)
    plan_hash = file_hash(args.dataset / "plan.json")
    references = read(args.dataset / "references.json")
    execution = read(args.output / "execution.json")
    if execution["plan_sha256"] != plan_hash or len(execution["prediction_sha256"]) != 2 * len(plan["items"]):
        raise ValueError("All frozen runs must finish before scoring")
    rows, paired = [], []
    for item in plan["items"]:
        pair = {"group_id": item["group_id"]}
        options, configs = [], []
        for system, model in plan["models"].items():
            path = args.output / "predictions" / f"{system}-{item['id']}.json"
            if file_hash(path) != execution["prediction_sha256"][path.name]:
                raise ValueError("Prediction changed after execution")
            record = read(path)
            validate_record(record, item, system, model["name"], plan_hash)
            if record["runtime_failure"] is None:
                options.append(record["effective_options"])
                configs.append({k: v for k, v in record["effective_config"].items() if k != "model"})
            counts = edit_counts(references[item["id"]], record["hypothesis"])
            rows.append({**record, "reference": references[item["id"]], "score": counts})
            pair["baseline" if system == "parent" else "candidate"] = counts
        if len(options) == 2 and (options[0] != options[1] or configs[0] != configs[1]):
            raise ValueError("Checkpoint comparison changed precision or decoding options")
        paired.append(pair)
    totals = {s: corpus_counts([r["score"] for r in rows if r["system"] == s]) for s in MODELS}
    failures = sum(r["runtime_failure"] is not None for r in rows)
    parent, adapted = (totals[s]["wer_lexical_corpus"] for s in MODELS)
    uncertainty = plan["uncertainty"]
    interval = paired_cluster_bootstrap(paired, resamples=uncertainty["resamples"], seed=uncertainty["seed"], confidence=uncertainty["confidence_level"])
    status = clean_guardrail(parent, adapted, len(plan["items"]), failures, plan["guardrail"])
    report = {"status": "EXECUTED", "clean_control_measured_guardrail": status, "scope": "general_English_diagnostic_A5_only",
              "formal_release_evidence": False, "asr_quality_gate": "NEEDS_MORE_DATA", "nlp_quality_gate": "NEEDS_MORE_DATA",
              "candidate_selected": False, "release_promoted": False, "cockpit_test_accessed": False,
              "plan_sha256": plan_hash, "samples": len(plan["items"]), "groups": len({i['group_id'] for i in plan['items']}),
              "duration_sec": sum(i['duration_sec'] for i in plan['items']), "runs": len(rows), "runtime_failures": failures,
              "scores": totals, "clean_wer_delta": adapted - parent, "maximum_clean_wer_delta": plan["guardrail"]["maximum_clean_wer_absolute_increase"],
              "paired_cluster_bootstrap": interval, "limitations": plan["limitations"], "rows": rows}
    atomic_json(args.output / "comparison.json", report)
    write_csv(args.output / "predictions.csv", ["id", "group_id", "system", "S", "D", "I", "N", "wer", "reference", "hypothesis", "elapsed_sec", "runtime_failure"], [{**r, **r["score"]} for r in rows])
    lines = ["# Контроль чистой английской речи — A5", "", f"{len(plan['items'])} записей, {report['groups']} читателей, {report['duration_sec'] / 60:.2f} мин; {len(rows)} локальных запусков, сбоев {failures}.", "",
             "| Модель | S | D | I | N | Lexical WER |", "|---|---:|---:|---:|---:|---:|"]
    for name, counts in totals.items():
        lines.append(f"| {name} | {counts['S']} | {counts['D']} | {counts['I']} | {counts['N']} | {counts['wer_lexical_corpus']:.4%} |")
    lines += ["", f"Изменение WER (LoRA − parent): **{(adapted-parent)*100:+.4f} п.п.**; допуск ACCEPTANCE: +1 п.п.",
              f"Измеренный clean-control guardrail: **{status}**. 95% paired reader-cluster bootstrap CI: [{interval['lower']:.6f}, {interval['upper']:.6f}], 2000 повторов, seed 55.", "",
              "Это отдельный A5 опыт: одна исходная Transformers модель, parent и LoRA CT2, одинаковые GPU/float16, beam=5, temperature=0, language=en. Все дополнительные стадии выключены, эталоны не передаются в inference.", "",
              "Использованы готовые издательские расшифровки [LibriSpeech dev-clean](https://www.openslr.org/12/) (CC BY 4.0). Локальное независимое прослушивание не выполнено. Выборка зафиксирована по ID до чтения текстов и ответов; reader 2277 из прежних smoke tests исключён. Сохранены все 50 пар ответов, включая ошибки.", "",
              "Общий ASR/NLP quality gate: **NEEDS_MORE_DATA**. Контроль аудиокниг не доказывает улучшение кабинной речи, RU/mixed, критических сущностей или temporal detection. Пересечение с исходным pretraining Whisper неизвестно. Candidate не выбран, release не изменён. На этих controls нельзя продолжать подбор LoRA.", ""]
    (args.output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "limitations"}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "infer", "score"))
    parser.add_argument("--dataset", type=Path, default=Path("/controls"))
    parser.add_argument("--output", type=Path, default=Path("/reports/clean-control-v1"))
    args = parser.parse_args()
    {"prepare": prepare, "infer": infer, "score": score}[args.action](args)


if __name__ == "__main__":
    main()
