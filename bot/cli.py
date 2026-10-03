#!/usr/bin/env python3
"""הרצה ישירה משורת הפקודה, בלי טלגרם — נוח לבדיקות.

    python3 cli.py video.mp4            # מפיק SRT
    python3 cli.py video.mp4 --burn     # גם צורב
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import uuid
from pathlib import Path

from zovexsub import config, pipeline


async def main() -> int:
    parser = argparse.ArgumentParser(description="כתוביות עברית מסרטון")
    parser.add_argument("source", type=Path)
    parser.add_argument("--burn", action="store_true", help="לצרוב את הכתוביות על הוידאו")
    parser.add_argument("--out", type=Path, default=Path.cwd())
    args = parser.parse_args()

    problems = config.validate()
    problems = [p for p in problems if "TG_" not in p]
    if problems:
        print("שגיאות הגדרה ב-.env:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    if not args.source.exists():
        print(f"לא נמצא: {args.source}", file=sys.stderr)
        return 2

    work = config.WORK_DIR / uuid.uuid4().hex[:10]

    async def progress(text: str) -> None:
        print(text, flush=True)

    try:
        result = await pipeline.run(args.source, work, burn=args.burn, progress=progress)
        args.out.mkdir(parents=True, exist_ok=True)
        for produced in (result.srt_path, result.burned_path):
            if produced:
                shutil.copy2(produced, args.out / produced.name)
                print(f"נשמר: {args.out / produced.name}")
        if result.burn_skipped:
            print(f"הערה: {result.burn_skipped}")
        print(f"{result.cues} כתוביות · שפת מקור {result.language} · "
              f"{result.elapsed / 60:.1f} דקות עיבוד")
        return 0
    finally:
        pipeline.cleanup(work)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
