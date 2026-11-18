"""Verify actual crop samples, raw targets, preserved data and unique coverage."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash, settings
from north55_speech.datasets import load_manifest, write_manifest
from scripts.publisher_recovery_rules_v3 import fresh_reasons, word_list


def read(path):
    return json.loads(path.read_bytes())


def intervals(rows):
    by_source = defaultdict(list)
    for row in rows:
        if row.variant_of:
            continue
        p = row.annotation_provenance
        by_source[p["source_sample_id"]].append((p["original_start_sec"], p["original_end_sec"]))
    out = {}
    for source, spans in by_source.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        out[source] = merged
    return out


def minutes(grouped):
    return sum(b-a for spans in grouped.values() for a, b in spans)/60


def overlap(row, grouped):
    p = row.annotation_provenance
    a, b = p["original_start_sec"], p["original_end_sec"]
    return sum(max(0, min(b, end)-max(a, start)) for start, end in grouped.get(p["source_sample_id"], []))


def main():
    root, out, dataset = Path("/workspace"), Path("/output"), Path("/dataset")
    candidates = read(out / "scoring/candidates.json")
    by_id = {c["id"]: c for c in candidates}
    plan = read(out / "inference/plan.json")
    old96 = load_manifest(root / "data/curated/publisher-phrases-v2/train.jsonl")
    old49 = load_manifest(root / "data/curated/publisher-recovery-v1/train.jsonl")
    train, dev, added = [load_manifest(dataset / (name+".jsonl")) for name in ("train", "dev", "added")]
    assert file_hash(dataset / "dev.jsonl") == plan["old_dev_sha256"]
    assert file_hash(root / "data/curated/publisher-recovery-v1/train.jsonl") == plan["old_49_train_sha256"]
    for name in ("train", "dev"):
        assert file_hash(root / "data/curated/publisher-phrases-v2" / (name+".jsonl")) == plan["old_"+name+"_sha256"]
    items = {i["id"]: i for i in read(root / "data/curated/pair-quality-v1/plan.json")["items"]}
    executions = {s: read(out / "predictions" / s / "execution.json") for s in ("medium", "large")}
    for e in executions.values():
        assert e["plan_sha256"] == file_hash(out / "inference/plan.json")
        assert set(e["predictions"]) == set(by_id)
    source_cache = {}
    for c in candidates:
        parent = items[c["parent_id"]]
        if c["parent_id"] not in source_cache:
            path = settings.audio_root / parent["audio_path"]
            assert file_hash(path) == parent["audio_sha256"]
            source_cache[c["parent_id"]] = sf.read(path, dtype="float32")
        source, source_rate = source_cache[c["parent_id"]]
        path = settings.audio_root / c["audio_path"]
        assert file_hash(path) == c["audio_sha256"]
        actual, rate = sf.read(path, dtype="float32")
        start, end = round(c["start_sec"]*rate), round(c["end_sec"]*rate)
        assert rate == source_rate == 16000 and np.array_equal(actual, source[start:end])
        assert abs(c["original_start_sec"]-parent["original_start_sec"]-start/rate) < 1e-8
        assert abs(c["original_end_sec"]-parent["original_start_sec"]-end/rate) < 1e-8
        cached_path = root / "reports/publisher-phrases-v2/predictions" / (c["parent_id"]+".json")
        assert file_hash(cached_path) == c["medium_prediction_sha256"]
        cached = read(cached_path)
        if c["kind"] == "subphrase":
            a, b = c["medium_word_range"]
            expected = "".join(w["word"] for w in word_list(cached)[a:b]).strip()
        else:
            expected = cached["hypothesis"].strip()
        assert c["target"] == expected
        for system, e in executions.items():
            prediction_path = out / "predictions" / system / (c["id"]+".json")
            assert file_hash(prediction_path) == e["predictions"][c["id"]]
            options = read(prediction_path)["options"]
            assert options["language"] == "en" and options["beam_size"] == 5
            assert options["initial_prompt"] is None and options["hotwords"] is None and options["prefix"] is None
            assert options["condition_on_previous_text"] is False
    for row in added:
        c = by_id[row.sample_id]
        assert row.reference_text == c["target"] and row.audio_sha256 == c["audio_sha256"]
        preds = [read(out / "predictions" / system / (row.sample_id+".json")) for system in ("medium", "large")]
        assert not fresh_reasons(c, *preds, c["duration_sec"])
    by_train = {s.sample_id: s for s in train}
    for s in old96:
        # New population group IDs may change; source text and audio must not.
        t = by_train[s.sample_id]
        assert (s.reference_text, s.audio_sha256, s.annotation_provenance) == (t.reference_text, t.audio_sha256, t.annotation_provenance)
    assert len({s.audio_sha256 for s in train}) == len(train)
    assert len({s.decoded_audio_sha256 for s in train}) == len(train)
    for key in ("recording_id", "session_id", "audio_sha256", "decoded_audio_sha256"):
        assert {getattr(s, key) for s in train}.isdisjoint(getattr(s, key) for s in dev)
    assert {p for s in train for p in s.speaker_ids}.isdisjoint(p for s in dev for p in s.speaker_ids)
    prior_union, new_union = intervals(old96+old49), intervals(train)
    assert abs(minutes(new_union)-sum(s.duration_sec for s in train)/60) < .001
    completely_new = [s for s in added if overlap(s, prior_union) == 0]
    write_manifest(dataset / "added-nonoverlap-all-prior.jsonl", completely_new)
    result = {"status": "PASS", "verified_actual_pcm_crops": len(candidates),
        "verified_fresh_prediction_hashes": len(candidates)*2, "unchanged_medium_word_targets": True,
        "prior_train_text_audio_and_provenance_preserved": True, "prior_dev_byte_identical": True,
        "no_train_audio_overlap": True, "train_dev_disjoint": True,
        "previous_49_and_96_unique_minutes": minutes(prior_union), "new_train_unique_minutes": minutes(new_union),
        "new_audio_outside_all_prior_minutes": sum(s.duration_sec-overlap(s, prior_union) for s in added)/60,
        "whole_added_pairs_outside_all_prior": len(completely_new),
        "whole_added_minutes_outside_all_prior": sum(s.duration_sec for s in completely_new)/60,
        "new_known_speakers": len({p for s in train for p in s.speaker_ids}),
        "v3_numeric_slots_accepted": [s.sample_id for s in added if s.annotation_provenance["publisher_match"]["mode"] == "numeric_slot"],
        "new_asr_calls": 0, "new_training_steps": 0, "quality_verified": False}
    atomic_json(out / "verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
