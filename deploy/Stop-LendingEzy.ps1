$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stateFile = Join-Path $root '.local\run-pids.json'
if (Test-Path $stateFile) {
  $state = Get-Content -Raw $stateFile | ConvertFrom-Json
  foreach ($name in @('admin','frontend','api')) {
    $processId = $state.$name
    if ($processId) { & taskkill.exe /PID $processId /T /F 2>$null | Out-Null }
  }
  Remove-Item $stateFile -Force
}
$secretFile = Join-Path $root '.env.local.test'
if (Test-Path $secretFile) {
  & docker compose --env-file $secretFile -f (Join-Path $root 'deploy\compose.local.yml') stop db mailpit
}
Write-Host 'Lending Ezy local processes stopped. PostgreSQL test data has been preserved.'
