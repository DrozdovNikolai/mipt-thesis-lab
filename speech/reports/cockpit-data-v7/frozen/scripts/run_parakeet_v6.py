"""Serialization-only amendment for NeMo enums; frozen inference stays unchanged."""
import importlib.util
from enum import Enum
from pathlib import Path

spec = importlib.util.spec_from_file_location('v6_worker', '/code/scripts/cockpit_cross_asr_v6.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


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
