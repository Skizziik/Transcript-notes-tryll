"""Whisper model management.

- Single cache path inside storage/models/<model-name>/.
- Catalog of supported models with size hints.
- Download with progress (huggingface_hub.snapshot_download + size polling).
- Delete a model from disk.
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import MODELS_DIR

ProgressCb = Callable[[float, int, int, str | None], None]  # frac, bytes, total, msg


@dataclass
class ModelInfo:
    name: str
    repo: str  # HF repo id
    label: str
    size_mb: int  # approximate, for display
    description: str


CATALOG: dict[str, ModelInfo] = {
    "large-v3": ModelInfo(
        name="large-v3",
        repo="Systran/faster-whisper-large-v3",
        label="large-v3",
        size_mb=3090,
        description="Лучшее качество, особенно для русского. Рекомендуется.",
    ),
    "large-v3-turbo": ModelInfo(
        name="large-v3-turbo",
        repo="deepdml/faster-whisper-large-v3-turbo-ct2",
        label="large-v3-turbo",
        size_mb=1620,
        description="Заметно быстрее, качество чуть ниже на сложной речи.",
    ),
    "medium": ModelInfo(
        name="medium",
        repo="Systran/faster-whisper-medium",
        label="medium",
        size_mb=1530,
        description="Компромисс между скоростью и качеством.",
    ),
    "small": ModelInfo(
        name="small",
        repo="Systran/faster-whisper-small",
        label="small",
        size_mb=480,
        description="Быстро, для коротких записей с чистой речью.",
    ),
    "base": ModelInfo(
        name="base",
        repo="Systran/faster-whisper-base",
        label="base",
        size_mb=145,
        description="Очень быстрая, низкое качество. Для тестов.",
    ),
}


# --- helpers -----------------------------------------------------------------


def model_dir(name: str) -> Path:
    return MODELS_DIR / name


def is_installed(name: str) -> bool:
    d = model_dir(name)
    if not d.exists():
        return False
    return (d / "model.bin").exists() or any(d.glob("**/model.bin"))


def disk_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def list_models() -> list[dict]:
    out = []
    for name, info in CATALOG.items():
        d = model_dir(name)
        installed = is_installed(name)
        out.append({
            "name": name,
            "label": info.label,
            "repo": info.repo,
            "expected_size_mb": info.size_mb,
            "description": info.description,
            "installed": installed,
            "size_bytes": disk_size(d) if installed else 0,
            "path": str(d),
        })
    return out


def delete_model(name: str) -> bool:
    d = model_dir(name)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


# --- download with progress --------------------------------------------------


@dataclass
class DownloadTask:
    name: str
    status: str = "running"  # running | done | error
    error: str | None = None
    bytes_done: int = 0
    bytes_total: int = 0
    message: str | None = None
    listeners: list[Callable[[dict], None]] = field(default_factory=list)
    _stop: bool = False


_tasks: dict[str, DownloadTask] = {}
_tasks_lock = threading.Lock()


def get_task(name: str) -> DownloadTask | None:
    with _tasks_lock:
        return _tasks.get(name)


def add_listener(name: str, cb: Callable[[dict], None]) -> bool:
    with _tasks_lock:
        t = _tasks.get(name)
        if t is None or t.status != "running":
            return False
        t.listeners.append(cb)
        return True


def _notify(t: DownloadTask) -> None:
    snapshot = {
        "name": t.name,
        "status": t.status,
        "error": t.error,
        "bytes_done": t.bytes_done,
        "bytes_total": t.bytes_total,
        "message": t.message,
    }
    for cb in list(t.listeners):
        try:
            cb(snapshot)
        except Exception:
            pass


def start_download(name: str) -> DownloadTask:
    if name not in CATALOG:
        raise ValueError(f"unknown model: {name}")

    with _tasks_lock:
        existing = _tasks.get(name)
        if existing and existing.status == "running":
            return existing
        task = DownloadTask(name=name)
        _tasks[name] = task

    threading.Thread(target=_run_download, args=(task,), daemon=True, name=f"dl-{name}").start()
    return task


def _run_download(task: DownloadTask) -> None:
    info = CATALOG[task.name]
    target = model_dir(task.name)
    target.mkdir(parents=True, exist_ok=True)

    task.message = "Получение списка файлов…"
    task.bytes_total = info.size_mb * 1024 * 1024
    _notify(task)

    # Probe actual size + file list from HF.
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        repo_info = api.repo_info(info.repo)
        sibs = getattr(repo_info, "siblings", []) or []
        sizes = []
        for s in sibs:
            sz = getattr(s, "size", None) or getattr(s, "lfs", None)
            if isinstance(sz, dict):
                sz = sz.get("size")
            if isinstance(sz, int):
                sizes.append(sz)
        if sizes:
            task.bytes_total = sum(sizes)
    except Exception:
        # Best-effort. Keep estimate.
        pass

    task.message = "Скачивание…"
    _notify(task)

    # Poll target dir size while snapshot_download runs in another thread.
    poll_stop = threading.Event()

    def poll() -> None:
        while not poll_stop.is_set():
            task.bytes_done = disk_size(target)
            _notify(task)
            poll_stop.wait(0.7)
        task.bytes_done = disk_size(target)
        _notify(task)

    poller = threading.Thread(target=poll, daemon=True, name=f"dl-poll-{task.name}")
    poller.start()

    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=info.repo,
            local_dir=str(target),
            local_dir_use_symlinks=False,
        )
        task.bytes_done = disk_size(target)
        if task.bytes_total < task.bytes_done:
            task.bytes_total = task.bytes_done
        task.status = "done"
        task.message = "Готово"
    except Exception as e:
        task.status = "error"
        task.error = str(e)
        task.message = "Ошибка"
    finally:
        poll_stop.set()
        poller.join(timeout=1.5)
        _notify(task)


def ensure_model(name: str, progress_cb: Callable[[float, str | None], None] | None = None) -> Path:
    """Make sure the model is on disk, downloading it with progress if not.

    Used by the pipeline before transcribe. Blocks until done.
    """
    target = model_dir(name)
    if is_installed(name):
        return target
    if name not in CATALOG:
        raise ValueError(f"unknown model: {name}")

    task = start_download(name)

    done = threading.Event()

    def listener(snapshot: dict) -> None:
        if progress_cb:
            frac = 0.0
            if snapshot["bytes_total"] > 0:
                frac = min(0.999, snapshot["bytes_done"] / snapshot["bytes_total"])
            progress_cb(frac, snapshot.get("message"))
        if snapshot["status"] in ("done", "error"):
            done.set()

    add_listener(name, listener)
    # In case download finishes before listener registered.
    if task.status != "running":
        done.set()

    done.wait()
    final = get_task(name)
    if final and final.status == "error":
        raise RuntimeError(f"Не удалось скачать модель {name}: {final.error}")
    if progress_cb:
        progress_cb(1.0, "Модель готова")
    return target
