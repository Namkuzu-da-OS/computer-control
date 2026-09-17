# Creates a logon Scheduled Task so the service is always up (adapters also auto-start it on demand).
# Uses the BASE interpreter's pythonw.exe (true GUI subsystem) via scripts\service-launch.py; the venv's
# pythonw.exe is a uv trampoline that spawns a console python.exe, and closing that stray terminal killed
# the service at logon on 2026-09-17 (exit 0xC000013A) -- after which it only lived as a child of a
# Claude Code session and would have died with it.
$root = Split-Path -Parent $PSScriptRoot
$home_ = (Get-Content (Join-Path $root ".venv\pyvenv.cfg") | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
$py = Join-Path $home_ "pythonw.exe"
if (-not (Test-Path $py)) { throw "pythonw.exe not found at $py" }
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$root\scripts\service-launch.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ComputerControlService" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "scheduled task ComputerControlService installed (run scripts\start-service.ps1 or Start-ScheduledTask to start it now)"
