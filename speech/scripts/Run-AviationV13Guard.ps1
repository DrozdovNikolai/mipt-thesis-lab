$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$study = Join-Path $taskRoot 'reports/aviation-v13'
$savedAudioDirectory = $env:HYBRID_AUDIO_DIR
try {
    foreach ($phase in @('replay', 'failure-fixture', 'full')) {
        $smoke = $phase -ne 'full'
        $ioRoot = Join-Path $study $(if ($smoke) { 'io-smoke' } else { 'io-full' })
        $env:HYBRID_AUDIO_DIR = Join-Path $taskRoot $(if ($smoke) { 'reports/cockpit-reviewed-v12/audio' } else { 'data/curated/aviation-v1/audio' })
        $command = @('compose', '-f', (Join-Path $taskRoot 'compose.cockpit-consensus-v11-local.yaml'), 'run', '--rm',
            '-v', ($ioRoot + ':/output'), '-v', ($study + '/plan.json:/study/plan.json:ro'),
            '-v', ($study + '/generation-guard-plan.json:/study/generation-guard-plan.json:ro'),
            '-v', ($study + '/inputs.json:/study/inputs.json:ro'),
            '-v', ($study + '/smoke-inputs.json:/study/smoke-inputs.json:ro'),
            '-v', ($study + '/frozen/scripts:/driver:ro'), '--entrypoint', 'python',
            'refine', '-u', '/driver/run_guarded_consensus_v13.py')
        if ($smoke) { $command += '--replay-smoke' }
        if ($phase -eq 'failure-fixture') { $command += '--inject-limit' }
        & docker @command *> (Join-Path $ioRoot ('guard-' + $phase + '.log'))
        if ($LASTEXITCODE -ne 0) { throw ($phase + ' guarded run failed; artifacts preserved') }
        Write-Output ($phase + ' guarded run ready')
    }
}
finally { $env:HYBRID_AUDIO_DIR = $savedAudioDirectory }
