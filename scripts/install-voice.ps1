# Logon Scheduled Task for the voice front end (bubble + talk key). Idempotent.
# Uses the BASE interpreter's pythonw.exe (true GUI subsystem) via scripts\voice-launch.py; the venv's
# pythonw.exe is a uv trampoline that spawns a console python.exe and shows a terminal window.
$root = Split-Path -Parent $PSScriptRoot
$home_ = (Get-Content (Join-Path $root ".venv\pyvenv.cfg") | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
$py = Join-Path $home_ "pythonw.exe"
if (-not (Test-Path $py)) { throw "pythonw.exe not found at $py" }
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$root\scripts\voice-launch.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ComputerControlVoice" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "scheduled task ComputerControlVoice installed (starts at next logon; run scripts\start-voice.ps1 to start now)"
