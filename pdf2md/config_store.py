"""Чтение и сохранение config.json (API-ключи, выбранный язык и т.п.)."""

import json
from .constants import CONFIG_DIR, CONFIG_FILE

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if "api_key" in cfg and "api_keys" not in cfg:
            cfg["api_keys"] = {"llamaparse": cfg.pop("api_key")}
        return cfg
    return {}

def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
