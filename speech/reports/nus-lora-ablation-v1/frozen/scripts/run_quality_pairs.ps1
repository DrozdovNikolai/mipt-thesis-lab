param([ValidateSet('prepare', 'small', 'large', 'assemble', 'tests')][string]$Stage = 'prepare')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$name = "north55-quality-pairs-$Stage-v1"
if (& docker ps -a --filter "name=^/${name}$" --format '{{.Names}}') {
    throw "Container $name exists. Preserve it; use docker start -a $name for an intentional resume."
}
$arguments = @('run', '-d', '--name', $name, '--network', 'none',
    '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
    '--entrypoint', 'python', '-v', "${repo}/scripts:/app/scripts:ro", '-v', "${repo}/src:/app/src:ro",
    '-v', "${repo}/tests:/app/tests:ro", '-v', "${repo}/uv.lock:/app/uv.lock:ro",
    '-v', "${repo}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro", '-v', "${repo}/SPEC.md:/app/SPEC.md:ro",
    '-v', "${repo}/SOURCES.md:/app/SOURCES.md:ro", '-v', "${repo}/reports/pair-quality-v1:/study",
    '-v', 'north55-speech_model_cache:/models:ro')
if ($Stage -in @('small', 'large', 'assemble')) { $arguments += @('--gpus', 'all') }
if ($Stage -in @('small', 'large')) {
    $arguments += @('-v', "${repo}/data/curated/pair-quality-v1/plan.json:/pairs/plan.json:ro",
        '-v', "${repo}/data/curated/pair-quality-v1/${Stage}:/pairs/${Stage}",
        '-v', 'north55-speech_audio_data:/audio:ro')
} elseif ($Stage -ne 'tests') {
    $arguments += @('-v', "${repo}/data/curated/pair-quality-v1:/pairs",
        '-v', "${repo}/data/curated/publisher-expanded-v1:/old:ro",
        '-v', "${repo}/data/curated/bleriot-v2/manifests/train-dev/train.jsonl:/source-train.jsonl:ro",
        '-v', $(if ($Stage -eq 'prepare') { 'north55-speech_audio_data:/audio' } else { 'north55-speech_audio_data:/audio:ro' }))
}
$arguments += 'north55-speech-gpu:0.1.0'
if ($Stage -eq 'tests') {
    $arguments += @('-m', 'pytest', 'tests/test_quality_pairs.py', 'tests/test_quality_pair_groups.py', 'tests/test_training_support_import.py', 'tests/unit/test_publisher_training.py', '-q', '--junitxml=/study/contracts-v3.xml')
} elseif ($Stage -eq 'assemble') {
    $arguments += @('-m', 'scripts.assemble_quality_pairs')
} else {
    $arguments += @('-m', 'scripts.prepare_quality_pairs')
    $arguments += $(if ($Stage -in @('small', 'large')) { @('infer', '--system', $Stage) } else { @($Stage) })
}
& docker @arguments
if ($LASTEXITCODE -ne 0) { throw "Could not start $name" }
Write-Output "Started $name. Read progress with docker logs $name; wait with docker wait $name."
