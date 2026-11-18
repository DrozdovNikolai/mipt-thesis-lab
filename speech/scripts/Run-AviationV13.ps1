$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$study = Join-Path $taskRoot 'reports/aviation-v13'
$driver = Join-Path $study 'frozen/scripts/run_checkpointed_asr_v13.py'
$savedAudioDirectory = $env:HYBRID_AUDIO_DIR
try {
    foreach ($phase in @('smoke', 'full')) {
        $ioRoot = Join-Path $study ('io-' + $phase)
        New-Item -ItemType Directory -Force -Path $ioRoot | Out-Null
        $env:HYBRID_AUDIO_DIR = if ($phase -eq 'smoke') { Join-Path $taskRoot 'reports/cockpit-reviewed-v12/audio' } else { Join-Path $taskRoot 'data/curated/aviation-v1/audio' }
        foreach ($stage in @('hybrid', 'consensus')) {
            if ($phase -eq 'full' -and $stage -eq 'consensus' -and (Test-Path (Join-Path $study 'generation-guard-plan.json'))) {
                & (Join-Path $PSScriptRoot 'Run-AviationV13Guard.ps1')
                if ($LASTEXITCODE -ne 0) { throw 'Guarded v11 run failed' }
                continue
            }
            $compose = if ($stage -eq 'hybrid') { 'compose.cockpit-hybrid-v10-local.yaml' } else { 'compose.cockpit-consensus-v11-local.yaml' }
            $service = if ($stage -eq 'hybrid') { 'transcribe' } else { 'refine' }
            $command = @('compose', '-f', (Join-Path $taskRoot $compose), 'run', '--rm',
                '-v', ($ioRoot + ':/output'), '-v', ($study + '/plan.json:/study/plan.json:ro'),
                '-v', ($study + '/inputs.json:/study/inputs.json:ro'),
                '-v', ($study + '/smoke-inputs.json:/study/smoke-inputs.json:ro'),
                '-v', ($driver + ':/driver/run.py:ro'), '--entrypoint', 'python',
                $service, '-u', '/driver/run.py', $stage)
            if ($phase -eq 'smoke') { $command += '--smoke' }
            & docker @command *> (Join-Path $ioRoot ($stage + '.log'))
            if ($LASTEXITCODE -ne 0) { throw ($phase + ' ' + $stage + ' failed; per-record checkpoints preserved') }
            Write-Output ($phase + ' ' + $stage + ' ready')
        }
        if ($phase -eq 'smoke') {
            & 'C:/Users/kolya/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' (Join-Path $taskRoot 'scripts/verify_aviation_v13_parity.py')
            if ($LASTEXITCODE -ne 0) { throw 'Frozen inference parity failed' }
        }
    }
    & docker run --rm --network none `
        --mount ('type=bind,source=' + (Join-Path $study 'frozen/scripts') + ',target=/work/scripts,readonly') `
        --mount ('type=bind,source=' + $study + ',target=/work/reports/aviation-v13') `
        -w /work --entrypoint python north55-annotation-tools:0.1.0 /work/scripts/score_aviation_v13.py
    if ($LASTEXITCODE -ne 0) { throw 'Full-corpus scoring or integrity verification failed' }
}
finally { $env:HYBRID_AUDIO_DIR = $savedAudioDirectory }
