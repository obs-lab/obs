import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

MODEL_REPO = "BAAI/bge-m3"
_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    TARGET_DIR = Path(_OBS_DATA_ENV) / "models" / "bge-m3"
else:
    TARGET_DIR = Path(__file__).parent / "backend" / "models" / "bge-m3"

CONFIG_PATTERNS = [
    "*.json",
    "*.model",
    "1_Pooling/*",
]

WEIGHT_BIN = "pytorch_model.bin"
WEIGHT_SAFE = "model.safetensors"


def _marker_ok(target: Path) -> bool:
    return (target / WEIGHT_SAFE).exists() and (target / "config.json").exists()


def _convert_bin_to_safetensors(bin_path: Path, safe_path: Path) -> bool:
    try:
        import torch
        from safetensors.torch import save_file
    except Exception as e:
        print("Conversion libraries not available:", e)
        return False

    try:
        state = torch.load(str(bin_path), map_location="cpu", weights_only=True)
    except Exception as e:
        print("Failed to read the weights file:", e)
        return False

    if not isinstance(state, dict):
        print("Unrecognized weights format.")
        return False

    tensors = {}
    for key, value in state.items():
        if hasattr(value, "contiguous"):
            tensors[key] = value.contiguous().clone()

    metadata = {"format": "pt"}
    try:
        save_file(tensors, str(safe_path), metadata=metadata)
    except Exception as e:
        print("Conversion to safetensors failed:", e)
        return False
    return True


def main() -> int:
    if _marker_ok(TARGET_DIR):
        print("BGE-M3 model already present in", TARGET_DIR)
        return 0

    try:
        from huggingface_hub import snapshot_download, hf_hub_download
    except Exception as e:
        print("huggingface_hub not available:", e)
        print("Run first: pip install -r requirements.txt")
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print("Preparing the BGE-M3 embedding model...")
    print("Destination:", TARGET_DIR)
    print("About 2.3 GB to download, only on first run.")

    try:
        snapshot_download(
            repo_id=MODEL_REPO,
            local_dir=str(TARGET_DIR),
            allow_patterns=CONFIG_PATTERNS,
        )
    except Exception as e:
        print("Configuration files download failed:", e)
        return 1

    bin_path = TARGET_DIR / WEIGHT_BIN
    safe_path = TARGET_DIR / WEIGHT_SAFE

    try:
        print("Downloading weights (", WEIGHT_BIN, "), this may take several minutes...")
        hf_hub_download(
            repo_id=MODEL_REPO,
            filename=WEIGHT_BIN,
            local_dir=str(TARGET_DIR),
        )
    except Exception as e:
        print("Weights download failed:", e)
        return 1

    print("Converting weights to safetensors format...")
    if not _convert_bin_to_safetensors(bin_path, safe_path):
        return 1

    try:
        bin_path.unlink()
    except Exception:
        pass

    if not _marker_ok(TARGET_DIR):
        print("Setup incomplete: safetensors file or config missing.")
        return 1

    print("BGE-M3 model ready in", TARGET_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())