param([ValidateSet('small_known', 'large_known', 'both')][string]$System = 'both')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$study = Join-Path $repo 'reports/language-large-v1'
$frozen = Join-Path $study 'frozen'
if (-not (Test-Path -LiteralPath "$study/plan.json")) { throw 'Prepare and freeze the study first' }
$systems = if ($System -eq 'both') { @('small_known', 'large_known') } else { @($System) }
foreach ($selected in $systems) {
    $name = if ($selected -eq 'small_known') { 'north55-language-small-v1' } else { 'north55-language-large-v1' }
    $existing = & docker ps -a --filter "name=^/${name}$" --format '{{.Names}}'
    if ($existing) { throw "Preserve existing container $name; use docker start -a $name to intentionally resume it" }
    $arguments = @('run', '-d', '--name', $name, '--network', 'none', '--gpus', 'all',
        '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
        '--entrypoint', 'python',
        '-v', "${frozen}/scripts:/app/scripts:ro", '-v', "${frozen}/src:/app/src:ro",
        '-v', "${frozen}/configs:/app/configs:ro", '-v', "${frozen}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro",
        '-v', "${frozen}/uv.lock:/app/uv.lock:ro", '-v', "${study}:/reports/language-large-v1",
        '-v', 'north55-speech_audio_data:/audio:ro', '-v', 'north55-speech_model_cache:/models:ro',
        'north55-speech-gpu:0.1.0', '-m', 'scripts.language_large_experiment', 'infer', '--system', $selected)
    & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "Could not start $name" }
    $runExit = & docker wait $name
    if ($LASTEXITCODE -ne 0) { throw "Could not wait for $name" }
    $inspect = (& docker inspect $name | ConvertFrom-Json)[0]
    $snapshot = @{name = $name; image_id = $inspect.Image; network_mode = $inspect.HostConfig.NetworkMode;
        command = $inspect.Config.Cmd; state = $inspect.State;
        mounts = @($inspect.Mounts | Select-Object Type, Source, Destination, RW)}
    $snapshot | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath "$study/$name.json" -Encoding utf8
    & docker logs $name 2>&1 | Set-Content -LiteralPath "$study/$name.log" -Encoding utf8
    if ([int]$runExit -ne 0) { throw "$name failed with exit $runExit; outputs and logs preserved" }
    Write-Output "$name completed with exit 0"
}
