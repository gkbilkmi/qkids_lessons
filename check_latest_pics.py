#!/usr/bin/env python3
"""找出「最新图片」所在的 pics 文件夹。

用法:
    python3 check_latest_pics.py

输出:
    第一行 = 最新图片所在文件夹（相对路径），供备课自动选择；
    其余以 `#` 开头的行是辅助信息。

说明:
    本脚本是重写版（原文件被 .gitignore 忽略后丢失）。
    如需保留，请从 .gitignore 中移除 `check_latest_pics.py` 并提交。
"""
import glob
import os

EXTS = ("png", "jpg", "jpeg", "webp", "PNG", "JPG", "JPEG")


def images_in(folder):
    return sorted({f for e in EXTS for f in glob.glob(os.path.join(folder, f"*.{e}"))})


def main():
    dirs = sorted(d for d in glob.glob("pics*") if os.path.isdir(d))
    if not dirs:
        print("no pics folder found")
        return 1

    best, best_mtime, best_img = None, None, None
    summary = []
    for d in dirs:
        files = images_in(d)
        if not files:
            summary.append(f"{d}(0)")
            continue
        mtime = max(os.path.getmtime(f) for f in files)
        summary.append(f"{d}({len(files)})")
        if best_mtime is None or mtime > best_mtime:
            best, best_mtime, best_img = d, mtime, max(files, key=os.path.getmtime)

    print(best if best else "no images in any pics folder")
    if best:
        import datetime

        ts = datetime.datetime.fromtimestamp(best_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"# newest image: {best_img} ({ts})")
    print(f"# candidates: {', '.join(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
