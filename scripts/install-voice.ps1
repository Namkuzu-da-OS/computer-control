# Logon Scheduled Task for the voice front end (bubble + talk key). Idempotent.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "-m computer_control.voice.app" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ComputerControlVoice" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "scheduled task ComputerControlVoice installed (starts at next logon; run scripts\start-voice.ps1 to start now)"
