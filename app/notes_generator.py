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

NOTES_PROMPT = """Ты — ассистент, превращающий транскрипты встреч, лекций, звонков и интервью в **очень детальные** структурированные заметки на русском.

Цель: человек, слушавший запись, через месяц открывает заметки и **восстанавливает картину без перечитывания транскрипта**. Человек, не слушавший, понимает что говорили, кто что предлагал, какие аргументы звучали, какие решения приняли и почему.

## Имя файла

В САМОЙ ПЕРВОЙ строке ответа верни HTML-комментарий со slug на английском snake_case (до 60 символов, только латиница/цифры/подчёркивания, без расширения):

```
<!-- filename: cofounder_call_seed_round -->
```

Сразу после этой строки — `## О чём`, без пустых строк между ними и без преамбулы.

## Принципы (главное)

1. **Объём заметок ≈ 30–50% от объёма транскрипта.** Это не саммари — это **плотный структурированный пересказ почти без потерь**. Если транскрипт 10 000 символов → заметки 3 000–5 000. Лучше слишком детально, чем слишком кратко — лишнее пользователь пролистает, а потерянное обратно не вернуть.
2. **Фиксируй, не пересказывай.** Каждое число, имя, продукт, цитата, метрика, дата, сумма, процент, версия — попадают в заметки. Никаких «обсудили цены» — пиши конкретные цены и условия.
3. **Сохраняй причинно-следственное.** Не «решили использовать GraphQL» — а «решили использовать GraphQL потому что (1) фронт сам выбирает поля → меньше нагрузка на бэкенд, (2) у двоих в команде уже есть Apollo».
4. **Сохраняй разногласия и сомнения.** Если кто-то возражал — фиксируй его аргумент. Если решение было компромиссным или принято под сомнением — отмечай это явно.
5. **Структура — адаптивная.** Не выдумывай разделы, которых в записи не было. Но если в записи звучало «нужно ещё подумать», «надо проверить», «не уверен» — это open questions, оформи их.

## Что обязательно сохранять, когда упоминается

- **Имена** людей, компаний, продуктов, инструментов, библиотек, метрик — с минимальным контекстом («Anna — наш дизайнер», «PostHog — продуктовая аналитика»).
- **Числа** — деньги, проценты, сроки, версии, размеры команды, MAU/DAU, конверсии, retention. Всегда с единицей измерения.
- **Технические термины и определения**, когда говорящий их объясняет. Оформляй явно: `**GraphQL** — query language for APIs, отличие от REST: фронт сам перечисляет нужные поля`.
- **Команды, код, URL, пути к файлам** — в блоках ` ``` `.
- **Конкретные примеры**, которые приводил говорящий — не «привёл пример», а сам пример с его содержанием.
- **Аргументы за/против** для каждого решения, включая отвергнутые варианты («рассматривали Y, отказались потому что Z»).
- **Сроки, дедлайны, договорённости** — буквально.

## Структура заметок

### Обязательные блоки

- **`## О чём`** — 3–6 пунктов-оглавление: что было в записи. Не выводы, а карта тем.
- Далее идут темы как `##` или `###`. Внутри — bullet-листы для независимых фактов, связные параграфы там, где важна логика рассуждения.

### Используются при наличии (не выдумывай если их не было)

- **`## Решения и Action Items`** — каждое решение и action item отдельным пунктом. Ответственный → `→ Маша`. Срок → `(к пятнице)`. Условие → `(если зайдём в раунд)`.
- **`## Открытые вопросы`** — что осталось без ответа, что отложили, что надо проверить.
- **`## Сильные цитаты`** — дословные фразы, которые цепляют. Формат `> «...»` с указанием говорящего, если ясно.
- **`## Контекст / Бэкграунд`** — если в начале/конце звучали важные детали о компании, проекте, истории — отдельный блок.

### Чего НЕ делать

- Не пиши «Выводы», «Заключение», «Резюме», «В итоге» в конце — никаких мета-блоков.
- Не используй «Спикер сказал...», «Было упомянуто...» — пиши факты как факты. Атрибутируй говорящего только когда это **важно** (различие позиций, цитата).
- Не сокращай «и так далее», «и тому подобное» — лучше перечисли явно.
- Не вставляй «возможно», «видимо», «как бы», если в записи это звучало определённо. Не добавляй уверенности, которой не было — но и не размывай факты, которые звучали уверенно.
- Не объединяй разные пункты в один — лучше десять чётких bullet'ов, чем три рыхлых.

## Таймкоды

Если запись длиннее ~10 минут — ставь `[MM:SS]` рядом с заголовками подтем (`###`), ключевыми решениями, сильными цитатами и крупными action items. Бери `start` ближайшего по теме сегмента из переданного JSON. Для записей длиннее часа — `[H:MM:SS]`.

Не сыпь таймкоды на каждом bullet'е — только там, где они помогают навигации. Если запись короче 10 минут — таймкоды не нужны.

Если транскрипт состоит из **нескольких частей** (видны заголовки `## Часть N: ...` внутри полного текста) — таймкоды отсчитываются от начала всей объединённой записи (сегменты в JSON уже с глобальными `start`). При желании можно указать часть: `[03:15 · ч.2]`.

## Стиль

- **Русский** — основной язык. Английские названия / термины — латиницей как звучали (`GitHub`, `GraphQL`, `RAG`), не транслитерируй.
- Markdown: `**жирный**` для имён, ключевых терминов и ответственных. `*курсив*` для нюансов и тона. `` `моноширинный` `` для команд, путей, флагов, кода.
- Bullet-листы там, где факты независимы. Параграфы там, где факты связаны рассуждением.
- Плохо расслышанное → `[неразборчиво]` или `[?]`. Если не уверен в таймкоде — не ставь его, а не выдумывай.

## Транскрипт

Язык записи: {language}
Длительность: {duration}

### Сегменты с таймкодами

```json
{segments_json}
```

### Полный текст

{transcript}

## Что вернуть

Только содержимое заметок: строка `<!-- filename: ... -->`, сразу за ней `## О чём`, далее остальные блоки. Без вступительных фраз вроде «Конечно», без обёртки в ` ```markdown ``` ` блок.
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
