"""Serialization-only amendment for NeMo enums; frozen inference stays unchanged."""
from enum import Enum
from pathlib import Path

from scripts import cockpit_cross_asr_v6 as worker


def encode_enums(value):
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {key: encode_enums(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_enums(item) for item in value]
    return value


if __name__ == '__main__':
    amendment = worker.read(Path('/amendment/amendment.json'))
    assert worker.file_hash(Path(__file__)) == amendment['runner_sha256']
    assert worker.file_hash(worker.STUDY/'plan.json') == amendment['plan_sha256']
    original_save = worker.save

    def amended_save(path, value):
        return original_save(path, encode_enums(value))

    worker.save = amended_save
    worker.infer()
