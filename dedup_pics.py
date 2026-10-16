#!/usr/bin/env python3
"""删除 pics 文件夹里的重复截图。

用法:
    python3 dedup_pics.py <pics_folder>

规则:
    按文件名排序逐张比较；若某张与上一张「保留图」的平均像素差 < 8.0，
    判定为同一页的重复截图并删除。

说明:
    本脚本是重写版（原文件被 .gitignore 忽略后丢失）。
    如需保留，请从 .gitignore 中移除 `dedup_pics.py` 并提交。
"""
import glob
import os
import sys

import numpy as np
from PIL import Image

THRESHOLD = 8.0
SIZE = (256, 256)  # 先缩放再比，抗轻微滚动/抖动
EXTS = ("png", "jpg", "jpeg", "webp", "PNG", "JPG", "JPEG")


def load_gray(path):
    with Image.open(path) as im:
        im = im.convert("L").resize(SIZE)
        return np.asarray(im, dtype=np.float32)


def main():
    if len(sys.argv) < 2:
        print("usage: python3 dedup_pics.py <pics_folder>")
        return 1

    folder = sys.argv[1].rstrip("/")
    if not os.path.isdir(folder):
        print(f"not a folder: {folder}")
        return 1

    files = sorted({f for e in EXTS for f in glob.glob(os.path.join(folder, f"*.{e}"))})
    if not files:
        print(f"no images in {folder}")
        return 0

    prev = load_gray(files[0])
    kept = 1
    removed = []
    for path in files[1:]:
        cur = load_gray(path)
        diff = float(np.mean(np.abs(cur - prev)))
        if diff < THRESHOLD:
            os.remove(path)
            removed.append((os.path.basename(path), diff))
        else:
            kept += 1
            prev = cur

    print(f"kept {kept} / {len(files)} images in {folder}")
    for name, diff in removed:
        print(f"  removed {name} (diff {diff:.2f} < {THRESHOLD})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
