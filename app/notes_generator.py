from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import CLAUDE_BIN, CLAUDE_MODEL

NotesProgressCb = Callable[[str, str | None], None]

NOTES_PROMPT = """Ты — ассистент, который превращает транскрипты в детальные структурированные заметки на русском.

## Имя файла

В **самой первой строке** ответа верни HTML-комментарий с предложенным именем файла на английском, snake_case, отражающим суть встречи:

```
<!-- filename: meeting_impressions_q1 -->
```

Требования к slug: только латиница, цифры и подчёркивания, до 60 символов, без расширения. Эта строка нужна нам для имени файла на диске; она будет удалена из текста заметок перед сохранением. После этой строки сразу пиши `## О чём` и далее заметки.

## Правила оформления заметок

- **Основной язык — русский.** Английские термины, имена, инструменты, продукты — оставляй как есть (`GitHub`, `GraphQL`, не «ГитХаб», не «ГраФКуЭл»).
- **Структура** — иерархия `##` / `###` по темам. В начале короткий блок «## О чём» (3–5 пунктов).
- **Детализация, не саммари.** Сохраняй цифры, имена, команды, примеры, цитаты. Не пересказывай — фиксируй.
- **Определения терминов** оформляй явно, например: **GraphQL** — query language for APIs…
- **Решения и Action Items** — отдельный раздел, по пунктам, с ответственными и сроками если звучали.
- **Открытые вопросы** — отдельный раздел, если что-то осталось неясным/отложенным.
- **Сильные цитаты** — `>` блок, с указанием говорящего если можно определить.
- **Код / команды** — в ```` ``` ```` блоках.
- **Таймкоды `[MM:SS]`** — если запись длиннее ~10 минут, ставь рядом с `###` заголовками подтем, ключевыми action items и цитатами. Бери `start` ближайшего сегмента из переданного JSON. Для записей длиннее часа — `[H:MM:SS]`. Не сыпь таймкоды на каждом пункте — только там, где они помогают навигации. Если запись короче 10 минут — таймкоды не нужны.
- **Не выдумывай.** Плохо расслышанное — `[неразборчиво]` или `[?]`. Если не уверен в таймкоде — не ставь.
- **Не добавляй** «Выводы» / «Заключение», если их не было в исходной записи.

Длина пропорциональна записи (получасовая встреча → 1–2 страницы плотных заметок).

## Что от тебя нужно

Верни **только** содержимое заметок в формате Markdown. Без вступлений, без «Конечно, вот ваши заметки:», без блока ```markdown``` вокруг. Сразу с `## О чём`.

## Транскрипт

Язык записи: {language}
Длительность: {duration}

### Сегменты с таймкодами (для проставления `[MM:SS]`)

```json
{segments_json}
```

### Полный текст

{transcript}
"""


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return "неизвестно"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _compact_segments(segments: list[dict]) -> list[dict]:
    # Round to 1 decimal to save tokens; keep all segments.
    out = []
    for s in segments:
        out.append({
            "start": round(float(s["start"]), 1),
            "end": round(float(s["end"]), 1),
            "text": s["text"].strip(),
        })
    return out


def build_prompt(transcript: str, language: str | None, duration_sec: float | None, segments: list[dict]) -> str:
    return NOTES_PROMPT.format(
        language=language or "не определён",
        duration=_format_duration(duration_sec),
        segments_json=json.dumps(_compact_segments(segments), ensure_ascii=False),
        transcript=transcript.strip(),
    )


def check_claude_cli() -> tuple[bool, str]:
    bin_path = shutil.which(CLAUDE_BIN)
    if not bin_path:
        return False, f"Не найден исполняемый файл '{CLAUDE_BIN}' в PATH. Установи Claude Code CLI и залогинься."
    return True, bin_path


def generate_notes(
    transcript: str,
    language: str | None,
    duration_sec: float | None,
    segments: list[dict],
    out_path: Path,
    progress_cb: NotesProgressCb | None = None,
    model: str = CLAUDE_MODEL,
) -> tuple[str, str | None]:
    ok, msg = check_claude_cli()
    if not ok:
        raise RuntimeError(msg)
    # On Windows the npm-installed claude is actually claude.cmd. subprocess.Popen
    # without shell=True won't pick up PATHEXT — resolve the full path explicitly.
    claude_path = msg

    prompt = build_prompt(transcript, language, duration_sec, segments)
    if progress_cb:
        progress_cb("", "Запуск Claude CLI…")

    cmd = [
        claude_path,
        "-p",
        "--model", model,
        "--tools", "",
        "--no-session-persistence",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    # Use shell=True on Windows so .cmd/.bat shims (like npm-installed claude.cmd)
    # are interpreted by the command processor instead of failing CreateProcess.
    use_shell = sys.platform == "win32" and claude_path.lower().endswith((".cmd", ".bat"))

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        shell=use_shell,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    collected = []
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        delta = _extract_text_delta(event)
        if delta:
            collected.append(delta)
            if progress_cb:
                progress_cb(delta, None)
        final_text = _extract_final_result(event)
        if final_text and not collected:
            collected.append(final_text)
            if progress_cb:
                progress_cb(final_text, None)

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"Claude CLI завершился с кодом {proc.returncode}: {stderr.strip()[:1000]}")

    notes_md = "".join(collected).strip()
    if not notes_md:
        raise RuntimeError("Claude CLI вернул пустой ответ.")

    # Strip any accidental fenced wrapper.
    notes_md = _strip_outer_fence(notes_md)

    # Pull out the filename slug Claude was asked to emit on the first line.
    slug, notes_md = _extract_filename_slug(notes_md)

    out_path.write_text(notes_md + "\n", encoding="utf-8")
    if progress_cb:
        progress_cb("", "Заметки готовы")
    return notes_md, slug


_FILENAME_RE = re.compile(r"^\s*<!--\s*filename\s*:\s*([A-Za-z0-9_-]{1,80})\s*-->\s*\r?\n?")


def _extract_filename_slug(text: str) -> tuple[str | None, str]:
    m = _FILENAME_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():].lstrip()


def _extract_text_delta(event: dict) -> str | None:
    """Extract a text delta from a stream-json event regardless of shape variant."""
    if not isinstance(event, dict):
        return None
    ev_type = event.get("type")

    # Partial message streaming: type == "stream_event" wraps SSE-like deltas
    if ev_type == "stream_event":
        inner = event.get("event") or {}
        if inner.get("type") == "content_block_delta":
            delta = inner.get("delta") or {}
            if delta.get("type") in ("text_delta", "text"):
                return delta.get("text")
        return None

    # Some versions emit assistant_message events with full assistant payload deltas.
    if ev_type == "assistant":
        msg = event.get("message") or {}
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                # This is usually a full message, not a delta. Return only if no
                # prior deltas were emitted — caller handles that fallback.
                return None

    return None


def _extract_final_result(event: dict) -> str | None:
    """Some stream-json shapes end with a 'result' event containing the full text."""
    if event.get("type") == "result":
        result = event.get("result")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("content") or result.get("text")
    if event.get("type") == "assistant":
        msg = event.get("message") or {}
        parts: list[str] = []
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        if parts:
            return "".join(parts)
    return None


def _strip_outer_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1 and t.rstrip().endswith("```"):
            return t[first_nl + 1 : t.rstrip().rfind("```")].strip()
    return text
