"""Descriptive exact-word audit; not manually labeled commands or entity accuracy."""

from pathlib import Path

import jiwer

from north55_speech.core import atomic_json, file_hash
from north55_speech.metrics import lexical_normalizer_v1
from scripts.improvement_experiment import read

# Fixed before candidate scores; these lists never enter ASR or candidate selection.
TERMS = frozenset({"climb", "descend", "maintain", "heading", "flight", "level", "runway",
                   "cleared", "hold", "stop", "unable", "negative", "not", "no", "left", "right",
                   "turn", "speed", "squawk", "contact", "wilco", "roger"})
NEGATIONS = frozenset({"unable", "negative", "not", "no"})


def exact_word_counts(reference, hypothesis, vocabulary):
    reference = lexical_normalizer_v1(reference)
    hypothesis = lexical_normalizer_v1(hypothesis)
    words = reference.split()
    wanted = {index for index, word in enumerate(words) if word in vocabulary}
    aligned = jiwer.process_words(reference, hypothesis)
    correct = set()
    for chunk in aligned.alignments[0]:
        if chunk.type == "equal":
            correct.update(range(chunk.ref_start_idx, chunk.ref_end_idx))
    return {"reference_occurrences": len(wanted), "correctly_aligned": len(wanted & correct),
            "missed_or_substituted": len(wanted - correct)}


def main():
    root = Path("/output")
    items = [i for i in read(root / "inference/inputs.json") if i["cohort"] == "atcosim"]
    refs = read(root / "scoring/references.json")
    results = {}
    for system in ("small", "medium", "atc"):
        execution = read(root / "predictions" / system / "execution.json")
        totals = {name: {"reference_occurrences": 0, "correctly_aligned": 0, "missed_or_substituted": 0}
                  for name in ("aviation_words", "negations")}
        for item in items:
            path = root / "predictions" / system / f"{item['id']}.json"
            if file_hash(path) != execution["files"][item["id"]]:
                raise ValueError("Prediction changed")
            hypothesis = read(path)["hypothesis"]
            for name, vocabulary in (("aviation_words", TERMS), ("negations", NEGATIONS)):
                for key, value in exact_word_counts(refs[item["id"]], hypothesis, vocabulary).items():
                    totals[name][key] += value
        results[system] = totals
    atomic_json(root / "aviation-words.json", {"script_sha256": file_hash(Path(__file__)),
        "terms": sorted(TERMS), "negations": sorted(NEGATIONS), "systems": results,
        "candidate_selection_input": False, "human_command_or_entity_labels": False,
        "meaning": "Exact reference-word recovery under lexical edit alignment; not command interpretation or entity validation"})


if __name__ == "__main__":
    main()
