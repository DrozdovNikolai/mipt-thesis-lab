from __future__ import annotations

from pathlib import Path

from north55_speech.core import file_hash, settings
from north55_speech.schemas import Segment


class DiarizationProvider:
    version = "pyannote_community1_local_v1"

    def apply(self, path: Path, segments: list[Segment], mode: str) -> dict:
        if mode == "off":
            return {"status": "not_requested", "der": None, "jer": None}
        if mode == "channel_mapping":
            return {
                "status": "completed",
                "source": "explicit_channel_metadata",
                "der": None,
                "jer": None,
            }
        model = settings.model_root / "speaker-diarization-community-1"
        if not (model / "config.yaml").is_file():
            return {
                "status": "blocked",
                "reason": "MODEL_NOT_AVAILABLE",
                "action": "Accept model terms and explicitly acquire a local snapshot",
                "der": None,
                "jer": None,
            }
        import json

        manifest_path = model / "manifest.json"
        if not manifest_path.is_file():
            return {
                "status": "blocked",
                "reason": "UNVERIFIED_LOCAL_DIARIZATION_WEIGHTS",
                "der": None,
                "jer": None,
            }
        manifest = json.loads(manifest_path.read_text())
        if not manifest.get("files") or "config.yaml" not in manifest["files"]:
            return {
                "status": "blocked",
                "reason": "UNVERIFIED_LOCAL_DIARIZATION_WEIGHTS",
                "der": None,
                "jer": None,
            }
        for name, sha in manifest.get("files", {}).items():
            artifact = (model / name).resolve()
            if (
                not artifact.is_relative_to(model.resolve())
                or not artifact.is_file()
                or file_hash(artifact) != sha
            ):
                return {
                    "status": "blocked",
                    "reason": "DIARIZATION_CHECKSUM_MISMATCH",
                    "der": None,
                    "jer": None,
                }
        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError:
            return {
                "status": "blocked",
                "reason": "DIARIZATION_DEPENDENCY_NOT_INSTALLED",
                "der": None,
                "jer": None,
            }
        try:
            pipeline = Pipeline.from_pretrained(str(model))
            if settings.device == "cuda":
                pipeline.to(torch.device("cuda"))
            output = pipeline(str(path))
            annotation = getattr(output, "speaker_diarization", output)
            turns = [
                {"start_sec": turn.start, "end_sec": turn.end, "speaker_id": speaker}
                for turn, _, speaker in annotation.itertracks(yield_label=True)
            ]
        except Exception as e:
            return {
                "status": "blocked",
                "reason": "DIARIZATION_LOCAL_LOAD_OR_INFERENCE_FAILED",
                "error_type": type(e).__name__,
                "der": None,
                "jer": None,
            }
        for segment in segments:
            overlaps = [
                (
                    max(
                        0,
                        min(segment.end_sec, t["end_sec"]) - max(segment.start_sec, t["start_sec"]),
                    ),
                    t,
                )
                for t in turns
            ]
            matches = [t for length, t in overlaps if length > 0]
            speakers = {t["speaker_id"] for t in matches}
            if len(speakers) == 1:
                segment.speaker_id = next(iter(speakers))
            elif len(speakers) > 1:
                segment.speaker_id = None
                segment.risk_reasons.append("overlap")
            # No assignment to captain/first_officer/instructor from acoustics.
        return {
            "status": "completed",
            "turns": turns,
            "der": None,
            "jer": None,
            "evaluation": "not_evaluated_without_human_speaker_time_annotations",
        }
