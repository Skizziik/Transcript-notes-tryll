from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage"
RUNS_DIR = STORAGE_DIR / "runs"
UPLOADS_DIR = STORAGE_DIR / "uploads"
MODELS_DIR = STORAGE_DIR / "models"
DB_PATH = STORAGE_DIR / "history.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Pin HuggingFace cache into our storage/ so model downloads go there too —
# applies to any code path that uses huggingface_hub under the hood.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "_hf"))
os.environ.setdefault("HF_HUB_CACHE", str(MODELS_DIR / "_hf" / "hub"))

DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
DEFAULT_WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
DEFAULT_WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "auto")

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".mp4", ".mov", ".opus", ".aac", ".flac", ".aiff", ".ogg", ".webm"}


def ensure_dirs() -> None:
    for p in (STORAGE_DIR, RUNS_DIR, UPLOADS_DIR, MODELS_DIR):
        p.mkdir(parents=True, exist_ok=True)
