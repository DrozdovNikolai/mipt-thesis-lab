"""Measure CPU/GPU FP32 merge arithmetic against untouched saved NUS tensors."""

from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import load_file

from scripts.audit_nus_training_contract import read, save

BASE = Path('/models/whisper-small-transformers/model.safetensors')
ADAPTER = Path('/models/whisper-small-nus-v1/adapter')
MERGED = Path('/models/whisper-small-nus-v1/merged/model.safetensors')


def main():
    adapter = load_file(ADAPTER / 'adapter_model.safetensors')
    config = read(ADAPTER / 'adapter_config.json')
    scale = config['lora_alpha'] / config['r']
    rows = []
    with safe_open(BASE, framework='pt', device='cpu') as base, safe_open(MERGED, framework='pt', device='cpu') as merged:
        for key in sorted(k for k in adapter if '.lora_A.' in k):
            target = key.removeprefix('base_model.model.').replace('.lora_A.weight', '.weight')
            a, b = adapter[key], adapter[key.replace('.lora_A.', '.lora_B.')]
            original, saved = base.get_tensor(target), merged.get_tensor(target)
            row = {'tensor': target, 'dtype': str(saved.dtype), 'numel': saved.numel(),
                   'adaptation_max_abs': float((saved - original).abs().max()), 'arithmetic': {}}
            for device, tf32 in [('cpu', False), ('cuda', False), ('cuda', True)]:
                torch.backends.cuda.matmul.allow_tf32 = tf32
                reconstructed = (original.to(device) + (b.to(device) @ a.to(device)) * scale).cpu()
                error = (saved - reconstructed).abs()
                row['arithmetic'][device + ('_tf32' if tf32 else '_fp32')] = {
                    'max_abs_difference': float(error.max()), 'rms_difference': float(error.square().mean().sqrt()),
                    'unequal_values': int(torch.count_nonzero(error)), 'exactly_equal': torch.equal(saved, reconstructed)}
            rows.append(row)
    save(Path('/output/roundoff.json'), {'tensors': rows, 'torch_version': torch.__version__,
         'gpu': torch.cuda.get_device_name(0), 'scale': scale, 'sources_modified': False})
    for mode in rows[0]['arithmetic']:
        print(mode, 'max error', max(r['arithmetic'][mode]['max_abs_difference'] for r in rows),
              'exact tensors', sum(r['arithmetic'][mode]['exactly_equal'] for r in rows), '/', len(rows), flush=True)


if __name__ == '__main__':
    main()
