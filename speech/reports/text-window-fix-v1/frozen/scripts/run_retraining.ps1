param([Parameter(Mandatory=$true)][string]$Stage, [string]$Selected, [switch]$Resume)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'run_retraining.py'), $Stage)
if ($Selected) { $arguments += @('--selected', $Selected) }
if ($Resume) { $arguments += '--resume' }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Retraining stage failed with exit $LASTEXITCODE; logs preserved" }
