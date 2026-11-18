"""Train-only audit of omitted sources and remaining whole-clip selection losses."""

import difflib
import json
import re
from collections import Counter
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_phrase_support import POLICY, search_normalize, support

# An exploratory document-comparison ablation, not a change to frozen v2 labels.
ALIASES = {
    "pwr": "power", "avail": "available", "t o": "takeoff", "alt": "altitude",
    "cmd": "command", "gen": "generator", "gens": "generators", "emer": "emergency",
    "norm": "normal", "temp": "temperature", "stand by": "standby",
    "auto thrust": "autothrust", "speed brake": "speedbrake", "seat belts": "seatbelts",
    "turnoff": "turn off",
}
EXTRA_DOCUMENTS = {
    "BEA_cvr": ("BEA_CVR", "fr_with_en_spans", "read_cockpit_and_radio"),
    "DGA_CVR1": ("DGA_CVR1-ocr", "en_with_fr_context_in_document", "read_radio"),
    "DGA_CVR2": ("DGA_CVR2", "mostly_fr_with_en_spans", "read_radio_and_controller_dialogue"),
    "DGA_CVR3": ("DGA_CVR3", "fr", "read_cockpit"),
    "DGA_CVR4": ("DGA_CVR4", "fr", "read_radio"),
    "DGA_CVR5": ("DGA_CVR5", "en_fr", "read_radio_and_cockpit"),
    "DGA_checklist-Puma-1": ("DGA_checklist-Puma1", "fr", "read_checklist"),
    "DGA_checklist-Puma-2": ("DGA_checklist-Puma2", "unknown", "unknown"),
    "DGA_checklist-unknown": ("DGA_checklist-unknown", "unknown", "unknown"),
}


def read(path):
    return json.loads(path.read_bytes())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def normalize_aliases(text):
    text = search_normalize(text)
    for alias, expanded in sorted(ALIASES.items(), key=lambda pair: -len(pair[0])):
        text = re.sub(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", expanded, text)
    return text


def main():
    root, out = Path("/workspace"), Path("/audit")
    old = root / "reports/publisher-phrases-v2"
    prior = root / "data/curated/pair-quality-v1"
    train_path = root / "data/curated/bleriot-v2/manifests/train-dev/train.jsonl"
    source_rows = rows(train_path)
    assert all(s["split"] == "train" for s in source_rows)
    used = read(prior / "sources.json")
    items = {i["id"]: i for i in read(prior / "plan.json")["items"]}
    decisions = read(old / "decisions.json")
    assert set(items) == {d["id"] for d in decisions}
    documents = read(old / "scoring/documents.json")
    texts = {name: "\n".join(line["text"] for line in doc["lines"] if not line.get("excluded_layout"))
             for name, doc in documents.items()}
    original = [s for s in source_rows if not s["variant_of"]]
    omitted = [s for s in original if s["sample_id"] not in used]
    source_inventory = []
    for sample in omitted:
        family = next(k for k in EXTRA_DOCUMENTS if k in sample["sample_id"])
        name, language, scope = EXTRA_DOCUMENTS[family]
        path = root / "data/curated/bleriot-documents/v1" / f"{name}.json"
        doc = read(path)
        body = " ".join(b["text"] for b in doc["blocks"]).strip()
        available = bool(body) and body.lower() != "unknown"
        source_inventory.append({"source": sample["sample_id"], "audio_path": sample["audio_path"],
            "audio_sha256": sample["audio_sha256"], "duration_sec": sample["duration_sec"],
            "speaker_ids": sample["speaker_ids"], "session_id": sample["session_id"], "split": "train",
            "document": str(path.relative_to(root)), "document_sha256": file_hash(path),
            "source_document": doc["source_file"], "source_document_sha256": doc["source_sha256"],
            "has_nonempty_publisher_text": available, "document_language_hint": language,
            "document_scope_hint": scope, "audio_language_verified": False, "audio_scope_verified": False,
            "automatic_training_eligible": False, "human_verified": False,
            "next_step": "multilingual_audio_screen_and_utterance_alignment" if available else "audio_transcription_without_publisher_reference",
            "previous_omission": "outside_fixed_English_checklist_family_mapping"})
    frozen = {"purpose": "Post-hoc training-data diagnosis; not independent model evaluation or pair admission",
        "asr_calls_planned": 0, "training_steps": 0, "aliases": ALIASES,
        "policy_unchanged": POLICY, "source_manifest_sha256": file_hash(train_path),
        "decisions_sha256": file_hash(old / "decisions.json"), "documents_sha256": file_hash(old / "scoring/documents.json"),
        "script_sha256": file_hash(Path(__file__)), "dev_used": False, "test_used": False}
    if (out / "plan.json").exists():
        raise ValueError("Preserve the completed audit version")
    atomic_json(out / "plan.json", frozen)
    atomic_json(out / "omitted-source-queue.json", source_inventory)
    only_document = {"insufficient_publisher_support", "critical_token_not_supported_by_publisher"}
    changed, phrase_rows = [], []
    old_execution = read(prior / "small/execution.json")
    medium_execution = read(old / "predictions/execution.json")
    for d in decisions:
        item = items[d["id"]]
        small_path = prior / "small/predictions" / f"{d['id']}.json"
        medium_path = old / "predictions" / f"{d['id']}.json"
        assert file_hash(small_path) == old_execution["prediction_sha256"][small_path.name]
        assert file_hash(medium_path) == medium_execution["predictions"][d["id"]]
        small, medium = read(small_path), read(medium_path)
        assert d["target"] == medium["hypothesis"].strip()
        relevant = {n + ".json": texts[n + ".json"] for n in FAMILIES[item["family"]]}
        if d["reasons"] and set(d["reasons"]) <= only_document:
            target = normalize_aliases(d["target"])
            best = max(({"document": name, **support(target, normalize_aliases(body))}
                        for name, body in relevant.items()), key=lambda p: (p["coverage"], p["critical_supported"]))
            changed.append({"id": d["id"], "source": item["source"], "duration_sec": item["duration_sec"],
                "target_unchanged": d["target"], "small_text": small["hypothesis"],
                "before": d["publisher"], "after": best,
                "document_check_passes_after_aliases": best["coverage"] >= POLICY["minimum_publisher_coverage"] and best["critical_supported"],
                "automatic_training_eligible": False, "needs_new_preparation_policy": True})
        if not d["accepted"]:
            left, right = search_normalize(d["target"]).split(), search_normalize(small["hypothesis"]).split()
            runs = []
            for block in difflib.SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks():
                if block.size < 4:
                    continue
                phrase = " ".join(left[block.a:block.a + block.size])
                padded = " " + phrase + " "
                matched = [n for n, t in relevant.items() if padded in " " + search_normalize(t) + " "]
                if matched:
                    runs.append({"text": phrase, "words": block.size, "documents": matched})
            if runs:
                phrase_rows.append({"id": d["id"], "source": item["source"], "whole_clip_reasons": d["reasons"],
                    "supported_common_runs": runs, "time_alignment_done": False,
                    "automatic_training_eligible": False, "candidate_only": True})
        if (len(changed) + len(phrase_rows)) % 50 == 0:
            print(json.dumps({"document_cases": len(changed), "clips_with_supported_common_runs": len(phrase_rows)}), flush=True)
    recovered = [v for v in changed if v["document_check_passes_after_aliases"]]
    noise = [s for s in source_rows if s["variant_of"]]
    summary = {"train_original_recordings": len(original), "train_original_minutes": sum(s["duration_sec"] for s in original)/60,
        "processed_original_recordings": len(used), "processed_original_minutes": sum(s["duration_sec"] for s in used.values())/60,
        "omitted_original_recordings": len(omitted), "omitted_original_minutes": sum(s["duration_sec"] for s in omitted)/60,
        "omitted_with_publisher_text_recordings": sum(s["has_nonempty_publisher_text"] for s in source_inventory),
        "omitted_with_publisher_text_minutes": sum(s["duration_sec"] for s in source_inventory if s["has_nonempty_publisher_text"])/60,
        "omitted_without_publisher_text_minutes": sum(s["duration_sec"] for s in source_inventory if not s["has_nonempty_publisher_text"])/60,
        "omitted_document_language_counts": dict(Counter(s["document_language_hint"] for s in source_inventory)),
        "train_noisy_versions": len(noise), "train_noisy_minutes": sum(s["duration_sec"] for s in noise)/60,
        "noisy_versions_with_confirmed_parent": sum(s["augmentation"]["parent_link_status"] == "ACOUSTICALLY_CONFIRMED" for s in noise),
        "pause_clip_minutes": sum(i["duration_sec"] for i in items.values())/60,
        "vad_held_long_spans": len(read(prior / "plan.json")["held_spans"]),
        "document_only_rejects_checked": len(changed), "pass_after_alias_expansion": len(recovered),
        "pass_after_alias_expansion_minutes": sum(s["duration_sec"] for s in recovered)/60,
        "pass_after_alias_expansion_by_source": dict(Counter(s["source"] for s in recovered)),
        "rejected_clips_with_at_least_four_word_common_publisher_run": len(phrase_rows),
        "common_publisher_run_words": sum(r["words"] for p in phrase_rows for r in p["supported_common_runs"]),
        "new_accepted_training_pairs": 0, "new_asr_calls": 0, "training_steps": 0,
        "interpretation": "Diagnostic candidates are not accepted audio-text pairs. Categories overlap and must not be summed."}
    atomic_json(out / "alias-comparison.json", changed)
    atomic_json(out / "supported-subphrases.json", phrase_rows)
    atomic_json(out / "result.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
