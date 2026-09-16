# Registers the MCP adapter with Claude Code at user scope (available in every project).
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
claude mcp remove -s user computer-control 2>$null | Out-Null
claude mcp add -s user computer-control -- $py -m computer_control.adapters.mcp_server --client claude-code
claude mcp list
