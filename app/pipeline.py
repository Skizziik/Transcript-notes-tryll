from __future__ import annotations

import asyncio
import json
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
    audio_paths: list[Path]
    audio_names: list[str]
    audio_sizes: list[int]
    run_dir: Path
    settings: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop: asyncio.AbstractEventLoop | None = None
    status: str = "queued"
    history_replay: list[dict] = field(default_factory=list)
    notes_buffer: list[str] = field(default_factory=list)

    @property
    def audio_path(self) -> Path:
        return self.audio_paths[0]

    @property
    def audio_name(self) -> str:
        if len(self.audio_names) == 1:
            return self.audio_names[0]
        return f"{self.audio_names[0]} (+{len(self.audio_names) - 1})"

    @property
    def audio_size(self) -> int:
        return sum(self.audio_sizes)


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


def create_run(payloads: list[tuple[bytes, str]], settings: dict) -> Run:
    """Create a run from one or more audio files (combined into a single note)."""
    if not payloads:
        raise ValueError("Не передан ни один аудиофайл.")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    multi = len(payloads) > 1

    first_name = payloads[0][1]
    run_id = new_run_id(first_name)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    audio_paths: list[Path] = []
    audio_names: list[str] = []
    audio_sizes: list[int] = []

    for idx, (data, original_name) in enumerate(payloads, start=1):
        ext = Path(original_name).suffix.lower()
        if ext not in AUDIO_EXTS:
            raise ValueError(
                f"Неподдерживаемый формат '{ext}' у файла {original_name}. "
                f"Допустимы: {', '.join(sorted(AUDIO_EXTS))}"
            )
        stem = "audio" if not multi else f"part-{idx:02d}"
        audio_path = run_dir / f"{stem}{ext}"
        audio_path.write_bytes(data)
        audio_paths.append(audio_path)
        audio_names.append(original_name)
        audio_sizes.append(len(data))

    display_name = first_name if not multi else f"{first_name} (+{len(payloads) - 1} ещё)"
    total_size = sum(audio_sizes)
    full_settings = {**settings, "part_count": len(payloads), "part_names": audio_names}

    db.create_run(
        run_id=run_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        audio_name=display_name,
        audio_size=total_size,
        run_dir=str(run_dir),
        settings=full_settings,
    )

    run = Run(
        id=run_id,
        audio_paths=audio_paths,
        audio_names=audio_names,
        audio_sizes=audio_sizes,
        run_dir=run_dir,
        settings=full_settings,
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
        total_files = len(run.audio_paths)
        multi = total_files > 1

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

        all_results: list[dict] = []
        for idx, audio_path in enumerate(run.audio_paths):
            part_name = run.audio_names[idx]
            stem = "transcript" if not multi else f"part-{idx + 1:02d}"

            def on_transcribe(progress: float, message: str | None, _idx: int = idx, _name: str = part_name) -> None:
                overall = (_idx + max(0.0, min(1.0, progress))) / total_files
                event: dict[str, Any] = {"type": "stage", "stage": "transcribe", "progress": overall}
                if multi:
                    prefix = f"[{_idx + 1}/{total_files}] "
                    event["message"] = prefix + (message or _name)
                elif message:
                    event["message"] = message
                _emit(run, event)

            tr = transcribe(
                audio_path=audio_path,
                out_dir=run.run_dir,
                language=run.settings.get("language") or None,
                model_name=model_name,
                device=run.settings.get("device") or "auto",
                compute_type=run.settings.get("compute_type") or "auto",
                progress_cb=on_transcribe,
                output_stem=stem,
            )
            all_results.append(tr)

        detected_lang = all_results[0]["language"]
        device = all_results[0]["device"]
        compute_type = all_results[0]["compute_type"]

        if multi:
            combined_text_parts: list[str] = []
            combined_segments: list[dict] = []
            duration_offset = 0.0
            for i, tr in enumerate(all_results):
                name = run.audio_names[i]
                combined_text_parts.append(f"## Часть {i + 1}: {name}\n\n{tr['text'].strip()}")
                for seg in tr["segments"]:
                    combined_segments.append({
                        "start": float(seg["start"]) + duration_offset,
                        "end": float(seg["end"]) + duration_offset,
                        "text": seg["text"],
                        "part": i + 1,
                    })
                duration_offset += float(tr["duration_sec"])
            combined_text = "\n\n".join(combined_text_parts).strip() + "\n"
            total_duration = duration_offset
            (run.run_dir / "transcript.txt").write_text(combined_text, encoding="utf-8")
            (run.run_dir / "transcript.json").write_text(
                json.dumps({
                    "language": detected_lang,
                    "duration_sec": total_duration,
                    "parts": run.audio_names,
                    "segments": combined_segments,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            final_text = combined_text
            final_segments = combined_segments
        else:
            final_text = all_results[0]["text"]
            final_segments = all_results[0]["segments"]
            total_duration = float(all_results[0]["duration_sec"])

        _emit(run, {
            "type": "transcript_ready",
            "language": detected_lang,
            "duration_sec": total_duration,
            "text": final_text,
            "device": device,
            "compute_type": compute_type,
        })
        db.update_run(
            run.id,
            language=detected_lang,
            audio_duration_sec=total_duration,
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

        tmp_notes_path = run.run_dir / "_notes.tmp.md"
        notes_md, slug = generate_notes(
            transcript=final_text,
            language=detected_lang,
            duration_sec=total_duration,
            segments=final_segments,
            out_path=tmp_notes_path,
            progress_cb=on_notes,
        )

        title = _extract_title(notes_md, fallback=Path(run.audio_name).stem)
        final_stem = _sanitize_slug(slug) or _fallback_slug(title, run.audio_name)
        notes_md_path = run.run_dir / f"{final_stem}.md"
        try:
            tmp_notes_path.replace(notes_md_path)
        except OSError:
            # Fallback: copy & remove
            notes_md_path.write_text(tmp_notes_path.read_text(encoding="utf-8"), encoding="utf-8")
            tmp_notes_path.unlink(missing_ok=True)

        _emit(run, {"type": "stage", "stage": "notes", "progress": 1.0})

        # --- docx ----
        _emit(run, {"type": "stage", "stage": "docx", "label": "Конвертация в .docx", "progress": 0.0})
        docx_path = run.run_dir / f"{final_stem}.docx"
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


_SLUG_OK_RE = re.compile(r"[^A-Za-z0-9_-]+")
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _sanitize_slug(slug: str | None) -> str | None:
    if not slug:
        return None
    s = _SLUG_OK_RE.sub("_", slug).strip("_")[:60]
    return s.lower() or None


def _fallback_slug(title: str, audio_name: str) -> str:
    src = title or Path(audio_name).stem
    transliterated = "".join(_TRANSLIT.get(ch, ch) for ch in src.lower())
    cleaned = _SLUG_OK_RE.sub("_", transliterated).strip("_")[:60]
    return cleaned or "notes"


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
    # Transcript: prefer canonical transcript.* (multi-file combined or single-file output);
    # fall back to legacy audio.* layout for back-compat with older runs.
    candidates = [("transcript_txt", ["transcript.txt", "audio.txt"]),
                  ("transcript_json", ["transcript.json", "audio.json"])]
    for key, names in candidates:
        for name in names:
            p = run_dir / name
            if p.exists():
                found[key] = name
                break

    transcript_stems = {"transcript", "audio"}
    # Part files (multi-file split) follow part-NN.txt/json — skip those too.
    for p in sorted(run_dir.glob("*.md")):
        if p.stem in transcript_stems or p.stem.startswith("part-"):
            continue
        found["notes_md"] = p.name
        break
    for p in sorted(run_dir.glob("*.docx")):
        if p.stem in transcript_stems or p.stem.startswith("part-"):
            continue
        found["notes_docx"] = p.name
        break

    for p in run_dir.glob("audio.*"):
        if p.suffix.lower() not in (".txt", ".json"):
            found["audio"] = p.name
            break
    if "audio" not in found:
        for p in run_dir.glob("part-*"):
            if p.suffix.lower() not in (".txt", ".json"):
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
