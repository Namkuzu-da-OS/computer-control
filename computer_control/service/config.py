import json
import os
import secrets

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.environ.get("CC_CONFIG") or os.path.join(ROOT, "config", "config.json")
DEFAULTS = {"host": "127.0.0.1", "port": 7710, "token": None, "default_max_width": 1600}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(24)
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({k: cfg[k] for k in DEFAULTS}, f, indent=2)
    return cfg


def base_url(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    host = "127.0.0.1" if cfg["host"] in ("0.0.0.0", "", None) else cfg["host"]
    return f"http://{host}:{cfg['port']}"

