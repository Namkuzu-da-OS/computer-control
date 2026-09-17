# Logon Scheduled Task for keybridge (bare key -> modifier combo, for Wispr Flow). Idempotent.
$root = Split-Path -Parent $PSScriptRoot
$home_ = (Get-Content (Join-Path $root ".venv\pyvenv.cfg") | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
$py = Join-Path $home_ "pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$root\scripts\keybridge-launch.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ComputerControlKeybridge" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "scheduled task ComputerControlKeybridge installed"
