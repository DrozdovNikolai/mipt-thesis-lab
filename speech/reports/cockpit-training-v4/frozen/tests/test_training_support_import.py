import io

import numpy as np
import pytest
import soundfile as sf

from scripts.import_training_support import fleurs_rows, waveform


def test_publisher_tsv_quotes_are_preserved_as_text(tmp_path):
    row = ['1', 'a.wav', '"first field', 'second "literal" field', 'meta', '16000', 'gender']
    path = tmp_path / 'train.tsv'
    path.write_text('\t'.join(row)+'\n', encoding='utf-8')
    assert fleurs_rows(path) == [row]


def test_malformed_tsv_is_rejected(tmp_path):
    path = tmp_path / 'bad.tsv'
    path.write_text('one\ttwo\n', encoding='utf-8')
    with pytest.raises(ValueError, match='format'):
        fleurs_rows(path)


@pytest.mark.parametrize('rate,shape', [(8000, (1000,)), (16000, (1000, 2))])
def test_unexpected_source_rate_or_channels_are_not_silently_changed(rate, shape):
    data = io.BytesIO()
    sf.write(data, np.zeros(shape), rate, format='WAV')
    with pytest.raises(ValueError, match='mono 16 kHz'):
        waveform(data.getvalue())
