$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-ComposeChecked {
    & docker compose @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit $LASTEXITCODE" }
}
try {
    Invoke-ComposeChecked stop rabbitmq
    Invoke-ComposeChecked --profile tools run --rm tools selftest create-job --kind short
    Invoke-ComposeChecked start rabbitmq
    Invoke-ComposeChecked --profile tools run --rm tools selftest wait-job --kind short
    Invoke-ComposeChecked --profile tools run --rm tools selftest create-job --kind long
    Invoke-ComposeChecked --profile tools run --rm tools selftest wait-running --kind long
    Invoke-ComposeChecked kill -s SIGKILL worker
    Invoke-ComposeChecked up -d worker
    Invoke-ComposeChecked --profile tools run --rm tools selftest wait-job --kind long
} finally {
    & docker compose start rabbitmq worker
}
