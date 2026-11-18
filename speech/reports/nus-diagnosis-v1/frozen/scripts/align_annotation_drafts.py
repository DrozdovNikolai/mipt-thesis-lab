"""Locate publisher-script context for review; never generate or alter gold labels."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest


def tokens(text: str) -> list[str]:
    # No homophone/number expansion, spelling repair or aircraft-state inference.
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).casefold())


def match_context(draft: dict, document: dict, original_start: float) -> dict:
    spoken, times = [], []
    for segment in draft["segments"]:
        for word in segment.get("words", []):
            for token in tokens(word["word"]):
                spoken.append(token)
                times.append([word["start_sec"], word["end_sec"]])
    script, locations = [], []
    for index, block in enumerate(document["blocks"]):
        for token in tokens(block["text"]):
            script.append(token)
            locations.append(index)
    if not spoken or not script:
        return {"coverage": 0.0, "anchors": [], "context": []}
    width = min(len(script), max(30, len(spoken)*2+20))
    offsets = {max(0, i-width//4) for i, token in enumerate(script) if token in spoken[:8]}
    offsets.add(0)
    best: tuple[int, int, list[tuple[int, int, int]]] = (0, 0, [])
    for offset in sorted(offsets):
        matches = difflib.SequenceMatcher(None, spoken, script[offset:offset+width], autojunk=False).get_matching_blocks()
        # Single common words do not constitute an alignment anchor.
        anchors = [(m.a, offset+m.b, m.size) for m in matches if m.size >= 2]
        count = sum(size for _, _, size in anchors)
        if count > best[0]:
            best = (count, offset, anchors)
    aligned = []
    block_ids = set()
    for spoken_index, script_index, size in best[2]:
        block_ids.update(locations[script_index:script_index+size])
        aligned.append({
            "exact_tokens": spoken[spoken_index:spoken_index+size],
            "script_token_start": script_index, "script_token_end": script_index+size,
            "clip_start_sec": times[spoken_index][0], "clip_end_sec": times[spoken_index+size-1][1],
            "original_start_sec": original_start+times[spoken_index][0],
            "original_end_sec": original_start+times[spoken_index+size-1][1],
            "timing_source": "machine_asr_words_not_forced_or_human_alignment",
        })
    context_ids = {neighbor for index in block_ids for neighbor in (index-1, index, index+1)
                   if 0 <= neighbor < len(document["blocks"])}
    return {"coverage": best[0]/len(spoken), "anchors": aligned,
            "context": [{"block_index": index, **document["blocks"][index]} for index in sorted(context_ids)],
            "unmatched_spoken_tokens": len(spoken)-best[0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    samples = []
    for split in ("train", "dev"):
        rows = load_manifest(args.packet/f"{split}.jsonl")
        if any(sample.split != split for sample in rows):
            raise ValueError("Only train/dev publisher context is allowed")
        samples.extend(rows)
    mapping = {
        "BEA_checklists": ["BEA_checklist_A320-NormalChecklist", "BEA_checklist_A320_pilote", "BEA_checklist_B737_NORMAL_CHECKLIST"],
        "DGA_checklist-Beech": ["DGA_checklist-Beech"],
        "DGA_checklist-PC7": ["DGA_checklist-PC7"],
        "DGA_checklist-Puma-1": ["DGA_checklist-Puma1"],
    }
    summary = []
    for sample in samples:
        # Script identity comes from the original acquisition, never ASR performance.
        source = str(sample.recording_id)
        names = next((names for key, names in mapping.items() if key in source), None)
        if names is None:
            raise ValueError("No reviewed publisher checklist mapping for this packet")
        draft_path = args.packet/"drafts"/f"{sample.sample_id}.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        candidates = []
        for name in names:
            path = args.documents/f"{name}.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            result = match_context(draft, document, sample.annotation_provenance["original_start_sec"])
            candidates.append({"source_file": document["source_file"], "source_sha256": document["source_sha256"],
                               "extraction_sha256": file_hash(path), **result})
        candidates.sort(key=lambda candidate: candidate["coverage"], reverse=True)
        result = {"sample_id": sample.sample_id, "status": "MACHINE_CONTEXT_REQUIRES_AUDIO_REVIEW",
                  "human_verified": False, "not_an_asr_reference": True, "not_for_inference_prompts": True,
                  "method": "exact_lexical_sequence_anchors_v1", "draft_sha256": file_hash(draft_path),
                  "candidates": candidates,
                  "limitations": "Repeated checklist phrases, OCR and ASR errors can select the wrong passage. Unmatched words have no alignment. Never replace what was heard with the script."}
        atomic_json(args.packet/"script-hints"/f"{sample.sample_id}.json", result)
        summary.append({"id": sample.sample_id, "split": sample.split, "top_source": candidates[0]["source_file"],
                        "machine_anchor_coverage": candidates[0]["coverage"]})
    atomic_json(args.report, {"status": "EXECUTED_MACHINE_CONTEXT_ONLY", "items": summary,
                             "test_opened": False, "human_labels_created": 0, "quality_evidence": False})


if __name__ == "__main__":
    main()
