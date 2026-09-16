# Start (or restart) the voice front end now.
$root = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object { $_.CommandLine -match 'computer_control\.voice\.app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
Start-Process -FilePath (Join-Path $root ".venv\Scripts\pythonw.exe") -ArgumentList "-m computer_control.voice.app" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "voice app started; log: $root\logs\voice.log"
