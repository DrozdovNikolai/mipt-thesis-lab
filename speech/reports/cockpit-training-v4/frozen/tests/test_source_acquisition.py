"""Source archives cannot write through traversal, aliases, links, or oversized entries."""

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def extractor():
    root = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("bleriot_extractor_test", root / "extract_bleriot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.path.remove(str(root))


@pytest.mark.parametrize("name", ["../escape.wav", "a/../../escape.wav", "C:\\escape.wav",
                                    "/escape.wav", "a.wav:stream", "CON.txt", "safe/evil. "])
def test_archive_rejects_unsafe_names(extractor, tmp_path, name):
    with pytest.raises(ValueError):
        extractor.safe_member(name, tmp_path)


@pytest.mark.parametrize("field", ["Symbolic Link", "Hard Link", "Copy Link", "Alternate Stream"])
def test_archive_rejects_links(extractor, tmp_path, field):
    with pytest.raises(ValueError):
        extractor.parse_listing(
            f"header\n----------\nPath = safe.wav\nSize = 4\n{field} = target\n", tmp_path
        )


def test_archive_rejects_case_collisions_and_bombs(extractor, tmp_path):
    for listing in [
        "Path = safe.wav\nSize = 4\n\nPath = SAFE.wav\nSize = 4\n",
        f"Path = huge.wav\nSize = {21 * 1024**3}\n",
    ]:
        with pytest.raises(ValueError):
            extractor.parse_listing("header\n----------\n" + listing, tmp_path)


def test_archive_accepts_actual_dga_filename_style(extractor, tmp_path):
    entries = extractor.parse_listing(
        "header\n----------\nPath = raw-speech\\DGA_checklist-PC7_sp104 .wav\n"
        "Folder = -\nSize = 100\nAttributes = A\nSymbolic Link = \n"
        "Hard Link = \nCopy Link = \nAlternate Stream = -\nEncrypted = -\n", tmp_path
    )
    assert len(entries) == 1
    assert extractor.safe_member(entries[0]["Path"], tmp_path).parent == tmp_path / "raw-speech"
