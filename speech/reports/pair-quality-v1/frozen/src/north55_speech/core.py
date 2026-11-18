from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SpeechError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NORTH55_", extra="ignore")
    database_url: str = "postgresql+psycopg://north55:unset@postgres/north55"
    broker_url: str = "amqp://north55:unset@rabbitmq:5672//"
    api_key: str = Field(default="", repr=False)
    session_secret: str = Field(default="", repr=False)
    audio_root: Path = Path("/audio")
    artifact_root: Path = Path("/artifacts")
    model_root: Path = Path("/models")
    report_root: Path = Path("/reports")
    input_root: Path = Path("/data/input")
    device: str = "cpu"
    compute_type: str = "int8"
    api_url: str = "http://api:8000"
    evaluator: bool = False
    max_upload_bytes: int = 2 * 1024**3
    max_duration_sec: float = 4 * 3600
    max_channels: int = 8
    minimum_free_bytes: int = 256 * 1024**2
    lease_seconds: int = 90
    max_attempts: int = 3
    pipeline_config: Path = Path("/app/configs/baseline.yaml")


settings = Settings()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        value = yaml.safe_load(f)
    if not isinstance(value, dict):
        raise SpeechError("INVALID_CONFIG", "Expected a YAML mapping")
    return value


def confined(root: Path, relative: str | Path, must_exist: bool = True) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise SpeechError("UNSAFE_PATH", "Path must remain inside the allowed directory")
    if must_exist and not candidate.is_file():
        raise SpeechError("FILE_NOT_FOUND", "Local file is unavailable")
    return candidate
