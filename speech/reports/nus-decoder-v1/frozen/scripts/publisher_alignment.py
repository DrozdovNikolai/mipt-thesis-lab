"""Publisher text preparation and local forced alignment; outputs are weak references."""

from __future__ import annotations

import difflib
import re
import statistics
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.metrics import canonical_normalizer_v1, lexical_normalizer_v1

METHOD = "publisher_columns_and_whisper_dtw_v1"


def tidy_line(text: str) -> str:
    # Remove typographical list numbering and dot leaders, not spoken numeric values.
    text = re.sub(r"^\s*\d+[.)]\s+", "", text)
    text = re.sub(r"[.\u2026]{2,}", " ", text)
    return lexical_normalizer_v1(text)


def pdf_columns(path: Path) -> list[dict]:
    xml = subprocess.check_output(["pdftotext", "-bbox-layout", str(path), "-"])
    root = ET.fromstring(xml)
    blocks = []
    for number, page in enumerate((x for x in root.iter() if x.tag.endswith("}page")), 1):
        width = float(page.attrib["width"])
        lines = []
        for line in page.iter():
            if not line.tag.endswith("}line"):
                continue
            words = [w for w in line if w.tag.endswith("}word")]
            if words:
                lines.append({"x": float(line.attrib["xMin"]), "y": float(line.attrib["yMin"]),
                              "text": " ".join(w.text or "" for w in words)})
        two_columns = sum(x["x"] < .4 * width for x in lines) >= 5 and sum(x["x"] > .5 * width for x in lines) >= 5
        for column in range(2 if two_columns else 1):
            selected = [x for x in lines if not two_columns or int(x["x"] > .5 * width) == column]
            selected.sort(key=lambda x: (x["y"], x["x"]))
            text = "\n".join(tidy_line(x["text"]) for x in selected if tidy_line(x["text"]))
            if text:
                blocks.append({"page": number, "column": column + 1, "text": text,
                               "method": "pdf_word_coordinates_column_order", "raw_lines": selected})
    return blocks


def prepare_document(document: dict, directory: Path) -> dict:
    path = directory / document["source_file"]
    if file_hash(path) != document["source_sha256"]:
        raise ValueError("Publisher source checksum changed")
    blocks = pdf_columns(path) if path.suffix.lower() == ".pdf" else []
    if not blocks:
        blocks = [{**b, "text": "\n".join(tidy_line(line) for line in b["text"].splitlines())}
                  for b in document["blocks"]]
    return {**document, "blocks": blocks, "preparation": METHOD, "human_verified": False}


def locate(draft: str, document: dict) -> dict:
    spoken = lexical_normalizer_v1(draft).split()
    script = " ".join(b["text"] for b in document["blocks"]).split()
    width = min(len(script), max(35, int(len(spoken) * 1.8) + 12))
    candidates = []
    for offset in range(0, max(1, len(script)), max(1, len(spoken) // 3)):
        matches = difflib.SequenceMatcher(None, spoken, script[offset:offset+width], autojunk=False).get_matching_blocks()
        anchors = [m for m in matches if m.size >= 2]
        if not anchors:
            continue
        first, last = anchors[0], anchors[-1]
        start = max(0, offset + first.b - min(first.a, 8))
        end = min(len(script), offset + last.b + last.size + min(len(spoken) - last.a - last.size, 8))
        count = sum(m.size for m in anchors)
        candidates.append({"coverage": count / max(1, len(spoken)), "matched_tokens": count,
                           "start_token": start, "end_token": end,
                           "text": " ".join(script[start:end]),
                           "length_difference": abs(end-start-len(spoken))})
    if not candidates:
        return {"coverage": 0., "matched_tokens": 0, "text": "", "reason": "no_lexical_anchors"}
    candidates.sort(key=lambda x: (-x["matched_tokens"], x["length_difference"], x["start_token"]))
    return candidates[0]


def number_tokens(text: str) -> list[str]:
    # Diagnostic only: this representation never rewrites the transcript.
    return re.findall(r"\d+(?:[.,]\d+)?", canonical_normalizer_v1(text))


def align(model, audio, document: dict, draft: str, original_start: float, language="en") -> dict:
    from faster_whisper.tokenizer import Tokenizer

    located = locate(draft, document)
    result = {**located, "source_file": document["source_file"], "source_sha256": document["source_sha256"],
              "method": METHOD, "human_verified": False, "reference_status": "weak",
              "words": [], "eligible_for_exploratory_training": False, "reasons": []}
    if located["coverage"] < .45 or located["matched_tokens"] < 8:
        result["reasons"].append("insufficient_script_anchors")
        return result
    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=language)
    tokens = tokenizer.encode(located["text"])
    if len(tokens) > 400:
        result["reasons"].append("publisher_span_too_long")
        return result
    features = model.feature_extractor(audio)
    frames = min(int(len(audio) / 160), features.shape[-1])
    encoded = model.encode(features[:, :model.feature_extractor.nb_max_frames])
    words = model.find_alignment(tokenizer, [tokens], encoded, frames)[0]
    for word in words:
        result["words"].append({"word": word["word"], "start_sec": float(word["start"]), "end_sec": float(word["end"]),
                                "original_start_sec": original_start + float(word["start"]),
                                "original_end_sec": original_start + float(word["end"]),
                                "model_score": float(word["probability"])})
    probabilities = [w["model_score"] for w in result["words"]]
    result["median_model_score"] = statistics.median(probabilities) if probabilities else 0.
    result["zero_duration_fraction"] = sum(w["end_sec"] <= w["start_sec"] for w in result["words"]) / max(1, len(words))
    if not words or result["median_model_score"] < .35:
        result["reasons"].append("low_forced_alignment_score")
    if result["zero_duration_fraction"] > .25:
        result["reasons"].append("collapsed_word_times")
    if any(not 0 <= w["start_sec"] <= w["end_sec"] <= len(audio)/16000 + .05 for w in result["words"]):
        result["reasons"].append("invalid_original_timeline")
    if number_tokens(draft) != number_tokens(located["text"]):
        result["reasons"].append("numeric_disagreement_requires_review")
    result["eligible_for_exploratory_training"] = not result["reasons"]
    return result
