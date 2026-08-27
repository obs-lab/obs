import os
import sys
import threading
import subprocess
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
_OBS_THREADS = os.environ.get("OBS_THREADS", "").strip()
if _OBS_THREADS:
    os.environ["OMP_NUM_THREADS"] = _OBS_THREADS
    os.environ["MKL_NUM_THREADS"] = _OBS_THREADS
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("DISABLE_TQDM", "1")

BACKEND_DIR = Path(__file__).parent


def _download_command(flag):
    if getattr(sys, "frozen", False):
        return [sys.executable, flag]
    return [sys.executable, str(BACKEND_DIR / "main.py"), flag]

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    TARGET_DIR = Path(_OBS_DATA_ENV) / "models" / "bge-m3"
else:
    TARGET_DIR = BACKEND_DIR / "models" / "bge-m3"

MODEL_REPO = "BAAI/bge-m3"
WEIGHT_BIN = "pytorch_model.bin"
WEIGHT_SAFE = "model.safetensors"
CONFIG_PATTERNS = ["*.json", "*.model", "1_Pooling/*"]

_state = {
    "status": "idle",
    "phase": "",
    "error": "",
}
_lock = threading.Lock()
_thread = None


def models_ready() -> bool:
    return (TARGET_DIR / WEIGHT_SAFE).exists() and (TARGET_DIR / "config.json").exists()


def get_status() -> dict:
    with _lock:
        snapshot = dict(_state)
    snapshot["ready"] = models_ready()
    return snapshot


def _set(status=None, phase=None, error=None):
    with _lock:
        if status is not None:
            _state["status"] = status
        if phase is not None:
            _state["phase"] = phase
        if error is not None:
            _state["error"] = error


def _convert_bin_to_safetensors(bin_path: Path, safe_path: Path) -> bool:
    try:
        import torch
        from safetensors.torch import save_file
    except Exception:
        return False
    try:
        state = torch.load(str(bin_path), map_location="cpu", weights_only=True)
    except Exception:
        return False
    if not isinstance(state, dict):
        return False
    tensors = {}
    for key, value in state.items():
        if hasattr(value, "contiguous"):
            tensors[key] = value.contiguous().clone()
    try:
        save_file(tensors, str(safe_path), metadata={"format": "pt"})
    except Exception:
        return False
    return True


def run_download_blocking() -> int:
    if models_ready():
        return 0
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass
    try:
        from huggingface_hub import snapshot_download, hf_hub_download
    except Exception as e:
        print("huggingface_hub not available:", e)
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    try:
        snapshot_download(repo_id=MODEL_REPO, local_dir=str(TARGET_DIR),
                          allow_patterns=CONFIG_PATTERNS, max_workers=1)
    except Exception as e:
        print("configuration download failed:", e)
        return 1

    bin_path = TARGET_DIR / WEIGHT_BIN
    safe_path = TARGET_DIR / WEIGHT_SAFE
    try:
        hf_hub_download(repo_id=MODEL_REPO, filename=WEIGHT_BIN,
                        local_dir=str(TARGET_DIR))
    except Exception as e:
        print("weights download failed:", e)
        return 1

    if not _convert_bin_to_safetensors(bin_path, safe_path):
        print("weight conversion failed")
        return 1
    try:
        bin_path.unlink()
    except Exception:
        pass

    if not models_ready():
        print("setup incomplete after download")
        return 1
    return 0


def _run_download_subprocess():
    if models_ready():
        _set(status="done", phase="already present", error="")
        return
    _set(status="running", phase="downloading", error="")
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    env["TQDM_DISABLE"] = "1"
    env["DISABLE_TQDM"] = "1"
    log_path = TARGET_DIR.parent / "download.log"
    try:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as logf:
            proc = subprocess.run(
                _download_command("--download-models"),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
    except Exception as e:
        _set(status="error", error="subprocess failed: " + str(e))
        return
    if proc.returncode != 0:
        tail = ""
        try:
            tail = open(log_path).read()[-400:]
        except Exception:
            pass
        _set(status="error", error="exit code " + str(proc.returncode) + ": " + tail)
        return
    if not models_ready():
        _set(status="error", error="setup incomplete after download")
        return
    _set(status="done", phase="complete", error="")


def start_download() -> dict:
    global _thread
    with _lock:
        if _state["status"] == "running":
            return {"started": False, "reason": "already running"}
        _state["status"] = "running"
        _state["phase"] = "starting"
        _state["error"] = ""
    _thread = threading.Thread(target=_run_download_subprocess, daemon=True)
    _thread.start()
    return {"started": True}


SPACY_MODEL_NAME = "it_core_news_lg"
SPACY_MODEL_VERSION = "3.8.0"
SPACY_WHL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    + SPACY_MODEL_NAME + "-" + SPACY_MODEL_VERSION + "/"
    + SPACY_MODEL_NAME + "-" + SPACY_MODEL_VERSION + "-py3-none-any.whl"
)

if _OBS_DATA_ENV:
    SPACY_DIR = Path(_OBS_DATA_ENV) / "models" / "spacy"
else:
    SPACY_DIR = BACKEND_DIR / "models" / "spacy"

SPACY_MODEL_DIR = SPACY_DIR / SPACY_MODEL_NAME

_spacy_state = {
    "status": "idle",
    "phase": "",
    "error": "",
}
_spacy_lock = threading.Lock()
_spacy_thread = None


def spacy_model_path():
    if not SPACY_MODEL_DIR.exists():
        return None
    inner = SPACY_MODEL_DIR / (SPACY_MODEL_NAME + "-" + SPACY_MODEL_VERSION)
    if (inner / "config.cfg").exists():
        return str(inner)
    if (SPACY_MODEL_DIR / "config.cfg").exists():
        return str(SPACY_MODEL_DIR)
    for cfg in SPACY_MODEL_DIR.rglob("config.cfg"):
        return str(cfg.parent)
    return None


def spacy_ready():
    return spacy_model_path() is not None


def spacy_status():
    with _spacy_lock:
        snap = dict(_spacy_state)
    snap["ready"] = spacy_ready()
    return snap


def _spacy_set(status=None, phase=None, error=None):
    with _spacy_lock:
        if status is not None:
            _spacy_state["status"] = status
        if phase is not None:
            _spacy_state["phase"] = phase
        if error is not None:
            _spacy_state["error"] = error


def run_spacy_download_blocking() -> int:
    if spacy_ready():
        return 0
    import urllib.request
    import zipfile
    import tempfile

    SPACY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_whl = SPACY_DIR / ("_" + SPACY_MODEL_NAME + ".whl")
    try:
        with urllib.request.urlopen(SPACY_WHL_URL, timeout=120) as resp:
            data = resp.read()
        tmp_whl.write_bytes(data)
    except Exception as e:
        print("spacy download failed:", e)
        return 1

    try:
        target = SPACY_MODEL_DIR
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(tmp_whl), "r") as zf:
            zf.extractall(str(target))
    except Exception as e:
        print("spacy extraction failed:", e)
        return 1
    finally:
        try:
            tmp_whl.unlink()
        except Exception:
            pass

    if not spacy_ready():
        print("spacy model not usable after extraction")
        return 1
    return 0


def _run_spacy_subprocess():
    if spacy_ready():
        _spacy_set(status="done", phase="already present", error="")
        return
    _spacy_set(status="running", phase="downloading", error="")
    env = dict(os.environ)
    log_path = SPACY_DIR / "spacy_download.log"
    try:
        SPACY_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as logf:
            proc = subprocess.run(
                _download_command("--download-spacy"),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
    except Exception as e:
        _spacy_set(status="error", error="subprocess failed: " + str(e))
        return
    if proc.returncode != 0:
        tail = ""
        try:
            tail = open(log_path).read()[-400:]
        except Exception:
            pass
        _spacy_set(status="error", error="exit code " + str(proc.returncode) + ": " + tail)
        return
    if not spacy_ready():
        _spacy_set(status="error", error="setup incomplete after download")
        return
    _spacy_set(status="done", phase="complete", error="")


def start_spacy_download() -> dict:
    global _spacy_thread
    with _spacy_lock:
        if _spacy_state["status"] == "running":
            return {"started": False, "reason": "already running"}
        _spacy_state["status"] = "running"
        _spacy_state["phase"] = "starting"
        _spacy_state["error"] = ""
    _spacy_thread = threading.Thread(target=_run_spacy_subprocess, daemon=True)
    _spacy_thread.start()
    return {"started": True}


def remove_spacy() -> dict:
    import shutil
    if not SPACY_DIR.exists():
        return {"removed": False, "reason": "not present"}
    try:
        shutil.rmtree(str(SPACY_DIR))
    except Exception as e:
        return {"removed": False, "reason": str(e)}
    with _spacy_lock:
        _spacy_state["status"] = "idle"
        _spacy_state["phase"] = ""
        _spacy_state["error"] = ""
    return {"removed": True}


def remove_embedding() -> dict:
    import shutil
    if not TARGET_DIR.exists():
        return {"removed": False, "reason": "not present"}
    try:
        shutil.rmtree(str(TARGET_DIR))
    except Exception as e:
        return {"removed": False, "reason": str(e)}
    with _lock:
        _state["status"] = "idle"
        _state["phase"] = ""
        _state["error"] = ""
    return {"removed": True}


CLIP_REPO = "sentence-transformers/clip-ViT-B-32"

if _OBS_DATA_ENV:
    CLIP_DIR = Path(_OBS_DATA_ENV) / "models" / "clip"
else:
    CLIP_DIR = BACKEND_DIR / "models" / "clip"

_clip_state = {
    "status": "idle",
    "phase": "",
    "error": "",
}
_clip_lock = threading.Lock()
_clip_thread = None


def clip_ready():
    if not CLIP_DIR.exists():
        return False
    if (CLIP_DIR / "modules.json").exists():
        return True
    for _ in CLIP_DIR.rglob("modules.json"):
        return True
    return False


def clip_path():
    if not CLIP_DIR.exists():
        return None
    if (CLIP_DIR / "modules.json").exists():
        return str(CLIP_DIR)
    for m in CLIP_DIR.rglob("modules.json"):
        return str(m.parent)
    return None


def clip_status():
    with _clip_lock:
        snap = dict(_clip_state)
    snap["ready"] = clip_ready()
    return snap


def _clip_set(status=None, phase=None, error=None):
    with _clip_lock:
        if status is not None:
            _clip_state["status"] = status
        if phase is not None:
            _clip_state["phase"] = phase
        if error is not None:
            _clip_state["error"] = error


def run_clip_download_blocking() -> int:
    if clip_ready():
        return 0
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass
    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        print("huggingface_hub not available:", e)
        return 1

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(repo_id=CLIP_REPO, local_dir=str(CLIP_DIR), max_workers=1)
    except Exception as e:
        print("clip download failed:", e)
        return 1

    if not clip_ready():
        print("clip model not usable after download")
        return 1
    return 0


def _run_clip_subprocess():
    if clip_ready():
        _clip_set(status="done", phase="already present", error="")
        return
    _clip_set(status="running", phase="downloading", error="")
    env = dict(os.environ)
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    env["TQDM_DISABLE"] = "1"
    env["DISABLE_TQDM"] = "1"
    log_path = CLIP_DIR.parent / "clip_download.log"
    try:
        CLIP_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as logf:
            proc = subprocess.run(
                _download_command("--download-clip"),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
    except Exception as e:
        _clip_set(status="error", error="subprocess failed: " + str(e))
        return
    if proc.returncode != 0:
        tail = ""
        try:
            tail = open(log_path).read()[-400:]
        except Exception:
            pass
        _clip_set(status="error", error="exit code " + str(proc.returncode) + ": " + tail)
        return
    if not clip_ready():
        _clip_set(status="error", error="setup incomplete after download")
        return
    _clip_set(status="done", phase="complete", error="")


def start_clip_download() -> dict:
    global _clip_thread
    with _clip_lock:
        if _clip_state["status"] == "running":
            return {"started": False, "reason": "already running"}
        _clip_state["status"] = "running"
        _clip_state["phase"] = "starting"
        _clip_state["error"] = ""
    _clip_thread = threading.Thread(target=_run_clip_subprocess, daemon=True)
    _clip_thread.start()
    return {"started": True}


def remove_clip() -> dict:
    import shutil
    if not CLIP_DIR.exists():
        return {"removed": False, "reason": "not present"}
    try:
        shutil.rmtree(str(CLIP_DIR))
    except Exception as e:
        return {"removed": False, "reason": str(e)}
    with _clip_lock:
        _clip_state["status"] = "idle"
        _clip_state["phase"] = ""
        _clip_state["error"] = ""
    return {"removed": True}
