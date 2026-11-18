"""Offline, reference-isolated comparison of fixed recognition policies."""

import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
import time
from collections import Counter
from pathlib import Path, PurePosixPath

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash, now


SMALL = "whisper-small-publisher-base-ct2"
LARGE = "whisper-large-v3-systran-ct2"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def pcm_hash(waveform):
    return hashlib.sha256(np.asarray(waveform, dtype="<f4").tobytes()).hexdigest()


def load_input(item):
    path = Path(item["audio_path"])
    if not path.is_absolute():
        path = Path("/audio") / path
    if file_hash(path) != item["audio_sha256"]:
        raise ValueError("Input audio checksum mismatch")
    waveform, rate = sf.read(path, dtype="float32")
    if rate != 16000 or waveform.ndim != 1 or not np.isfinite(waveform).all():
        raise ValueError("Expected finite mono 16 kHz audio")
    if abs(len(waveform) / rate - item["duration_sec"]) > .02:
        raise ValueError("Input duration mismatch")
    if item.get("gain_db", 0):
        waveform = waveform * np.float32(10 ** (item["gain_db"] / 20))
    return waveform


def select_fleurs(rows, train_ids, exposed_ids):
    """Text-independent selection; keep repeat readings as a separate secondary set."""
    eligible = [r for r in rows if r[0] not in train_ids | exposed_ids]
    first = {}
    for row in sorted(eligible, key=lambda r: hashlib.sha256(("55:" + r[1]).encode()).hexdigest()):
        first.setdefault(row[0], row[1])
    return [(row, first[row[0]] == row[1]) for row in eligible]


def glossary_from_train(domain, general):
    def counts(rows):
        result = Counter()
        for row in rows:
            result.update(re.findall(r"\b[a-z][a-z-]{2,}\b", row["reference_text"].lower()))
        return result
    a, b = counts(domain), counts(general)
    candidates = [w for w in a if a[w] >= 2 and len(w) >= 4]
    # The denominator removes words common in general English without using dev answers.
    ranked = sorted(candidates, key=lambda w: (-a[w] / (b[w] + 1), -a[w], w))[:48]
    return ", ".join(ranked)


def code_identity():
    root = Path("/code")
    paths = [Path(__file__), *sorted((root / "src/north55_speech").glob("*.py"))]
    return {str(p.relative_to(root)): file_hash(p) for p in paths}


def prepare():
    from north55_speech.asr import local_model_manifest
    from north55_speech.schemas import PipelineConfig

    w, out = Path("/workspace"), Path("/output")
    if (out / "inference/plan.json").exists():
        raise ValueError("Preserve the existing experiment freeze")
    old = read(w / "reports/nus-lora-ablation-v1/inputs.json")
    refs = read(w / "reports/nus-lora-ablation-v1/scoring/references.json")
    items = old["control"]
    weak_refs = read(w / "reports/additional-sources-v1/asr/references.json")
    weak = [i for i in read(w / "reports/language-large-v1/inputs.json")
            if i["cohort"] == "publisher_weak_dev" and weak_refs[i["id"]] is not None]
    items = items + weak
    refs = {i["id"]: (weak_refs if i in weak else refs)[i.get("reference_id", i["id"])] for i in items}
    train = jsonl(w / "data/curated/nus-training-v1/train.jsonl")
    domain = jsonl(w / "data/curated/publisher-expanded-v1/training/train.jsonl")
    domain += [r for r in train if r["source_dataset"].startswith("NUS")]
    if any(r["split"] != "train" for r in train + domain):
        raise ValueError("Glossary and exclusion inputs must be train only")
    glossary = glossary_from_train(domain, [r for r in train if r["language"] == "en"
                                           and not r["source_dataset"].startswith("NUS")])
    train_pcm = set()
    for r in {r["audio_path"]: r for r in train + domain}.values():
        x, rate = sf.read(Path("/audio") / r["audio_path"], dtype="float32")
        if rate != 16000 or x.ndim != 1:
            raise ValueError("Unexpected prepared training audio")
        train_pcm.add(pcm_hash(x))
    train_speakers = {s for r in train + domain for s in r.get("speaker_ids", [])}
    old_ru = {i["id"].removeprefix("fleurs-ru-") for i in items if i["cohort"] == "general_ru"}
    with (w / "data/input/pair-quality-sources-v1/fleurs-train.tsv").open(encoding="utf-8", newline="") as f:
        train_ids = {r[0] for r in csv.reader(f, delimiter="\t")}
    fleurs = w / "data/input/fleurs-ru-v1"
    acquisition = read(fleurs / "acquisition.json")
    for entry in acquisition["files"]:
        if file_hash(fleurs / entry["path"]) != entry["sha256"]:
            raise ValueError("FLEURS source checksum mismatch")
    with (fleurs / "dev.tsv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if any(len(r) != 7 for r in rows):
        raise ValueError("Unexpected TSV schema")
    selected = {r[1]: (r, primary) for r, primary in select_fleurs(rows, train_ids, old_ru)}
    seen = set()
    with tarfile.open(fleurs / "dev.tar.gz", "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError("Unsafe archive member")
            if not member.isfile() or path.name not in selected:
                continue
            if path.name in seen or member.size > 20 * 1024 * 1024:
                raise ValueError("Duplicate or oversized audio member")
            row, primary = selected[path.name]
            seen.add(path.name)
            x, rate = sf.read(io.BytesIO(archive.extractfile(member).read()), dtype="float32")
            if rate != 16000 or x.ndim != 1 or len(x) != int(row[5]) or not np.isfinite(x).all():
                raise ValueError("Audio/TSV contract failure")
            identifier = "fleurs-expanded-" + hashlib.sha256(path.name.encode()).hexdigest()[:20]
            target = Path("/new-audio") / (identifier + ".wav")
            sf.write(target, x, rate, subtype="FLOAT")
            items.append({"id": identifier, "audio_path": str(target), "audio_sha256": file_hash(target),
                          "duration_sec": len(x) / rate, "input_language": "ru", "sentence_id": row[0],
                          "group_id": "fleurs-unknown-speakers", "primary_new_ru": primary,
                          "cohort": "new_ru_primary" if primary else "new_ru_repeat_readings",
                          "source_file": path.name, "reference_kind": "publisher_human_transcript",
                          "local_human_verified": False})
            refs[identifier] = row[3]
    if seen != set(selected):
        raise ValueError("Selected audio missing from archive")
    new_pcm = set()
    for item in items:
        x = load_input(item)
        h = pcm_hash(x)
        if h in train_pcm or (item.get("speaker_id") and item["speaker_id"] in train_speakers):
            raise ValueError("Evaluation overlaps known training data")
        if item["cohort"].startswith("new_ru"):
            if h in new_pcm:
                raise ValueError("Repeated waveform in new Russian data")
            new_pcm.add(h)
        item["pcm_sha256"] = h
    if len({i["id"] for i in items}) != len(items):
        raise ValueError("Duplicate evaluation ID")
    base = read(w / "reports/language-large-v1/plan.json")["configs"]["small_known"]
    base = PipelineConfig.model_validate(base).model_dump()
    atomic_json(out / "scoring/references.json", refs)
    atomic_json(out / "inference/inputs.json", items)
    plan = {"created_at": now().isoformat(), "code": code_identity(), "baseline": base,
            "protocol_sha256": file_hash(out / "protocol.md"), "glossary": glossary,
            "glossary_train_count": len(domain), "train_pcm_count": len(train_pcm),
            "models": {"small": local_model_manifest(SMALL), "large": local_model_manifest(LARGE)},
            "model_names": {"small": SMALL, "large": LARGE},
            "inputs_sha256": file_hash(out / "inference/inputs.json"),
            "references_sha256": file_hash(out / "scoring/references.json"),
            "source_acquisition": acquisition, "fleurs_source_rows": len(rows),
            "fleurs_train_sentence_exclusions": len(train_ids), "previous_ru_sentence_exclusions": len(old_ru),
            "cohorts": dict(Counter(i["cohort"] for i in items)),
            "systems": ["small", "small_glossary", "large", "large_glossary"],
            "gate": {"threshold": .5, "min_speech_duration_ms": 100},
            "max_configurations": 8, "new_training_steps": 0, "closed_test_accessed": False,
            "new_ru_policy_locked": "large baseline, no glossary, no gate"}
    atomic_json(out / "inference/plan.json", plan)
    print(json.dumps({"cohorts": plan["cohorts"], "glossary": glossary}, ensure_ascii=False), flush=True)


def infer(system):
    from north55_speech.asr import AsrProvider
    from north55_speech.audio import VadProvider
    from north55_speech.schemas import PipelineConfig, VadConfig

    study, output = Path("/study"), Path("/predictions") / system
    plan = read(study / "plan.json")
    if code_identity() != plan["code"] or file_hash(study / "inputs.json") != plan["inputs_sha256"]:
        raise ValueError("Frozen code or inputs changed")
    items = read(study / "inputs.json")
    model = system.split("_")[0]
    config = PipelineConfig.model_validate(plan["baseline"] | {"model": plan["model_names"][model]})
    provider = AsrProvider(config)
    if provider.model.model.device != "cuda" or provider.model.model.compute_type != "float16":
        raise ValueError("Runtime precision/device differs")
    begun, completed, reused = time.perf_counter(), 0, 0
    output.mkdir(parents=True, exist_ok=True)
    plan_hash = file_hash(study / "plan.json")
    for index, item in enumerate(items):
        target = output / (item["id"] + ".json")
        if target.exists():
            if read(target)["plan_sha256"] != plan_hash:
                raise ValueError("Incompatible resume")
            continue
        # No hints on RU/auto; these calls are exactly identical to the base system.
        if "glossary" in system and item["input_language"] != "en":
            source = Path("/predictions") / model / target.name
            record = read(source)
            if record["plan_sha256"] != plan_hash:
                raise ValueError("Invalid reuse source")
            atomic_json(target, record | {"reused_from": str(source), "reused_sha256": file_hash(source)})
            reused += 1
            continue
        x = load_input(item)
        if pcm_hash(x) != item["pcm_sha256"]:
            raise ValueError("Frozen waveform differs")
        started = time.perf_counter()
        speech = VadProvider().intervals(x, VadConfig(enabled=True, **plan["gate"]))
        provider.config = config.model_copy(update={"name": system,
            "hotwords": plan["glossary"] if "glossary" in system and item["input_language"] == "en" else None,
            "glossary_version": "train_glossary_v1" if "glossary" in system else None})
        record = {"id": item["id"], "plan_sha256": plan_hash, "pcm_sha256": item["pcm_sha256"],
                  "options": provider.options(item["input_language"]), "speech_intervals": speech,
                  "hypothesis": "", "segments": [], "runtime_failure": None}
        try:
            segments = provider.transcribe(x, 0, item["input_language"], item["id"], lambda: None)
            record["segments"] = [s.model_dump() for s in segments]
            record["hypothesis"] = " ".join(s.raw_asr_text.strip() for s in segments)
        except Exception as exc:
            record["runtime_failure"] = {"type": type(exc).__name__, "message": str(exc)}
        record["elapsed_sec"] = time.perf_counter() - started
        atomic_json(target, record)
        completed += 1
        if index % 25 == 0:
            print(json.dumps({"system": system, "done": index + 1, "total": len(items)}), flush=True)
    atomic_json(output / "execution.json", {"plan_sha256": plan_hash, "new_calls": completed,
        "reused_calls": reused, "wall_sec": time.perf_counter() - begun,
        "model_initialization_sec": provider.initialization_sec,
        "files": {i["id"]: file_hash(output / (i["id"] + ".json")) for i in items}})
    print(json.dumps({"system": system, "completed": len(items), "new_calls": completed, "reused_calls": reused}), flush=True)


def score():
    from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap

    out = Path("/output")
    plan = read(out / "inference/plan.json")
    if (code_identity() != plan["code"] or file_hash(out / "protocol.md") != plan["protocol_sha256"]
            or file_hash(out / "inference/inputs.json") != plan["inputs_sha256"]
            or file_hash(out / "scoring/references.json") != plan["references_sha256"]):
        raise ValueError("Frozen study integrity check failed")
    items, refs = read(out / "inference/inputs.json"), read(out / "scoring/references.json")
    records, counts = {}, {}
    systems = [s + suffix for s in plan["systems"] for suffix in ("", "_gate")]
    for system in plan["systems"]:
        execution = read(out / "predictions" / system / "execution.json")
        for item in items:
            path = out / "predictions" / system / (item["id"] + ".json")
            if file_hash(path) != execution["files"][item["id"]]:
                raise ValueError("Prediction checksum mismatch")
            record = read(path)
            if record["plan_sha256"] != file_hash(out / "inference/plan.json") or record["pcm_sha256"] != item["pcm_sha256"]:
                raise ValueError("Prediction/input mismatch")
            for suffix in ("", "_gate"):
                text = record["hypothesis"] if not suffix or record["speech_intervals"] else ""
                records[system + suffix, item["id"]] = record | {"selected_text": text}
                counts[system + suffix, item["id"]] = edit_counts(refs[item["id"]], text)
    summaries = {}
    for cohort in sorted({i["cohort"] for i in items}):
        selected = [i for i in items if i["cohort"] == cohort]
        minutes = sum(i["duration_sec"] for i in selected) / 60
        summaries[cohort] = {}
        for system in systems:
            total = corpus_counts([counts[system, i["id"]] for i in selected])
            total.update(clips=len(selected), minutes=minutes,
                failures=sum(records[system, i["id"]]["runtime_failure"] is not None for i in selected),
                inserted_words_per_minute=sum(counts[system, i["id"]]["I"] for i in selected) / minutes)
            summaries[cohort][system] = total
    checks = {}
    for system in systems:
        def wer(cohort, s):
            return summaries[cohort][s]["wer_lexical_corpus"]
        checks[system] = {
            "clean_en": wer("general_clean", system) <= wer("general_clean", "small") + .01,
            "quiet_en": wer("quiet_general_clean", system) <= wer("quiet_general_clean", "small"),
            "quiet_cockpit": wer("quiet_partial_human_dev", system) <= wer("quiet_partial_human_dev", "small"),
            "noise": all(summaries[c][system]["I"] <= summaries[c]["small"]["I"]
                         for c in ("noise_only", "bleriot_b_noise")),
            "runtime": all(summaries[c][system]["failures"] == 0 for c in summaries),
            "cockpit_improved": wer("partial_human_dev", system) < wer("partial_human_dev", "small")}
    eligible = [s for s in systems if all(checks[s].values())]
    chosen = min(eligible, key=lambda s: (summaries["partial_human_dev"][s]["wer_lexical_corpus"],
        summaries["publisher_weak_dev"][s]["wer_lexical_corpus"], s.count("_"), s)) if eligible else "small"
    ru = [i for i in items if i["cohort"] == "new_ru_primary"]
    conditional_ci = paired_cluster_bootstrap([{"group_id": i["sentence_id"],
        "baseline": counts["small", i["id"]], "candidate": counts["large", i["id"]]} for i in ru])
    result = {"plan_sha256": file_hash(out / "inference/plan.json"), "cohorts": summaries,
        "checks": checks, "selected_english_exploratory": chosen,
        "new_ru_comparison": {"baseline": "small", "candidate": "large",
            "conditional_sentence_bootstrap": conditional_ci,
            "population_speaker_CI_available": False, "scope": "general_read_RU_only"},
        "full_spec_gate": "NEEDS_MORE_DATA", "closed_test_accessed": False}
    atomic_json(out / "metrics.json", result)
    atomic_json(out / "scoring/counts.json", {s: {i["id"]: counts[s, i["id"]] for i in items} for s in systems})
    print(json.dumps({"selected_english": chosen, "new_ru": {s: summaries["new_ru_primary"][s]
        for s in ("small", "large")}, "cockpit": {s: summaries["partial_human_dev"][s]["wer_lexical_corpus"]
        for s in systems}, "checks": checks}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "infer", "score"])
    parser.add_argument("system", nargs="?", choices=["small", "small_glossary", "large", "large_glossary"])
    args = parser.parse_args()
    if args.stage == "infer":
        if not args.system:
            parser.error("infer requires a system")
        infer(args.system)
    else:
        {"prepare": prepare, "score": score}[args.stage]()
