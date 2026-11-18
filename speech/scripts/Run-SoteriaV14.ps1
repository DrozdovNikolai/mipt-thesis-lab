param([switch]$SkipAcquire)
$ErrorActionPreference = 'Stop'
$soteriaPython = 'C:/Users/kolya/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not $SkipAcquire) {
    & $soteriaPython scripts/acquire_soteria_v14.py acquire
    if ($LASTEXITCODE -ne 0) { throw 'SOTERIA acquisition failed' }
}
if (-not (Test-Path -LiteralPath reports/soteria-v14/experiment-plan.json)) {
    & $soteriaPython scripts/freeze_soteria_v14.py
    if ($LASTEXITCODE -ne 0) { throw 'SOTERIA frozen inputs differ' }
}
docker compose -f compose.soteria-v14.yaml run --rm prepare prepare
if ($LASTEXITCODE -ne 0) { throw 'SOTERIA preparation failed' }
docker compose -f compose.soteria-v14.yaml run --rm infer large
if ($LASTEXITCODE -ne 0) { throw 'SOTERIA large inference failed' }
docker compose -f compose.soteria-v14.yaml up -d review
if ($LASTEXITCODE -ne 0) { throw 'SOTERIA review startup failed' }
docker compose -f compose.soteria-v14.yaml run --rm infer small
if ($LASTEXITCODE -ne 0) { throw 'SOTERIA small inference failed' }
docker compose -f compose.soteria-v14.yaml run --rm prepare report
if ($LASTEXITCODE -ne 0) { throw 'SOTERIA verification/report failed' }
