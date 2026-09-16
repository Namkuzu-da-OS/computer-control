# Starts the computer-control service detached (no console window). Idempotent.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\pythonw.exe"
& (Join-Path $root ".venv\Scripts\python.exe") -c "from computer_control.service.config import load_config; load_config()"
$cfg = Get-Content (Join-Path $root "config\config.json") -Raw | ConvertFrom-Json
try {
  $h = Invoke-RestMethod "http://127.0.0.1:$($cfg.port)/health" -TimeoutSec 2
  Write-Host "already running (pid $($h.pid), $($h.tools) tools)"; exit 0
} catch {}
Start-Process -FilePath $py -ArgumentList "-m computer_control.service.app" -WorkingDirectory $root -WindowStyle Hidden
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  try { $h = Invoke-RestMethod "http://127.0.0.1:$($cfg.port)/health" -TimeoutSec 1; Write-Host "started (pid $($h.pid), $($h.tools) tools) on http://$($cfg.host):$($cfg.port)"; exit 0 } catch {}
}
Write-Error "service did not come up; run '.venv\Scripts\python.exe -m computer_control.service.app' in a console to see the error"
