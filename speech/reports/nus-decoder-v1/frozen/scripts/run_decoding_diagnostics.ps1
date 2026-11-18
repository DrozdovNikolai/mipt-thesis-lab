param(
    [Parameter(Mandatory = $true)][string]$Action,
    [string]$System
)
$ErrorActionPreference = 'Stop'
$diagnosticArgs = @((Join-Path $PSScriptRoot 'run_decoding_diagnostics.py'), $Action)
if ($System) { $diagnosticArgs += @('--system', $System) }
python @diagnosticArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
