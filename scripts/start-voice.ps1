# Start (or restart) the voice front end now, with no console window (via the scheduled task).
$root = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'computer_control\.voice\.app|voice-launch\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
Start-Sleep 1
if (-not (Get-ScheduledTask -TaskName "ComputerControlVoice" -ErrorAction SilentlyContinue)) { & (Join-Path $PSScriptRoot "install-voice.ps1") }
Start-ScheduledTask -TaskName "ComputerControlVoice"
Write-Host "voice app started; log: $root\logs\voice.log"
