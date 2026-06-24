from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

from . import models as model_mgr
from .config import DEFAULT_WHISPER_COMPUTE, DEFAULT_WHISPER_DEVICE, DEFAULT_WHISPER_MODEL

ProgressCb = Callable[[float, str], None]


def _register_nvidia_dll_dirs() -> None:
    """Expose pip-installed CUDA libs (nvidia-cublas-cu12, nvidia-cudnn-cu12) to ctranslate2.

    These wheels drop cublas64_12.dll / cudnn_ops*.dll into
    site-packages/nvidia/<lib>/bin/. Without this, ctranslate2's LoadLibrary
    can't find them at runtime and fails with errors like
    "Library cublas64_12.dll is not found or cannot be loaded".
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia  # type: ignore
    except ImportError:
        return
    base = Path(nvidia.__file__).resolve().parent
    for sub in ("cublas/bin", "cudnn/bin"):
        bin_dir = base / sub
        if bin_dir.exists():
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass


_register_nvidia_dll_dirs()


def _resolve_device_compute(device: str, compute: str) -> tuple[str, str]:
    if device == "auto":
        try:
            import ctranslate2  # type: ignore

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def transcribe(
    audio_path: Path,
    out_dir: Path,
    language: str | None = None,
    model_name: str = DEFAULT_WHISPER_MODEL,
    device: str = DEFAULT_WHISPER_DEVICE,
    compute_type: str = DEFAULT_WHISPER_COMPUTE,
    progress_cb: ProgressCb | None = None,
    output_stem: str | None = None,
) -> dict:
    """Transcribe audio with faster-whisper.

    Reports progress as a float in [0,1] reflecting fraction of audio duration
    that has been processed (segment.end / total duration).
    """
    from faster_whisper import WhisperModel

    out_dir.mkdir(parents=True, exist_ok=True)
    device, compute_type = _resolve_device_compute(device, compute_type)

    # Resolve the model: prefer a locally-installed copy under storage/models/<name>/.
    # If it's not there but is in our catalog, fall back to letting WhisperModel
    # itself fetch it via HF cache (which we've pinned into storage/models/_hf).
    local_path = model_mgr.model_dir(model_name)
    if model_mgr.is_installed(model_name):
        model_arg: str = str(local_path)
        label = f"локально из {local_path.name}"
    else:
        model_arg = model_name
        label = f"загрузка из HuggingFace в кэш"

    if progress_cb:
        progress_cb(0.0, f"Загрузка модели {model_name} ({label}, {device}/{compute_type})…")

    model = WhisperModel(model_arg, device=device, compute_type=compute_type)

    if progress_cb:
        progress_cb(0.02, "Распознавание…")

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
        word_timestamps=False,
    )

    total = float(info.duration or 0.0) or 1.0
    detected_lang = info.language
    collected: list[dict] = []
    full_text_parts: list[str] = []

    for seg in segments_iter:
        collected.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text})
        full_text_parts.append(seg.text)
        if progress_cb:
            frac = min(0.99, max(0.02, float(seg.end) / total))
            progress_cb(frac, None)

    if progress_cb:
        progress_cb(1.0, "Транскрипция готова")

    base = output_stem or audio_path.stem
    txt_path = out_dir / f"{base}.txt"
    json_path = out_dir / f"{base}.json"

    full_text = "".join(full_text_parts).strip() + "\n"
    txt_path.write_text(full_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "language": detected_lang,
                "duration_sec": total,
                "segments": collected,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "txt": str(txt_path),
        "json": str(json_path),
        "language": detected_lang,
        "duration_sec": total,
        "text": full_text,
        "segments": collected,
        "device": device,
        "compute_type": compute_type,
    }
