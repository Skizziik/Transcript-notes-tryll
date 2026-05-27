"""Tiny .exe launcher.

Locates the project's .venv next to itself and starts the app in a windowed
Python (pythonw.exe), so the user double-clicks the exe and the pywebview
window opens — no console flash, no .bat files.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def show_error(msg: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, msg, "Transcript Notes", 0x10)
    except Exception:
        sys.stderr.write(msg + "\n")


def main() -> int:
    base = base_dir()
    venv_pyw = base / ".venv" / "Scripts" / "pythonw.exe"
    venv_py = base / ".venv" / "Scripts" / "python.exe"

    python_exe = venv_pyw if venv_pyw.exists() else venv_py
    if not python_exe.exists():
        show_error(
            "Виртуальное окружение .venv не найдено.\n\n"
            f"Ожидалось здесь:\n{venv_py}\n\n"
            "Запусти один раз setup.bat в корне проекта."
        )
        return 1

    app_dir = base / "app"
    if not app_dir.exists():
        show_error(
            "Не найдена папка app\\ рядом с exe.\n\n"
            f"Проверь расположение: {base}"
        )
        return 1

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    creationflags = 0x08000000  # CREATE_NO_WINDOW

    log_dir = base / "storage"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "launcher.log"

    try:
        with open(log_path, "wb") as log_f:
            proc = subprocess.Popen(
                [str(python_exe), "-m", "app.main"],
                cwd=str(base),
                env=env,
                creationflags=creationflags,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
            ret = proc.wait()
        if ret != 0:
            try:
                tail = log_path.read_bytes()[-2000:].decode("utf-8", errors="replace")
            except Exception:
                tail = ""
            show_error(
                f"Приложение завершилось с кодом {ret}.\n\n"
                f"Лог: {log_path}\n\n"
                f"Хвост лога:\n{tail or '(пусто)'}"
            )
        return ret
    except Exception as e:
        show_error(f"Не удалось запустить приложение:\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
