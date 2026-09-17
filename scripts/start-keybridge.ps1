# Start (or restart) keybridge now, via its scheduled task (no console window).
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'keybridge-launch\.py|computer_control\.keybridge' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
Start-Sleep 1
if (-not (Get-ScheduledTask -TaskName "ComputerControlKeybridge" -ErrorAction SilentlyContinue)) { & (Join-Path $PSScriptRoot "install-keybridge.ps1") }
Start-ScheduledTask -TaskName "ComputerControlKeybridge"
Write-Host "keybridge started"
