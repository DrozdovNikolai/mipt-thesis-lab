param([ValidateSet('score', 'report', 'verify')][string]$Action = 'score')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$frozen = Join-Path $repo 'reports/language-large-v1/frozen'
$module = switch ($Action) {
    'score' { 'scripts.language_large_experiment' }
    'report' { 'report_language_large' }
    'verify' { 'verify_language_large' }
}
$arguments = @('run', '--rm', '--network', 'none', '--entrypoint', 'python',
    '-v', "${frozen}/scripts:/app/scripts:ro", '-v', "${frozen}/src:/app/src:ro",
    '-v', "${frozen}/configs:/app/configs:ro", '-v', "${frozen}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro",
    '-v', "${frozen}/uv.lock:/app/uv.lock:ro",
    '-v', "${repo}/scripts/report_language_large.py:/app/report_language_large.py:ro",
    '-v', "${repo}/scripts/verify_language_large.py:/app/verify_language_large.py:ro",
    '-v', "${repo}/reports:/reports", '-v', "${repo}/data/curated/language-large-v1/scoring:/scoring:ro",
    '-v', "${repo}/data/curated/reviewed-pilot-v2:/reviewed:ro",
    '-v', 'north55-speech_audio_data:/audio:ro', '-v', 'north55-speech_model_cache:/models:ro',
    'north55-speech:login-fix-v1', '-m', $module)
if ($Action -eq 'score') { $arguments += 'score' }
& docker @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
