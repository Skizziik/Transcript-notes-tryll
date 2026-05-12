#!/usr/bin/env python3
"""Convert markdown notes to a clean .docx via pandoc.

Usage:
    to_docx.py <input.md> [-o output.docx]

Requires:
    pandoc (installed via `brew install pandoc`).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def convert(md_path: Path, docx_path: Path) -> None:
    if shutil.which("pandoc") is None:
        print("error: pandoc not found. Install with: brew install pandoc", file=sys.stderr)
        sys.exit(2)

    docx_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pandoc",
        str(md_path),
        "-o", str(docx_path),
        "--from", "gfm+smart",
        "--to", "docx",
        "--standalone",
    ]
    reference = md_path.parent.parent / "reference.docx"
    if reference.exists():
        cmd += ["--reference-doc", str(reference)]

    subprocess.run(cmd, check=True)
    print(str(docx_path))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path, help="input markdown file")
    p.add_argument("-o", "--output", type=Path, default=None, help="output .docx path")
    args = p.parse_args()

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    out = args.output or args.input.with_suffix(".docx")
    convert(args.input, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
