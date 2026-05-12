# Transcript Notes (tryll)

Локальная транскрипция аудио на Apple Silicon + детальные структурированные заметки на русском в `.docx`. Без облака для самой транскрипции — звук с машины не уходит.

- **Транскрипция:** [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (`large-v3`), работает через Metal на M-чипах.
- **Заметки:** Claude Code прямо из чата, через слэш-команду `/notes`.
- **Конвертация в .docx:** pandoc.

Любой язык на входе → русские заметки на выходе (английские термины, имена, инструменты сохраняются как есть).

## Зачем

Сделать так, чтобы из встречи/лекции/звонка получались **подробные**, а не пересказ-в-три-строки, заметки — с цифрами, именами, цитатами, action items и открытыми вопросами. Голосовой ввод никуда не уходит, кроме твоей машины. Текст транскрипта Claude видит — но это уже текст без аудио.

## Workflow

```
input/audio.m4a  →  MLX Whisper  →  output/audio.txt
                                     ↓
                                  Claude reads
                                     ↓
                       output/audio.notes.md  →  pandoc  →  output/audio.notes.docx
```

## Структура репо

```
scripts/
  transcribe.py       # MLX Whisper → output/<name>.txt + .json (с таймкодами)
  to_docx.py          # Markdown → .docx через pandoc
.claude/
  commands/
    notes.md          # /notes — слэш-команда для Claude Code
input/                # сюда кидаешь аудио (gitignored)
output/               # результаты — txt, md, docx (gitignored)
```

## Установка (один раз)

Требуется macOS на Apple Silicon (M1+), Python 3.10+, Homebrew.

```bash
# системные зависимости
brew install ffmpeg pandoc

# python окружение
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

При первом запуске модель `whisper-large-v3-mlx` (~3 GB) скачается из HuggingFace в `~/.cache/huggingface/` и закэшируется. Дальше всё быстро.

## Использование

### Через Claude Code (рекомендуется)

1. Кинь аудиофайл в папку `input/` (форматы: m4a, mp3, wav, mp4, mov, opus, aac, flac, aiff, ogg, webm).
2. Открой Claude Code в корне репо.
3. Набери `/notes` — без аргументов.
4. Жди — на выходе `output/<имя>.notes.docx`.

Дополнительно:
- `/notes --lang ru` — принудительно указать язык (быстрее, чем автоопределение).
- `/notes ~/Downloads/file.m4a` — обработать файл напрямую, минуя `input/`.
- Если в `input/` несколько файлов, команда попросит уточнить какой.

### Вручную (без Claude)

```bash
# 1. транскрипция
.venv/bin/python scripts/transcribe.py input/audio.m4a --out output

# 2. заметки — пишешь сам или через любой LLM
# результат сохрани в output/audio.notes.md

# 3. конвертация в docx
.venv/bin/python scripts/to_docx.py output/audio.notes.md
```

## Модели

По умолчанию — `mlx-community/whisper-large-v3-mlx` (лучшее качество для русского).

Если нужно быстрее (например, на коротких записях с чистой речью):

```bash
.venv/bin/python scripts/transcribe.py input/audio.m4a \
  --model mlx-community/whisper-large-v3-turbo
```

## Что именно делает Claude с транскриптом

См. [`.claude/commands/notes.md`](.claude/commands/notes.md) — там полные инструкции. Кратко:

- Иерархия `##` / `###` по темам, в начале короткое «О чём».
- Сохраняет цифры, имена, команды, примеры, цитаты — не пересказывает.
- Определения терминов оформляет явно: **GraphQL** — query language for APIs…
- Отдельные разделы: `Решения и Action Items`, `Открытые вопросы`.
- Сильные цитаты — блок `>` с указанием говорящего, если ясно.
- Не выдумывает: плохо расслышанное помечает `[неразборчиво]` или `[?]`.
- Не добавляет «Выводы»/«Заключение», если их не было в записи.

## Стилизация .docx

Хочешь свой шрифт/отступы — положи `reference.docx` в корень проекта (можно сгенерить и отредактировать в Word: `pandoc -o reference.docx --print-default-data-file reference.docx`). Скрипт подхватит автоматически.

## Поддержка

Apple Silicon (M1/M2/M3/M4). На Intel-Mac или Linux MLX не работает — нужна замена на `faster-whisper` или `whisper.cpp`.
