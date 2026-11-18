param(
    [Parameter(Mandatory = $true)][string]$AudioDirectory,
    [Parameter(Mandatory = $true)][string[]]$Files,
    [ValidateSet('en', 'ru', 'auto')][string]$Language = 'en',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')][string]$OutputName = ('recording-' + [guid]::NewGuid().ToString('N'))
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$audioRoot = (Resolve-Path -LiteralPath $AudioDirectory).Path
if (-not (Test-Path -LiteralPath $audioRoot -PathType Container)) { throw 'AudioDirectory must be a directory' }
$inputs = @()
foreach ($name in $Files) {
    $resolved = (Resolve-Path -LiteralPath (Join-Path $audioRoot $name)).Path
    $relative = [IO.Path]::GetRelativePath($audioRoot, $resolved)
    if ($relative -eq '..' -or $relative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar) -or [IO.Path]::IsPathRooted($relative)) {
        throw 'Every audio file must be inside AudioDirectory'
    }
    $inputs += '/input/' + $relative.Replace('\', '/')
}
$outputRoot = Join-Path $taskRoot 'reports/cockpit-consensus-v11/local-runtime/output'
$baseFile = Join-Path $outputRoot ($OutputName + '-base.json')
$finalFile = Join-Path $outputRoot ($OutputName + '.json')
if ((Test-Path -LiteralPath $baseFile) -or (Test-Path -LiteralPath $finalFile)) { throw 'Choose a new OutputName' }
$savedAudioDirectory = $env:HYBRID_AUDIO_DIR
try {
    $env:HYBRID_AUDIO_DIR = $audioRoot
    $first = @('compose', '-f', (Join-Path $taskRoot 'compose.cockpit-hybrid-v10-local.yaml'),
        'run', '--rm', '-v', ($outputRoot + ':/output'), 'transcribe') + $inputs +
        @('--language', $Language, '--output', ('/output/' + $OutputName + '-base.json'))
    & docker @first
    if ($LASTEXITCODE -ne 0) { throw 'Base ASR failed; inspect its output before retrying' }
    $second = @('compose', '-f', (Join-Path $taskRoot 'compose.cockpit-consensus-v11-local.yaml'),
        'run', '--rm', 'refine', '--base', ('/output/' + $OutputName + '-base.json'),
        '--output', ('/output/' + $OutputName + '.json'))
    & docker @second
    if ($LASTEXITCODE -ne 0) { throw ('Consensus failed; base ASR is preserved at ' + $baseFile) }
    Write-Output $finalFile
}
finally {
    $env:HYBRID_AUDIO_DIR = $savedAudioDirectory
}
