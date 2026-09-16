"""Local computer-control layer for this Windows workstation.

Layers:
  core/      pure Python + Win32/UIA primitives (no server, no agent knowledge)
  registry   one tool table (name, schema, fn) shared by every adapter
  service/   FastAPI REST on localhost - the long-running control engine
  adapters/  thin protocol shims (MCP stdio today) that talk to the service
"""
__version__ = "0.1.0"
