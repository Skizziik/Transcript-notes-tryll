from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, models as model_mgr, pipeline
from .config import HOST, PORT, STATIC_DIR, AUDIO_EXTS, ensure_dirs
from .notes_generator import check_claude_cli

logger = logging.getLogger("transcript-notes")

app = FastAPI(title="Transcript Notes (tryll) — Windows")


@app.on_event("startup")
async def _on_startup() -> None:
    ensure_dirs()
    db.init()


@app.get("/api/health")
async def health() -> dict:
    claude_ok, claude_msg = check_claude_cli()
    return {
        "ok": True,
        "claude_cli": claude_ok,
        "claude_message": claude_msg,
        "supported_formats": sorted(AUDIO_EXTS),
    }


@app.get("/api/models")
async def list_models() -> dict:
    return {"models": model_mgr.list_models(), "cache_dir": str(model_mgr.MODELS_DIR)}


@app.post("/api/models/{name}/download")
async def download_model(name: str) -> dict:
    if name not in model_mgr.CATALOG:
        raise HTTPException(404, "unknown model")
    if model_mgr.is_installed(name):
        return {"status": "installed"}
    task = model_mgr.start_download(name)
    return {"status": task.status, "name": name}


@app.delete("/api/models/{name}")
async def delete_model(name: str) -> dict:
    if name not in model_mgr.CATALOG:
        raise HTTPException(404, "unknown model")
    ok = model_mgr.delete_model(name)
    return {"deleted": ok}


@app.websocket("/ws/models/{name}")
async def ws_model(ws: WebSocket, name: str):
    await ws.accept()
    if name not in model_mgr.CATALOG:
        await ws.send_json({"status": "error", "error": "unknown model"})
        await ws.close()
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def listener(snapshot: dict) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, snapshot)
        except RuntimeError:
            pass

    task = model_mgr.get_task(name)
    if task is None or task.status != "running":
        # Nothing to stream; just report current state and close.
        if model_mgr.is_installed(name):
            await ws.send_json({"name": name, "status": "done", "bytes_done": 0, "bytes_total": 0})
        else:
            await ws.send_json({"name": name, "status": "idle"})
        await ws.close()
        return

    if not model_mgr.add_listener(name, listener):
        await ws.send_json({"name": name, "status": "done"})
        await ws.close()
        return

    try:
        while True:
            snapshot = await queue.get()
            await ws.send_json(snapshot)
            if snapshot["status"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        return
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    return db.list_runs()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    rec = db.get_run(run_id)
    if not rec:
        raise HTTPException(404, "run not found")
    return rec


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    ok = pipeline.delete_run(run_id)
    if not ok:
        raise HTTPException(404, "run not found")
    return {"ok": True}


@app.get("/api/runs/{run_id}/file/{name}")
async def download(run_id: str, name: str):
    rec = db.get_run(run_id)
    if not rec:
        raise HTTPException(404, "run not found")
    run_dir = Path(rec["run_dir"])
    target = (run_dir / name).resolve()
    if not str(target).startswith(str(run_dir.resolve())):
        raise HTTPException(400, "invalid name")
    if not target.exists():
        raise HTTPException(404, "file not found")
    media = "application/octet-stream"
    if target.suffix.lower() == ".docx":
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif target.suffix.lower() == ".md":
        media = "text/markdown"
    elif target.suffix.lower() == ".txt":
        media = "text/plain"
    elif target.suffix.lower() == ".json":
        media = "application/json"
    return FileResponse(target, media_type=media, filename=target.name)


@app.post("/api/runs")
async def create_run(
    files: list[UploadFile],
    language: str | None = None,
    whisper_model: str | None = None,
):
    if not files:
        raise HTTPException(400, "no files")
    payloads: list[tuple[bytes, str]] = []
    for f in files:
        if not f.filename:
            raise HTTPException(400, "filename required")
        suffix = Path(f.filename).suffix.lower()
        if suffix not in AUDIO_EXTS:
            raise HTTPException(400, f"unsupported format {suffix} for {f.filename}")
        data = await f.read()
        if not data:
            raise HTTPException(400, f"empty file: {f.filename}")
        payloads.append((data, f.filename))
    settings = {
        "language": language or None,
        "whisper_model": whisper_model or "large-v3",
    }
    try:
        run = pipeline.create_run(payloads, settings)
    except ValueError as e:
        raise HTTPException(400, str(e))
    pipeline.start_run(run, asyncio.get_running_loop())
    return JSONResponse({"run_id": run.id, "status": run.status, "parts": len(payloads)})


@app.websocket("/ws/{run_id}")
async def ws_run(ws: WebSocket, run_id: str):
    await ws.accept()
    run = pipeline.get_run(run_id)
    if run is None:
        await ws.send_json({"type": "error", "message": "run not found (server restarted?)"})
        await ws.close()
        return

    # Replay history so a late connector still gets full progress.
    for event in list(run.history_replay):
        await ws.send_json(event)
    if run.status in ("done", "error"):
        await ws.close()
        return

    try:
        while True:
            event = await run.queue.get()
            await ws.send_json(event)
            if event.get("type") in ("done", "error"):
                break
    except WebSocketDisconnect:
        return
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


# Static files (UI) — mounted last so /api/* and /ws/* take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# -----------------------------------------------------------------------------
# Launcher: starts uvicorn in a background thread, then opens a pywebview window.
# Falls back to opening default browser if pywebview is unavailable.
# -----------------------------------------------------------------------------


def _run_server() -> None:
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.run()


def _wait_until_up(url: str, timeout: float = 15.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


class DesktopApi:
    """Exposed to the page as window.pywebview.api — handles 'downloads' inside
    the pywebview window (WebView2 doesn't surface a download UX on its own).
    """

    def _resolve(self, run_id: str, name: str) -> Path | None:
        rec = db.get_run(run_id)
        if not rec:
            return None
        run_dir = Path(rec["run_dir"]).resolve()
        target = (run_dir / name).resolve()
        if not str(target).startswith(str(run_dir)):
            return None
        return target if target.exists() else None

    def open_file(self, run_id: str, name: str) -> dict:
        target = self._resolve(run_id, name)
        if not target:
            return {"ok": False, "error": "файл не найден"}
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target)], check=False)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def show_in_folder(self, run_id: str, name: str) -> dict:
        target = self._resolve(run_id, name)
        if not target:
            return {"ok": False, "error": "файл не найден"}
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", f"/select,{target}"])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target.parent)], check=False)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_as(self, run_id: str, name: str, suggested_name: str | None = None) -> dict:
        target = self._resolve(run_id, name)
        if not target:
            return {"ok": False, "error": "файл не найден"}
        try:
            import webview  # type: ignore
            windows = webview.windows
            window = windows[0] if windows else None
            if window is None:
                return {"ok": False, "error": "no window"}

            suffix = target.suffix
            ext_label = suffix.upper().lstrip(".") + " file"
            file_types = (f"{ext_label} (*{suffix})", "All files (*.*)")
            initial = suggested_name or target.name
            dest = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=initial,
                file_types=file_types,
            )
            if not dest:
                return {"ok": False, "error": "cancelled"}
            dest_path = dest if isinstance(dest, str) else dest[0]
            shutil.copy2(target, dest_path)
            return {"ok": True, "path": dest_path}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def _port_busy(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def launch() -> None:
    ensure_dirs()
    db.init()

    global PORT  # may shift if default is busy
    if _port_busy(HOST, PORT):
        # Try the next few ports — keeps the bookmark stable most of the time
        # but doesn't fail silently when 8765 is taken by something else.
        chosen = None
        for candidate in range(PORT + 1, PORT + 20):
            if not _port_busy(HOST, candidate):
                chosen = candidate
                break
        if chosen is None:
            print(
                f"Порт {PORT} занят, и соседние тоже. Закрой процесс, держащий порт, "
                f"или задай переменную окружения PORT=<свободный_порт> и запусти снова.",
                flush=True,
            )
            sys.exit(2)
        print(f"[launch] port {PORT} busy, switching to {chosen}", flush=True)
        PORT = chosen

    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()

    url = f"http://{HOST}:{PORT}"
    if not _wait_until_up(f"{url}/api/health"):
        print(f"Сервер не поднялся за 15 секунд. Открой вручную: {url}", flush=True)
        sys.exit(3)

    try:
        import webview  # type: ignore

        api = DesktopApi()
        webview.create_window(
            "Transcript Notes (tryll)",
            url,
            width=1180,
            height=820,
            min_size=(900, 640),
            background_color="#0b0d12",
            js_api=api,
        )
        webview.start()
    except Exception as e:
        print(f"pywebview недоступен ({e}); открываю в браузере: {url}")
        import webbrowser
        webbrowser.open(url)
        # Keep process alive so server stays running.
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    launch()
