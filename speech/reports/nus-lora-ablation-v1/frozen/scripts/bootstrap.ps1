$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path -LiteralPath '.env') {
    Write-Output '.env exists; preserved.'
    exit 0
}
function New-LocalSecret {
    $taskBytes = New-Object byte[] 32
    $taskRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $taskRng.GetBytes($taskBytes)
    $taskRng.Dispose()
    return ([BitConverter]::ToString($taskBytes)).Replace('-', '').ToLowerInvariant()
}
$taskLines = @('POSTGRES_PASSWORD','RABBITMQ_PASSWORD','NORTH55_API_KEY','NORTH55_SESSION_SECRET') | ForEach-Object { $_ + '=' + (New-LocalSecret) }
[System.IO.File]::WriteAllLines((Join-Path $PWD '.env'), $taskLines, [System.Text.UTF8Encoding]::new($false))
foreach ($taskDir in @('data/input','data/curated','data/manifests/train-dev','data/manifests/test-inference','data/sealed','reports')) {
    New-Item -ItemType Directory -Force -Path $taskDir | Out-Null
}
Write-Output 'Created local .env. Secrets were not printed.'

