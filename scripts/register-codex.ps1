# Registers the SAME MCP adapter with OpenAI Codex CLI/app via ~/.codex/config.toml.
$root = Split-Path -Parent $PSScriptRoot
$py = (Join-Path $root ".venv\Scripts\python.exe")
$toml = Join-Path $env:USERPROFILE ".codex\config.toml"
$content = Get-Content $toml -Raw
if ($content -match '\[mcp_servers\.computer_control\]') { Write-Host "already registered in $toml"; exit 0 }
Copy-Item $toml "$toml.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
$block = @"

[mcp_servers.computer_control]
command = '$py'
args = ["-m", "computer_control.adapters.mcp_server", "--client", "codex"]
startup_timeout_sec = 60

[mcp_servers.computer_control.env]
PYTHONPATH = '$root'
"@
Add-Content -Path $toml -Value $block -Encoding utf8
Write-Host "added [mcp_servers.computer_control] to $toml (backup kept)"
