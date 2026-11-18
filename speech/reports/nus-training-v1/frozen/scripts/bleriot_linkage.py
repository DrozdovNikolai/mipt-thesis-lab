"""Acoustic source-identity audit; no ASR hypotheses or reference text are used.

Magnitude-squared coherence tolerates an audio-chain frequency response, unlike
the initial broadband envelope correlation. It is evidence for parent linkage,
not a recognition-quality score or evidence of human transcript verification.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from north55_speech.core import atomic_json, file_hash

ROOT = Path("/data/input/bleriot/verified")
REPORT = Path("/reports/bleriot-linkage-v2.json")
RATE = 8000


@lru_cache(maxsize=48)
def audio(path: Path) -> np.ndarray:
    with sf.SoundFile(path) as stream:
        wave = stream.read(min(len(stream), stream.samplerate * 90), dtype="float32", always_2d=True)[:, 0]
        common = math.gcd(RATE, stream.samplerate)
        return signal.resample_poly(wave, RATE//common, stream.samplerate//common)


def similarity(first: np.ndarray, second: np.ndarray) -> dict:
    n = min(len(first), len(second))
    frequencies, values = signal.coherence(first[:n], second[:n], fs=RATE, nperseg=2048, noverlap=1024)
    values = values[(frequencies >= 300) & (frequencies <= 3000)]
    return {"mean_coherence": float(np.nanmean(values)), "median_coherence": float(np.nanmedian(values)),
            "seconds": n/RATE}


def main() -> None:
    if REPORT.exists():
        raise ValueError("Preserve the existing linkage audit")
    raw = {path.name: path for path in sorted((ROOT / "a").rglob("*.wav"))}
    plan = {
        "source_archive_sha256": {
            corpus: json.loads((ROOT/corpus/"extraction.json").read_text())["archive_sha256"]
            for corpus in ("a", "c")
        },
        "reference_text_access": False, "asr_access": False,
        "signal": "first at most 90 seconds, mono channel 0, polyphase resampling to 8 kHz",
        "metric": "mean magnitude-squared Welch coherence, 300-3000 Hz, nperseg 2048, overlap 1024",
        "decision": "metadata-name match (or explicitly audited filename anomaly), mean coherence >= 0.20 and >= 3x highest other-source coherence",
        "retention": "unconfirmed audio stays quarantined; never select source pairs using ASR performance",
    }
    atomic_json(REPORT.with_name("bleriot-linkage-v2-plan.json"), plan)
    rows = []
    for path in sorted((ROOT/"c").rglob("*.wav")):
        key = re.sub(r"_sp(\d+)(?=\.wav$)", lambda match: f"_sp{int(match[1]):03d}",
                     path.name.removeprefix("CVR_"))
        scores = sorted(
            ({"a": name, **similarity(audio(parent), audio(path))} for name, parent in raw.items()),
            key=lambda row: row["mean_coherence"], reverse=True,
        )
        best, runner_up = scores[:2]
        confident = best["mean_coherence"] >= 0.20 and best["mean_coherence"] >= 3*runner_up["mean_coherence"]
        status = "ACOUSTICALLY_CONFIRMED" if confident and (key == best["a"] or key not in raw) else "REVIEW_REQUIRED"
        row = {"c": path.name, "sha256": file_hash(path), "metadata_candidate": key if key in raw else None,
               "status": status, "best": best, "runner_up": runner_up, "all_candidates": scores,
               "same_start_time_checked": True, "full_duration_correspondence": key == best["a"]}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("c", "status", "best", "runner_up")}), flush=True)
    atomic_json(REPORT, {"plan": plan, "rows": rows, "confirmed": sum(r["status"] == "ACOUSTICALLY_CONFIRMED" for r in rows),
                         "quality_claim": False, "human_verified_annotations": 0})


if __name__ == "__main__":
    main()
