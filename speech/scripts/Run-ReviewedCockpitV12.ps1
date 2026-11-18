$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studyRoot = Join-Path $taskRoot 'reports/cockpit-reviewed-v12'
$ioRoot = Join-Path $studyRoot 'io'
New-Item -ItemType Directory -Force -Path $ioRoot | Out-Null
$savedAudioDirectory = $env:HYBRID_AUDIO_DIR
try {
    if (-not (Test-Path -LiteralPath (Join-Path $ioRoot 'baseline.json'))) {
        & docker compose -f (Join-Path $taskRoot 'compose.cockpit-reviewed-v12.yaml') run --rm baseline *> (Join-Path $ioRoot 'baseline.log')
        if ($LASTEXITCODE -ne 0) { throw 'Baseline ASR failed; see baseline.log' }
    }
    Write-Output 'Baseline inference ready'
    $env:HYBRID_AUDIO_DIR = Join-Path $studyRoot 'audio'
    $inputs = Get-Content -LiteralPath (Join-Path $studyRoot 'inputs.json') -Raw | ConvertFrom-Json
    $audioFiles = @($inputs | ForEach-Object { '/input/' + $_.file })
    if (-not (Test-Path -LiteralPath (Join-Path $ioRoot 'hybrid.json'))) {
        $command = @('compose', '-f', (Join-Path $taskRoot 'compose.cockpit-hybrid-v10-local.yaml'),
            'run', '--rm', '-v', ($ioRoot + ':/output'), 'transcribe') + $audioFiles +
            @('--language', 'en', '--output', '/output/hybrid.json')
        & docker @command *> (Join-Path $ioRoot 'hybrid.log')
        if ($LASTEXITCODE -ne 0) { throw 'Hybrid ASR failed; see hybrid.log' }
    }
    Write-Output 'Hybrid inference ready'
    if (-not (Test-Path -LiteralPath (Join-Path $ioRoot 'consensus.json'))) {
        & docker compose -f (Join-Path $taskRoot 'compose.cockpit-consensus-v11-local.yaml') run --rm -v ($ioRoot + ':/output') refine --base /output/hybrid.json --output /output/consensus.json *> (Join-Path $ioRoot 'consensus.log')
        if ($LASTEXITCODE -ne 0) { throw 'Consensus ASR failed; see consensus.log' }
    }
    Write-Output 'Consensus inference ready'
    if (-not (Test-Path -LiteralPath (Join-Path $studyRoot 'comparison.json'))) {
        & docker compose -f (Join-Path $taskRoot 'compose.cockpit-reviewed-v12.yaml') run --rm score
        if ($LASTEXITCODE -ne 0) { throw 'Scoring failed' }
    }
}
finally {
    $env:HYBRID_AUDIO_DIR = $savedAudioDirectory
}
