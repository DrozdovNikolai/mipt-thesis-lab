param(
    [ValidateSet('score', 'report', 'verify')]
    [string]$Action = 'score'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$module = switch ($Action) {
    'score' { 'scripts.evaluate_expanded_sources' }
    'report' { 'scripts.report_expanded_sources' }
    'verify' { 'scripts.verify_expanded_sources' }
}
$arguments = @(
    'run', '--rm', '--network', 'none', '--entrypoint', 'python',
    '-v', "${repo}/scripts:/app/scripts:ro",
    '-v', "${repo}/src:/app/src:ro",
    '-v', "${repo}/configs:/app/configs:ro",
    '-v', "${repo}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro",
    '-v', "${repo}/reports:/reports",
    '-v', "${repo}/data/curated/publisher-expanded-v1:/expanded:ro",
    '-v', "${repo}/data/curated/voici-diagnostic-v1:/voici-diagnostic:ro",
    '-v', 'north55-speech_audio_data:/audio:ro',
    '-v', 'north55-speech_model_cache:/models:ro',
    'north55-speech:login-fix-v1', '-m', $module
)
if ($Action -eq 'score') { $arguments += 'score' }
& docker @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
