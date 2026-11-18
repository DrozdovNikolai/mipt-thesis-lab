from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import tarfile
import time
from pathlib import Path
from typing import Any

import httpx

from north55_speech.core import SpeechError, atomic_json, file_hash, settings

SMALL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"


def download(
    url: str,
    destination: Path,
    maximum_bytes: int,
    expected: str | None = None,
    algorithm: str = "sha256",
) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    h, size = hashlib.new(algorithm), 0
    start = time.perf_counter()
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            if int(response.headers.get("content-length", 0)) > maximum_bytes:
                raise SpeechError("DOWNLOAD_BUDGET", "Remote asset exceeds byte budget")
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise SpeechError("DOWNLOAD_BUDGET", "Asset exceeded allowed byte budget")
                    h.update(chunk)
                    stream.write(chunk)
    if expected and h.hexdigest() != expected:
        temporary.unlink(missing_ok=True)
        raise SpeechError(
            "DOWNLOAD_CHECKSUM_MISMATCH", "Acquired asset checksum does not match publisher"
        )
    temporary.replace(destination)
    return {
        "url": url,
        "sha256": file_hash(destination),
        "bytes": size,
        "publisher_checksum": expected,
        "publisher_algorithm": algorithm,
        "elapsed_sec": time.perf_counter() - start,
    }


def fetch_model(
    model="small", repo="Systran/faster-whisper-small", revision=SMALL_REVISION
) -> dict:
    if (model, repo, revision) != ("small", "Systran/faster-whisper-small", SMALL_REVISION):
        raise SpeechError(
            "UNVERIFIED_MODEL_SOURCE",
            "Automatic acquisition is restricted to the reviewed MIT small checkpoint; use a separately verified local manifest for other weights",
        )
    if not model.replace("-", "").isalnum():
        raise SpeechError("INVALID_MODEL_NAME", "Model ID must be a simple local name")
    destination = settings.model_root / model
    existing = destination / "manifest.json"
    if existing.is_file():
        manifest = json.loads(existing.read_text())
        if manifest["revision"] != revision:
            raise SpeechError(
                "MODEL_REVISION_CONFLICT", "Existing immutable model revision differs"
            )
        if all(file_hash(destination / name) == value for name, value in manifest["files"].items()):
            return manifest
    # The explicit acquisition command is the only place that enables model network access.
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import constants, snapshot_download

    constants.HF_HUB_OFFLINE = False
    snapshot_download(
        repo_id=repo,
        revision=revision,
        local_dir=destination,
        allow_patterns=[
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
            "README.md",
        ],
        max_workers=2,
    )
    files = {
        p.name: file_hash(p)
        for p in destination.iterdir()
        if p.is_file() and p.name != "manifest.json"
    }
    from faster_whisper.utils import get_assets_path

    vad = Path(get_assets_path()) / "silero_vad_v6.onnx"
    if not vad.exists():
        candidates = list(Path(get_assets_path()).glob("*.onnx"))
        vad = candidates[0] if candidates else vad
    manifest = {
        "model": model,
        "repo": repo,
        "revision": revision,
        "files": files,
        "license": "MIT",
        "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "faster_whisper_version": importlib.metadata.version("faster-whisper"),
        "silero": {
            "path": str(vad),
            "sha256": file_hash(vad) if vad.exists() else None,
            "distribution": "bundled_with_faster_whisper",
        },
    }
    atomic_json(existing, manifest)
    atomic_json(settings.model_root / "models.lock.json", {model: manifest})
    return manifest


def fetch_smoke() -> dict:
    """Two actual LibriSpeech dev-clean utterances, CC BY 4.0, engineering controls only."""
    target = settings.audio_root / "smoke"
    card = target / "provenance.json"
    if card.exists():
        data = json.loads(card.read_text())
        if all(file_hash(target / f["filename"]) == f["sha256"] for f in data["samples"]):
            return data
    target.mkdir(parents=True, exist_ok=True)
    base = "https://www.openslr.org/resources/12/"
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(base + "md5sum.txt")
        response.raise_for_status()
    checksum = next(
        line.split()[0]
        for line in response.text.splitlines()
        if line.strip().endswith("dev-clean.tar.gz")
    )
    archive = target / "dev-clean.tar.gz"
    acquisition = download(base + "dev-clean.tar.gz", archive, 400 * 1024**2, checksum, "md5")
    # No extractall: only explicitly selected regular audio and transcript entries are read.
    chosen: list[str] = []
    transcripts: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or member.size > 10 * 1024**2:
                continue
            if member.name.endswith(".flac") and len(chosen) < 2:
                source = tar.extractfile(member)
                if source:
                    filename = Path(member.name).name
                    (target / filename).write_bytes(source.read())
                    chosen.append(filename)
            if member.name.endswith(".trans.txt"):
                source = tar.extractfile(member)
                if source:
                    for line in source.read().decode().splitlines():
                        key, value = line.split(" ", 1)
                        transcripts[key] = value
    samples = [
        {
            "filename": name,
            "sha256": file_hash(target / name),
            "reference_text": transcripts[Path(name).stem],
            "sample_id": Path(name).stem,
        }
        for name in chosen
    ]
    data = {
        "source": "LibriSpeech dev-clean (SLR12)",
        "source_url": "https://www.openslr.org/12/",
        "attribution": "Vassil Panayotov, Guoguo Chen, Daniel Povey, Sanjeev Khudanpur",
        "license": "CC-BY-4.0",
        "speech_origin": "recorded_human",
        "scope": "general_control",
        "use": "engineering_smoke_only_not_cockpit_quality_evidence",
        "samples": samples,
        "acquisition": acquisition,
    }
    atomic_json(card, data)
    return data


def fetch_snapshot(repo: str, revision: str, local_name: str, accepted_terms: bool = False) -> dict:
    """Explicit acquisition for local Transformers or gated diarization weights."""
    if not local_name.replace("-", "").isalnum():
        raise SpeechError("UNSAFE_MODEL_PATH", "Use a simple local model name")
    permitted = {
        "openai/whisper-small",
        "openai/whisper-large-v3",
        "pyannote/speaker-diarization-community-1",
    }
    if repo not in permitted:
        raise SpeechError(
            "UNVERIFIED_MODEL_SOURCE",
            "Snapshot command accepts the documented primary model sources only",
        )
    if repo.startswith("pyannote/") and not accepted_terms:
        raise SpeechError(
            "MODEL_TERMS_REQUIRED",
            "The owner must accept model terms before passing --accepted-terms",
        )
    os.environ["HF_HUB_OFFLINE"] = "0"
    from huggingface_hub import HfApi, constants, snapshot_download

    constants.HF_HUB_OFFLINE = False
    token = os.environ.get("HF_TOKEN")
    info = HfApi().model_info(repo, revision=revision, token=token)
    if info.sha != revision:
        raise SpeechError("REVISION_MUST_BE_COMMIT", "Supply a verified full model commit hash")
    destination = settings.model_root / local_name
    snapshot_download(repo, revision=revision, local_dir=destination, token=token, max_workers=2)
    card_metadata: dict[str, Any] = info.card_data.to_dict() if info.card_data is not None else {}
    manifest = {
        "repo": repo,
        "revision": revision,
        "accepted_terms": accepted_terms,
        "license": card_metadata.get("license", "see_model_card"),
        "files": {
            str(p.relative_to(destination)): file_hash(p)
            for p in destination.rglob("*")
            if p.is_file() and ".cache" not in p.parts and p.name != "manifest.json"
        },
    }
    atomic_json(destination / "manifest.json", manifest)
    return manifest
