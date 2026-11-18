"""Additional mechanical control after the frozen repeat-retention failure."""
import json
from pathlib import Path

import numpy as np

from north55_speech.asr import AsrProvider
from north55_speech.audio import RATE
from north55_speech.core import atomic_json
from north55_speech.schemas import PipelineConfig
from scripts.decoding_diagnostics import load_audio, read


class LegacyText(AsrProvider):
    def options(self, language, retry=False):
        return super().options(language, retry) | {'without_timestamps': True}


plan = read(Path('/study/plan.json'))
item = next(i for i in read(Path('/study/inputs.json')) if i['id'] == '3536-8226-0027')
source = load_audio(item)
waveform = np.concatenate([source, np.zeros(RATE, dtype='float32'), source])
result = {}
for name, provider_type in [('reference', AsrProvider), ('legacy_text', LegacyText)]:
    provider = provider_type(PipelineConfig.model_validate(plan['configs']['parent_reference']))
    segments = provider.transcribe(waveform, 30 * RATE, 'en', name, lambda: None)
    result[name] = {'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments),
                    'segments': [s.model_dump() for s in segments], 'options': provider.options('en')}
atomic_json(Path('/study/regressions/control-result.json'), result)
print(json.dumps({k: v['hypothesis'] for k, v in result.items()}))
