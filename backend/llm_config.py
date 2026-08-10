import json
import os
import threading
from pathlib import Path

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_FILE = DATA_DIR / "llm_config.json"

_lock = threading.Lock()

ALLOWED_KEYS = {
    "backend",
    "cloud_api_url",
    "cloud_model",
    "cloud_api_key",
    "cloud_api_style",
    "local_model",
    "local_api_url",
    "local_num_ctx",
    "llm_timeout",
    "report_max_tokens",
}

INT_KEYS = {"local_num_ctx", "llm_timeout", "report_max_tokens"}


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with _lock:
            raw = CONFIG_FILE.read_text()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in ALLOWED_KEYS}
    except Exception:
        return {}


def save(values: dict) -> dict:
    current = load()
    for k, v in values.items():
        if k not in ALLOWED_KEYS:
            continue
        if k in INT_KEYS:
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        current[k] = v
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        CONFIG_FILE.write_text(json.dumps(current, indent=2))
    return current
