$root = Split-Path -Parent $PSScriptRoot
$cfg = Get-Content (Join-Path $root "config\config.json") -Raw | ConvertFrom-Json
try { $h = Invoke-RestMethod "http://127.0.0.1:$($cfg.port)/health" -TimeoutSec 2 } catch { Write-Host "not running"; exit 0 }
Stop-Process -Id $h.pid -Force -Confirm:$false
Write-Host "stopped pid $($h.pid)"
