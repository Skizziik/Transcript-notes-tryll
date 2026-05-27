from __future__ import annotations

import asyncio
import re
import shutil
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import db, models as model_mgr
from .config import AUDIO_EXTS, RUNS_DIR, UPLOADS_DIR
from .md_to_docx import convert as md_to_docx
from .notes_generator import generate_notes
from .transcribe import transcribe

# --- Run model & event bus ---------------------------------------------------


@dataclass
class Run:
    id: str
    audio_path: Path
    audio_name: str
    audio_size: int
    run_dir: Path
    settings: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop: asyncio.AbstractEventLoop | None = None
    status: str = "queued"
    history_replay: list[dict] = field(default_factory=list)
    notes_buffer: list[str] = field(default_factory=list)


_runs: dict[str, Run] = {}
_runs_lock = threading.Lock()


def get_run(run_id: str) -> Run | None:
    with _runs_lock:
        return _runs.get(run_id)


def register_run(run: Run) -> None:
    with _runs_lock:
        _runs[run.id] = run


def _emit(run: Run, event: dict[str, Any]) -> None:
    run.history_replay.append(event)
    # Cap history to keep memory bounded; notes deltas are bulky.
    if len(run.history_replay) > 5000:
        run.history_replay = run.history_replay[-3000:]
    if run.loop is None:
        return
    try:
        run.loop.call_soon_threadsafe(run.queue.put_nowait, event)
    except RuntimeError:
        pass


# --- Public API --------------------------------------------------------------


def new_run_id(audio_name: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(audio_name).stem)[:60] or "audio"
    short = uuid.uuid4().hex[:6]
    return f"{ts}_{safe}_{short}"


def create_run(audio_bytes: bytes, original_name: str, settings: dict) -> Run:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(original_name).suffix.lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(f"Неподдерживаемый формат '{ext}'. Допустимы: {', '.join(sorted(AUDIO_EXTS))}")

    run_id = new_run_id(original_name)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    audio_path = run_dir / f"audio{ext}"
    audio_path.write_bytes(audio_bytes)

    db.create_run(
        run_id=run_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        audio_name=original_name,
        audio_size=len(audio_bytes),
        run_dir=str(run_dir),
        settings=settings,
    )

    run = Run(
        id=run_id,
        audio_path=audio_path,
        audio_name=original_name,
        audio_size=len(audio_bytes),
        run_dir=run_dir,
        settings=settings,
    )
    register_run(run)
    return run


def start_run(run: Run, loop: asyncio.AbstractEventLoop) -> None:
    run.loop = loop
    run.status = "running"
    db.update_run(run.id, status="running")

    t = threading.Thread(target=_run_pipeline, args=(run,), daemon=True, name=f"pipeline-{run.id}")
    t.start()


# --- Worker thread -----------------------------------------------------------


def _run_pipeline(run: Run) -> None:
    try:
        model_name = run.settings.get("whisper_model") or "large-v3"

        # --- model availability check / download ----
        if not model_mgr.is_installed(model_name) and model_name in model_mgr.CATALOG:
            _emit(run, {
                "type": "stage", "stage": "model", "label": "Скачивание модели",
                "message": f"{model_name} ({model_mgr.CATALOG[model_name].size_mb} MB)",
                "progress": 0.0,
            })

            def on_model(frac: float, message: str | None) -> None:
                event: dict[str, Any] = {"type": "stage", "stage": "model", "progress": frac}
                if message:
                    event["message"] = message
                _emit(run, event)

            model_mgr.ensure_model(model_name, progress_cb=on_model)
            _emit(run, {"type": "stage", "stage": "model", "progress": 1.0})

        _emit(run, {"type": "stage", "stage": "transcribe", "label": "Транскрипция", "progress": 0.0})

        def on_transcribe(progress: float, message: str | None) -> None:
            event: dict[str, Any] = {"type": "stage", "stage": "transcribe", "progress": progress}
            if message:
                event["message"] = message
            _emit(run, event)

        tr = transcribe(
            audio_path=run.audio_path,
            out_dir=run.run_dir,
            language=run.settings.get("language") or None,
            model_name=model_name,
            device=run.settings.get("device") or "auto",
            compute_type=run.settings.get("compute_type") or "auto",
            progress_cb=on_transcribe,
        )

        _emit(run, {
            "type": "transcript_ready",
            "language": tr["language"],
            "duration_sec": tr["duration_sec"],
            "text": tr["text"],
            "device": tr["device"],
            "compute_type": tr["compute_type"],
        })
        db.update_run(
            run.id,
            language=tr["language"],
            audio_duration_sec=tr["duration_sec"],
        )

        # --- notes ----
        # No progress field → UI shows indeterminate (streaming) bar.
        _emit(run, {"type": "stage", "stage": "notes", "label": "Заметки (Claude)", "message": "стриминг от Claude…"})

        def on_notes(delta: str, message: str | None) -> None:
            if delta:
                run.notes_buffer.append(delta)
                _emit(run, {"type": "notes_delta", "text": delta})
            if message:
                _emit(run, {"type": "stage", "stage": "notes", "message": message})

        notes_md_path = run.run_dir / "notes.md"
        notes_md = generate_notes(
            transcript=tr["text"],
            language=tr["language"],
            duration_sec=tr["duration_sec"],
            segments=tr["segments"],
            out_path=notes_md_path,
            progress_cb=on_notes,
        )

        title = _extract_title(notes_md, fallback=Path(run.audio_name).stem)
        _emit(run, {"type": "stage", "stage": "notes", "progress": 1.0})

        # --- docx ----
        _emit(run, {"type": "stage", "stage": "docx", "label": "Конвертация в .docx", "progress": 0.0})
        docx_path = run.run_dir / "notes.docx"
        md_to_docx(notes_md_path, docx_path, title=title)
        _emit(run, {"type": "stage", "stage": "docx", "progress": 1.0})

        artifacts = _collect_artifacts(run.run_dir)
        db.update_run(
            run.id,
            status="done",
            title=title,
            artifacts=artifacts,
        )
        run.status = "done"
        _emit(run, {"type": "done", "title": title, "artifacts": artifacts})

    except Exception as e:
        tb = traceback.format_exc()
        run.status = "error"
        db.update_run(run.id, status="error", error=f"{e}\n{tb}")
        _emit(run, {"type": "error", "message": str(e), "trace": tb})


def _extract_title(notes_md: str, fallback: str) -> str:
    for line in notes_md.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)$", line.strip())
        if m:
            t = m.group(1).strip()
            if t.lower().startswith("о чём"):
                continue
            return t[:120]
    return fallback


def _collect_artifacts(run_dir: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    mapping = {
        "transcript_txt": "*.txt",
        "transcript_json": "*.json",
        "notes_md": "notes.md",
        "notes_docx": "notes.docx",
    }
    for key, pattern in mapping.items():
        for p in sorted(run_dir.glob(pattern)):
            found[key] = p.name
            break
    # also list audio
    for p in run_dir.glob("audio.*"):
        found["audio"] = p.name
        break
    return found


def delete_run(run_id: str) -> bool:
    rec = db.delete_run(run_id)
    if rec and rec.get("run_dir"):
        run_dir = Path(rec["run_dir"])
        if run_dir.exists() and run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
    with _runs_lock:
        _runs.pop(run_id, None)
    return rec is not None
