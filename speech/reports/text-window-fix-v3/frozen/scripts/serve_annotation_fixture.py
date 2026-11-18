"""Temporary synthetic UI fixture; never connected to real annotation storage."""

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import uvicorn

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import Sample, validate_groups, write_manifest
from scripts.review_dataset import create_app


def main():
    with tempfile.TemporaryDirectory(prefix="north55-ui-fixture-") as temporary:
        root = Path(temporary)
        audio, packet = root/"audio", root/"packet"
        audio.mkdir()
        packet.mkdir()
        sf.write(audio/"synthetic.wav", np.zeros(16000, dtype=np.float32), 16000)
        sample = Sample(sample_id="a"*32, audio_path="synthetic.wav", audio_sha256=file_hash(audio/"synthetic.wav"),
                        source_dataset="synthetic_ui_fixture", source_version="1", recording_id="fixture-recording",
                        session_id="fixture-session", original_utterance_id="fixture-original", speaker_ids=["fixture-speaker"],
                        language="unknown", scope="unknown", speech_origin="synthetic", duration_sec=1,
                        license_id="test_fixture", provenance="UI testing only, no real human speech",
                        rights_confirmed=True, split="train", primary=False,
                        annotation_provenance={"source_sample_id":"SYNTHETIC UI FIXTURE — NOT BENCHMARK",
                                               "original_start_sec":30,"original_end_sec":31})
        validate_groups([sample])
        write_manifest(packet/"train.jsonl", [sample])
        write_manifest(packet/"dev.jsonl", [])
        atomic_json(packet/"drafts"/(sample.sample_id+".json"), {"text":"UI fixture text; audio is silence"})
        app = create_app(packet, audio, "k"*32, "s"*32)

        @app.middleware("http")
        async def diagnostic(request, call_next):
            if request.url.path == "/login":
                print({"origin": request.headers.get("origin"), "base_url": str(request.base_url)}, flush=True)
            return await call_next(request)

        uvicorn.run(app, host="0.0.0.0", port=8010, access_log=True)


if __name__ == "__main__":
    main()
