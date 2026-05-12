#!/usr/bin/env python3
"""Transcribe audio to text using MLX Whisper (Apple Silicon).

Usage:
    transcribe.py <audio_file> [--model MODEL] [--language LANG] [--out OUT_DIR]

Outputs:
    <out_dir>/<basename>.txt   — plain transcript
    <out_dir>/<basename>.json  — segments with timestamps
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import mlx_whisper

DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"


def transcribe(audio_path: Path, model: str, language: str | None, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[transcribe] model={model} file={audio_path.name}", file=sys.stderr)
    t0 = time.time()
    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=language,
        word_timestamps=False,
        verbose=False,
    )
    dt = time.time() - t0
    print(f"[transcribe] done in {dt:.1f}s, detected lang={result.get('language')}", file=sys.stderr)

    base = audio_path.stem
    txt_path = out_dir / f"{base}.txt"
    json_path = out_dir / f"{base}.json"

    txt_path.write_text(result["text"].strip() + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "language": result.get("language"),
                "duration_sec": result.get("segments", [{}])[-1].get("end") if result.get("segments") else None,
                "segments": [
                    {"start": s["start"], "end": s["end"], "text": s["text"]}
                    for s in result.get("segments", [])
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"txt": str(txt_path), "json": str(json_path), "language": result.get("language")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("audio", type=Path, help="path to audio file")
    p.add_argument("--model", default=DEFAULT_MODEL, help="MLX Whisper model HF repo")
    p.add_argument("--language", default=None, help="force language (e.g. ru, en); auto-detect if omitted")
    p.add_argument("--out", type=Path, default=Path("output"), help="output directory")
    args = p.parse_args()

    if not args.audio.exists():
        print(f"error: audio file not found: {args.audio}", file=sys.stderr)
        return 1

    info = transcribe(args.audio, args.model, args.language, args.out)
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
