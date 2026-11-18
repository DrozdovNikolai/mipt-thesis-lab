param(
    [ValidateSet('score', 'report', 'verify')]
    [string]$Action = 'score'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$frozen = Join-Path $repo 'reports/additional-sources-v1/frozen'
if (-not (Test-Path -LiteralPath "$frozen/manifest.json")) { throw 'Frozen experiment source is missing' }
$module = switch ($Action) {
    'score' { 'scripts.additional_asr_experiment' }
    'report' { 'scripts.report_additional_sources' }
    'verify' { 'scripts.verify_additional_sources' }
}
$arguments = @(
    'run', '--rm', '--network', 'none', '--entrypoint', 'python',
    '-v', "${frozen}/scripts:/app/scripts:ro",
    '-v', "${frozen}/src:/app/src:ro",
    '-v', "${frozen}/configs:/app/configs:ro",
    '-v', "${frozen}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro",
    '-v', "${frozen}/uv.lock:/app/uv.lock:ro",
    '-v', "${repo}/scripts/report_additional_sources.py:/app/scripts/report_additional_sources.py:ro",
    '-v', "${repo}/scripts/verify_additional_sources.py:/app/scripts/verify_additional_sources.py:ro",
    '-v', "${repo}/reports:/reports",
    '-v', "${repo}/data/curated/additional-audio-v1:/additional-audio:ro",
    '-v', "${repo}/data/curated/cvr-native-v1:/cvr:ro",
    '-v', "${repo}/data/input/bleriot/bleriot-b:/source-b:ro",
    '-v', "${repo}/data/input/fleurs-ru-v1:/fleurs:ro",
    '-v', 'north55-speech_audio_data:/audio:ro',
    '-v', 'north55-speech_model_cache:/models:ro',
    'north55-speech:login-fix-v1', '-m', $module
)
if ($Action -eq 'score') { $arguments += 'score' }
& docker @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
