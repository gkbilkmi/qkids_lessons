#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qkids_capture.py v9 — 久趣绘本备课截图（替代影刀 Qkids 流程）

v2 关键修正（来自 v1 自检实测）：
  - 截图按「窗口 ID」截（screencapture -l），不再截屏幕区域：
    久趣被别的窗口盖住时也不会截错；没屏幕录制权限时只会拍到壁纸，脚本会识别并报错。
  - 窗口位置/ID 用系统窗口列表（Swift 调用 CGWindowList）读取，不依赖辅助功能权限。
  - 点击权限（CGPreflightPostEventAccess）为 False 时直接停，并打印
    到底是哪个终端 App 需要去系统设置里授权，不盲跑。
v3：截完后自动点右上角退出教室；另有 --exit-only 单步测试模式。
v4：久趣在任何地方都常吞第一次点击 — Story 进入、退出教室改为
  「点击后验证，没生效就原位重点」，最多 3 次（翻页/关弹窗本来就有验证）。
v5：备课成功后自动清理输出文件夹 — 只保留 page 页图，_tmp、
  capture.log、after_exit.png 全部删掉（Liang 定）；中途失败的运行
  不清理，日志和调试图留着排查。
v6：页码 OCR 加图像预处理（放大保比例+灰度后依次试原图/自动对比/
  反色/二值化/二值反色，tesseract 限数字与斜杠）— 暗色绘本页上
  原图对比度太低读不出页码（2026-10-25 实测：翻页后读空导致连环
  重点、跳页误判）；Next 验证每次点击后先重读两次再决定是否重点。
v7：回第 1 页加 Next 探活（Liang 定）：读不到页码时点 Next 探读
  总页码；Reset/Prev 连点 3 次不动时点 Next 分辨「点击没落到久趣
  上」（立刻停并说明）与「弹窗挡住往回翻」（再关一次弹窗继续）；
  Word Book 主关闭点位关不掉时自动试备用点位 (764,527)。
v8（正式版完善，2026-10-25 Liang 实测流程跑通后收的尾）：
  - 等教室：脚本启动后先等 Preview Mode 出现（默认 75 秒）— 流程是
    「先启动脚本，再打开久趣进教室」，脚本等得起；若停在课程详情页
    （读到 Overview），脚本自己点「进入教室」。
  - 弹窗关闭改候选点位：不同绘本弹窗卡片位置偏移约 30px，单一点位
    会关不掉（教学提示 × 实测在 928‰、不在 906‰）— 每种弹窗依次试
    候选点，画面差验证关掉才算数。
  - 防挂死：所有子进程超时改为「返回失败」而不是抛异常中断；另加
    全局时限（默认 12 分钟，SIGALRM）— 到点必然停并写明原因，
    不再出现日志停住几分钟没动静的静默卡死。
  - 快速失败说明：到 Story 阶段还读不到页码时，按实际情况分三种
    原因写日志（没等到教室 / 在教室但点击全无反应 / 弹窗关了但进不去）。
v9（2026-10-28 修「点进入教室点到学生头像」bug）：
  - 病根：旧版在详情页只点一次「进入教室」就用 entered 标志永不重点；
    久趣不在最前时第一下点击只激活窗口、被吞，30 秒超时后脚本还盲目
    继续到关弹窗/Story 阶段 — 那些是教室内的点位，在详情页上正好
    落在别处：关教学提示 (906,588) 正中学生头像、Story (65,954)
    正中左下角「个人中心」，实测把页面点进了个人资料页。
  - 改法：进教室改为验证重试 — 每次点完等加载复检，还在详情页
    （读到 Overview）就重点，最多 4 次；只有读到 Preview Mode
    才算进教室。等不到就立刻停并存 debug 图，绝不在详情页继续
    点教室点位。等教室时限同时由实际的 30 秒对齐到文档写的 75 秒；
    进入教室按钮中心按 2026-10-28 详情页截图复测改为 (898,902)。

前提：久趣老师端已打开；脚本启动后 75 秒内点进某节课的教室即可
（停在详情页也行，脚本会自己点进入教室）。运行期间不要碰鼠标键盘。
流程：激活久趣 -> 固定窗口 -> 等教室 -> 关教学提示/Word Book（候选点位，每次点击后校验画面变化）
     -> 点 Story 分节 -> OCR 读总页数 -> 回第 1 页 -> 逐页截图，每翻一页都 OCR 验证页码 +1
     -> 退出教室。
输出：/Users/mac/workspace/kiki_um/qkids/books/<书名>/page-01-of-NN.png ...（成功后文件夹里只留页图）

用法（在 VS Code 集成终端或系统「终端」里运行都行，权限跟宿主 App 走）：
  cd /Users/mac/workspace/kiki_um/qkids
  /opt/anaconda3/bin/python3 qkids_capture.py --probe
  /opt/anaconda3/bin/python3 qkids_capture.py --book "Peck, Peck, Peck"
  /opt/anaconda3/bin/python3 qkids_capture.py --exit-only
"""
import argparse
import ctypes
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/mac/workspace/kiki_um/qkids")
OUT_ROOT = BASE / "books"
WIN_W, WIN_H = 1200, 672
DEFAULT_RECT = (240, 93, WIN_W, WIN_H)

# 窗口内相对坐标（千分比，实测校准）
TEACHING_CLOSE = (906, 588)
WORDBOOK_CLOSE = (738, 533)
# 弹窗关闭候选点位（依次试，画面差验证）：弹窗卡片位置随绘本偏移约
# 30px，单一点位会关不掉 — 2026-10-25 实测教学提示 × 在 928‰、
# Word Book × 在 762‰ 附近。
TEACHING_CLOSE_CANDS = [(906, 588), (928, 588)]
WORDBOOK_CLOSE_CANDS = [(738, 533), (764, 527)]
ENTER_BTN = (898, 902)
STORY_DOT = (65, 954)
RESET_BTN = (59, 324)
NEXT_BTN = (37, 442)
PREV_BTN = (36, 382)
EXIT_BTN = (965, 86)
PAGE_REGION = (2, 290, 130, 365)          # 千分比 x0,y0,x1,y1
TEACHING_REGION = (730, 500, 940, 995)
WORDBOOK_REGION = (640, 480, 900, 995)

LOG_PATH = None


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def run(cmd, timeout=30):
    """跑子进程。超时/起不来都返回一个失败结果而不是抛异常 — 让调用方
    按『这一步没成』处理，脚本永远不会卡死在一个外部命令上。"""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -9, "", f"timeout {timeout}s")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, -1, "", str(e))


class _Deadline(Exception):
    """全局时限到点（SIGALRM）— 无论脚本卡在哪一步都必然停下来。"""


def _on_alarm(signum, frame):
    raise _Deadline()


# ---------- 鼠标 ----------
class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


try:
    _cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    _cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    _cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    _cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    _cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    _cf.CFRelease.argtypes = [ctypes.c_void_p]
    _CG_OK = True
except Exception as e:
    _CG_OK = False
    _CG_ERR = str(e)


def _post(t, x, y, button=0):
    ev = _cg.CGEventCreateMouseEvent(None, t, CGPoint(float(x), float(y)), button)
    if ev:
        _cg.CGEventPost(0, ev)
        _cf.CFRelease(ev)


def click_abs(x, y):
    _post(5, x, y)
    time.sleep(0.08)
    _post(1, x, y)
    time.sleep(0.08)
    _post(2, x, y)


def preflight():
    post_ok = cap_ok = None
    try:
        if hasattr(_cg, "CGPreflightPostEventAccess"):
            _cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
            post_ok = bool(_cg.CGPreflightPostEventAccess())
        if hasattr(_cg, "CGPreflightScreenCaptureAccess"):
            _cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
            cap_ok = bool(_cg.CGPreflightScreenCaptureAccess())
    except Exception:
        pass
    return post_ok, cap_ok


def host_app_name():
    """向上找父进程链里第一个 .app，告诉用户到底该给谁授权。"""
    pid = os.getppid()
    for _ in range(8):
        try:
            r = run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], timeout=5)
            parts = (r.stdout or "").strip().split(None, 1)
            if len(parts) < 2:
                break
            ppid, comm = int(parts[0]), parts[1]
            m = re.search(r"([^/]+)\.app/", comm)
            if m:
                return m.group(1) + ".app"
            if ppid <= 1:
                break
            pid = ppid
        except Exception:
            break
    return "当前终端 App"


# ---------- 窗口信息（Swift / CGWindowList，不需要辅助功能） ----------
_SWIFT = r'''
import CoreGraphics
import Foundation
let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
let list = (CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]]) ?? []
for w in list {
    let owner = w[kCGWindowOwnerName as String] as? String ?? ""
    let name = w[kCGWindowName as String] as? String ?? ""
    let num = w[kCGWindowNumber as String] as? Int ?? 0
    let layer = w[kCGWindowLayer as String] as? Int ?? -1
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    func d(_ k: String) -> Int { return Int(b[k] as? Double ?? 0) }
    print("\(num)\t\(layer)\t\(d("X"))\t\(d("Y"))\t\(d("Width"))\t\(d("Height"))\t\(owner)\t\(name)")
}
'''


def list_windows():
    tmp = Path("/tmp/qkids_winlist.swift")
    tmp.write_text(_SWIFT, encoding="utf-8")
    r = run(["swift", str(tmp)], timeout=60)
    wins = []
    for line in (r.stdout or "").splitlines():
        f = line.split("\t")
        if len(f) >= 7:
            try:
                wins.append(dict(id=int(f[0]), layer=int(f[1]), x=int(f[2]), y=int(f[3]),
                                 w=int(f[4]), h=int(f[5]), owner=f[6],
                                 name=f[7] if len(f) > 7 else ""))
            except ValueError:
                pass
    return wins


def find_qkids_window():
    wins = list_windows()
    cands = [w for w in wins if w["layer"] == 0 and w["w"] > 400 and w["h"] > 300
             and ("qkids" in w["owner"].lower() or "久趣" in w["owner"] or "久趣" in w["name"])]
    if not cands:
        return None
    cands.sort(key=lambda w: w["w"] * w["h"], reverse=True)
    return cands[0]


# ---------- AppleScript（激活/摆窗口，需要辅助功能） ----------
def applescript(src, timeout=15):
    r = run(["osascript", "-e", src], timeout=timeout)
    return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode


def activate_qkids():
    _, err, rc = applescript('tell application id "com.qkids.teacher" to activate', timeout=10)
    time.sleep(0.8)
    out, _, _ = applescript('tell application "System Events" to return name of first process whose frontmost is true', timeout=10)
    return rc == 0, out, err


def set_window_rect(owner, rect):
    x, y, w, h = rect
    src = (f'tell application "System Events" to tell process "{owner}"\n'
           f"set position of window 1 to {{{x}, {y}}}\n"
           f"set size of window 1 to {{{w}, {h}}}\nend tell")
    _, err, rc = applescript(src)
    return rc == 0, err


# ---------- 截图（按窗口 ID） ----------
def shot_window(path, win_id, rect):
    if win_id:
        r = run(["screencapture", "-x", "-o", "-t", "png", "-l", str(win_id), str(path)], timeout=20)
    else:
        r = run(["screencapture", "-x", "-t", "png", "-R", f"{rect[0]},{rect[1]},{rect[2]},{rect[3]}", str(path)], timeout=20)
    p = Path(path)
    return p.exists() and p.stat().st_size > 0, (r.stderr or "").strip()


def crop_rel(full_png, region, out_png):
    """从整窗截图按千分比裁剪。"""
    from PIL import Image
    with Image.open(full_png) as im:
        W, H = im.size
        box = (region[0] * W // 1000, region[1] * H // 1000,
               region[2] * W // 1000, region[3] * H // 1000)
        im.crop(box).save(out_png)
    return out_png


def mean_diff(pa, pb):
    try:
        import numpy as np
        from PIL import Image
        def load(p):
            with Image.open(p) as im:
                return np.asarray(im.convert("L").resize((256, 256)), dtype=np.float32)
        return float(np.mean(np.abs(load(pa) - load(pb))))
    except Exception:
        sa, sb = Path(pa).stat().st_size, Path(pb).stat().st_size
        return abs(sa - sb) / max(sa, sb) * 100.0


def ocr_image(path):
    big = str(path) + ".big.png"
    run(["sips", "-z", "400", "900", str(path), "--out", big], timeout=20)
    target = big if Path(big).exists() else str(path)
    try:
        r = run(["/usr/local/bin/tesseract", target, "stdout", "--psm", "6"], timeout=30)
        return (r.stdout or "")
    finally:
        try:
            os.remove(big)
        except OSError:
            pass


def ocr_page_number(crop, tmpdir, tag="page"):
    """页码小裁图 OCR（带图像预处理）。暗色绘本页上原图对比度太低，
    tesseract 经常读空，所以放大保比例+灰度后依次试多个版本：
    原图 / 自动对比 / 反色 / 二值化 / 二值反色，每个版本再试 psm 6/7，
    并限制字符集为数字和斜杠。返回 ((cur,total), 版本名, 原图原文)。"""
    from PIL import Image, ImageOps
    try:
        with Image.open(crop) as im:
            base = im.convert("L")
    except Exception:
        return None, "", ""
    big = base.resize((base.width * 3, base.height * 3), Image.LANCZOS)
    variants = [
        ("raw", big),
        ("contrast", ImageOps.autocontrast(big, cutoff=1)),
        ("invert", ImageOps.invert(big)),
        ("thresh", big.point(lambda v: 255 if v > 140 else 0)),
        ("thresh_inv", big.point(lambda v: 0 if v > 140 else 255)),
    ]
    raw_txt = ""
    for name, img in variants:
        p = Path(tmpdir) / f"{tag}_ocr_{name}.png"
        try:
            img.save(p)
        except Exception:
            continue
        for psm in ("6", "7"):
            r = run(["/usr/local/bin/tesseract", str(p), "stdout",
                     "--psm", psm, "-c", "tessedit_char_whitelist=0123456789/"],
                    timeout=30)
            txt = r.stdout or ""
            if name == "raw" and psm == "6":
                raw_txt = txt
            m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
            if m:
                return (int(m.group(1)), int(m.group(2))), name, raw_txt
    return None, "", raw_txt


def read_page(win_id, rect, tmpdir, tag="page"):
    full = Path(tmpdir) / f"{tag}_full.png"
    ok, _ = shot_window(full, win_id, rect)
    if not ok:
        return None
    crop = Path(tmpdir) / f"{tag}_crop.png"
    try:
        crop_rel(full, PAGE_REGION, crop)
    except Exception as e:
        log(f"  裁剪失败: {e}")
        return None
    pg, how, raw_txt = ocr_page_number(crop, tmpdir, tag)
    if pg:
        if how not in ("", "raw"):
            log(f"  页码靠预处理[{how}]读出: {pg[0]}/{pg[1]}")
        return pg
    log(f"  OCR 未读出页码（预处理全试过），原图原文: {raw_txt.strip()[:80]!r}")
    return None


def rel(rect, pt):
    return (rect[0] + pt[0] * rect[2] // 1000, rect[1] + pt[1] * rect[3] // 1000)


def close_one(win_id, rect, name, pt, region, tmpdir, tries=2):
    for i in range(1, tries + 1):
        bf, af = Path(tmpdir) / f"{name}_b.png", Path(tmpdir) / f"{name}_a.png"
        cf, ca = Path(tmpdir) / f"{name}_bc.png", Path(tmpdir) / f"{name}_ac.png"
        shot_window(bf, win_id, rect)
        x, y = rel(rect, pt)
        click_abs(x, y)
        time.sleep(0.8)
        shot_window(af, win_id, rect)
        try:
            crop_rel(bf, region, cf)
            crop_rel(af, region, ca)
            d = mean_diff(cf, ca)
        except Exception:
            d = mean_diff(bf, af)
        log(f"  关{name} 第{i}次: 点击({x},{y}) 画面差={d:.2f}")
        if d > 3.0:
            return True
    return False


def close_popup(win_id, rect, name, cands, region, tmpdir):
    """关一种弹窗：候选关闭点位依次试（第一个点位给 2 次机会，防吞点击；
    其余 1 次），画面差验证关掉才算数。返回是否关掉了至少一个弹窗。"""
    for i, pt in enumerate(cands):
        label = name if len(cands) == 1 else f"{name}@{pt[0]}"
        if close_one(win_id, rect, label, pt, region, tmpdir, tries=2 if i == 0 else 1):
            return True
    return False


def ocr_full(path):
    """整窗截图直接 OCR（不缩放），用来判断现在是哪种页面。"""
    try:
        r = run(["/usr/local/bin/tesseract", str(path), "stdout", "--psm", "6"], timeout=60)
        return r.stdout or ""
    except Exception:
        return ""


# 教室左上角 "Preview Mode" 白字的位置（千分比，2026-10-28 教室截图实测
# 约在 x 297–390‰、y 39–68‰；取宽一点的范围防偏移）
PREVIEW_REGION = (260, 20, 450, 90)


def ocr_preview_mode(path, tmpdir):
    """专门读教室左上角的 "Preview Mode" 白字：它压在老师摄像头画面上，
    整页 OCR 读不到（2026-10-28 实测：已进教室 60 秒，整页 OCR 始终
    读不到，脚本误判没进教室而停）。裁顶部小图后放大 3 倍，依次试
    原图/自动对比/反色/二值化/二值反色/高阈值反色 × psm 6/7，任一
    读到 preview 即算在教室。"""
    from PIL import Image, ImageOps
    crop = Path(tmpdir) / "preview_crop.png"
    try:
        crop_rel(path, PREVIEW_REGION, crop)
        with Image.open(crop) as im:
            base = im.convert("L")
    except Exception:
        return False
    big = base.resize((base.width * 3, base.height * 3), Image.LANCZOS)
    variants = [
        ("raw", big),
        ("contrast", ImageOps.autocontrast(big, cutoff=1)),
        ("invert", ImageOps.invert(big)),
        ("thresh", big.point(lambda v: 255 if v > 140 else 0)),
        ("thresh_inv", big.point(lambda v: 0 if v > 140 else 255)),
        # 白字压浅色背景专用：只有近纯白（字本身）才留黑，其余全白
        ("hi_thresh_inv", big.point(lambda v: 0 if v > 235 else 255)),
    ]
    for name, img in variants:
        p = Path(tmpdir) / f"preview_ocr_{name}.png"
        try:
            img.save(p)
        except Exception:
            continue
        for psm in ("6", "7"):
            r = run(["/usr/local/bin/tesseract", str(p), "stdout", "--psm", psm], timeout=30)
            if "preview" in (r.stdout or "").lower():
                if name != "raw" or psm != "6":
                    log(f"  Preview Mode 靠预处理[{name}/psm{psm}]读出")
                return True
    return False


def exit_classroom(win_id, rect, out, tmpdir):
    """点右上角退出教室，用 OCR 验证已回到详情页（读到 Overview）。
    久趣常吞第一次点击：没验证到就在原位置重点，最多 3 次。
    返回 True=已确认退出，False=3 次都没确认（after_exit.png 已存）。"""
    for i in range(1, 4):
        x, y = rel(rect, EXIT_BTN)
        click_abs(x, y)
        log(f"点退出教室 第{i}次: ({x},{y})")
        time.sleep(2.2)
        p = Path(out) / "after_exit.png"
        shot_window(p, win_id, rect)
        if "overview" in ocr_full(p).lower():
            log("已验证退出到详情页（读到 Overview）")
            return True
        log("  还没看到详情页，可能点击被吞，再点一次")
    log("退出未确认：3 次后仍没读到详情页")
    return False


def wait_for_classroom(win_id, rect, tmpdir, timeout=75):
    """等教室出现。Liang 定的流程是『先启动脚本，再打开久趣进教室』，
    所以脚本先等 Preview Mode；若先看到课程详情页（Overview 在屏），
    自己点「进入教室」再继续等。

    v9（2026-10-28）：进教室是验证重试，不是只点一次。久趣不在最前
    时第一下点击常只激活窗口、被吞（退出教室早已这么处理，见
    exit_classroom）；旧版 entered 标志让它永不重点，超时后调用方
    还盲目继续，关弹窗/Story 的教室点位在详情页上正中学生头像和
    「个人中心」。现在：还在详情页就重点，最多 4 次；只有确认
    Preview Mode 才返回 True；返回 False 时调用方必须立刻停。
    确认方式也不能只靠整页 OCR：「Preview Mode」白字压在摄像头
    画面上整页 OCR 读不到，改用 ocr_preview_mode 裁图预处理读；
    且每次点击后至少等 12 秒（教室加载慢）才允许凭 Overview 重点，
    防加载中的过渡帧触发多余点击。"""
    deadline = time.time() + timeout
    attempts = 0
    last_click = 0.0
    while True:
        p = Path(tmpdir) / "wait_full.png"
        ok, _ = shot_window(p, win_id, rect)
        txt = ocr_full(p).lower() if ok else ""
        if "preview mode" in txt or (ok and ocr_preview_mode(p, tmpdir)):
            log("已在教室里（读到 Preview Mode）")
            return True
        if "overview" in txt and time.time() - last_click >= 12:
            if attempts >= 4:
                log("进教室点满 4 次还停在详情页，放弃 — 不在详情页继续点教室点位")
                return False
            attempts += 1
            x, y = rel(rect, ENTER_BTN)
            click_abs(x, y)
            last_click = time.time()
            log(f"看到课程详情页，点进入教室 第{attempts}次: ({x},{y})，等教室加载…")
            time.sleep(8)
            continue
        if time.time() >= deadline:
            log(f"等教室超时（{timeout}s），一直没读到 Preview Mode")
            return False
        time.sleep(2.5)


def slugify(name):
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "book"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--exit-only", action="store_true", help="只点退出教室并存一张退出后的图，然后结束")
    ap.add_argument("--max-minutes", type=int, default=12, help="全局时限（分钟），到点必停，默认 12")
    args = ap.parse_args()

    global LOG_PATH
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = slugify(args.book) if args.book else f"book-{stamp}"
    out = OUT_ROOT / folder
    if out.exists() and not args.probe:
        out = OUT_ROOT / f"{folder}-{stamp[9:]}"
    out.mkdir(parents=True, exist_ok=True)
    tmpdir = out / "_tmp"
    tmpdir.mkdir(exist_ok=True)
    LOG_PATH = out / "capture.log"

    log(f"=== qkids_capture v9 {'probe' if args.probe else 'run'} book={args.book!r} ===")
    log(f"python={sys.executable} ({sys.version.split()[0]})")
    if not _CG_OK:
        log(f"CoreGraphics 加载失败: {_CG_ERR}")
        return 1
    post_ok, cap_ok = preflight()
    host = host_app_name()
    log(f"运行宿主: {host}")
    log(f"权限预检: 点击(辅助功能)={post_ok} 截图(屏幕录制)={cap_ok}")
    try:
        import PIL  # noqa
        log("PIL: 有")
    except Exception:
        log("PIL: 无（请用 /opt/anaconda3/bin/python3 运行）")
        return 1
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, args.max_minutes * 60)
    log(f"全局时限: {args.max_minutes} 分钟（到点必停，不会静默卡死）")

    win = None
    for _try in range(3):
        win = find_qkids_window()
        if win:
            break
        if _try < 2:
            log("暂时没找到久趣窗口，3 秒后重试…")
            time.sleep(3)
    if win:
        rect = (win["x"], win["y"], win["w"], win["h"])
        log(f"久趣窗口: id={win['id']} owner={win['owner']!r} rect={rect}")
        win_id, owner = win["id"], win["owner"]
    else:
        log("窗口列表里找不到久趣窗口（久趣没在运行、被最小化、或不在当前桌面空间都会这样）。停。")
        return 1

    probe_png = tmpdir / "probe_full.png"
    ok, err = shot_window(probe_png, win_id, rect)
    size = probe_png.stat().st_size if probe_png.exists() else 0
    log(f"按窗口截图: ok={ok} size={size} {err} -> {probe_png}")
    if not ok or size < 10000:
        log("窗口截图异常：多半是屏幕录制权限没给到宿主 App。")
        return 1
    if cap_ok is False:
        log(f"提醒：预检显示 {host} 没有屏幕录制权限，上面的截图可能只是壁纸/别的窗口，请先授权再跑。")
    if args.probe:
        pg = read_page(win_id, rect, tmpdir, "probe")
        log(f"probe 页码 OCR: {pg}（不在 Story 页读不到属正常）")
        if post_ok is False:
            log(f"probe 结论: 点击权限=False。先给「{host}」开辅助功能：系统设置 -> 隐私与安全性 -> 辅助功能 -> 把 {host} 打开（没有就点 + 添加）；改完彻底退出 {host} 再重开，重跑 probe 到点击=True 为止。")
        else:
            log("probe 结论: 权限基本齐了，可以跑正式截图。")
        return 0

    if args.exit_only:
        if post_ok is False:
            log("点击权限=False，先授权再跑。停。")
            return 3
        ok_a, front, err_a = activate_qkids()
        log(f"激活久趣: ok={ok_a} frontmost={front!r} {err_a}")
        return 0 if exit_classroom(win_id, rect, out, tmpdir) else 2

    if post_ok is False:
        log(f"点击权限=False，模拟点击会被系统丢掉。先给「{host}」开辅助功能并重启它，再重跑。停。")
        return 3

    # 1) 激活 + 固定窗口
    ok_a, front, err_a = activate_qkids()
    log(f"激活久趣: ok={ok_a} frontmost={front!r} {err_a}")
    ok_s, err_s = set_window_rect(owner, DEFAULT_RECT)
    time.sleep(0.6)
    win2 = find_qkids_window()
    if win2:
        rect = (win2["x"], win2["y"], win2["w"], win2["h"])
        win_id = win2["id"]
    log(f"固定窗口: set={ok_s} {err_s} 结果 rect={rect} id={win_id}")

    # 1.5) 等教室（脚本先于「进教室」启动是正常流程 — 见 wait_for_classroom）
    in_classroom = wait_for_classroom(win_id, rect, tmpdir)
    if not in_classroom:
        # v9：没确认进教室就立刻停。旧版超时后盲目继续关弹窗/点 Story，
        # 那些教室点位在详情页上正中学生头像 (906,588 附近) 和左下角
        # 「个人中心」(65,954)，会把页面点乱（2026-10-28 实测点进了
        # 个人资料页）。宁可停下重跑，也不许在详情页乱点。
        shot_window(out / "debug_not_in_classroom.png", win_id, rect)
        log("没确认进教室，已停在当前页面，没有继续点关弹窗/Story。把久趣提到最前后重跑。已存 debug_not_in_classroom.png，停。")
        return 2

    # 2) 关弹窗（候选点位依次试，画面差验证）
    log("关弹窗…")
    any_popup = False
    any_popup |= close_popup(win_id, rect, "教学提示", TEACHING_CLOSE_CANDS, TEACHING_REGION, tmpdir)
    any_popup |= close_popup(win_id, rect, "WordBook", WORDBOOK_CLOSE_CANDS, WORDBOOK_REGION, tmpdir)
    any_popup |= close_popup(win_id, rect, "教学提示2", TEACHING_CLOSE_CANDS, TEACHING_REGION, tmpdir)

    # 3) 进 Story（点击可能被吞：读不到页码就原位重点 Story 圆点，最多 3 轮）
    pg = None
    for rnd in range(1, 4):
        x, y = rel(rect, STORY_DOT)
        click_abs(x, y)
        log(f"点 Story 分节圆点 第{rnd}次: ({x},{y})")
        time.sleep(2.0)
        any_popup |= close_popup(win_id, rect, "教学提示3", TEACHING_CLOSE_CANDS, TEACHING_REGION, tmpdir)
        for _ in range(3):
            pg = read_page(win_id, rect, tmpdir)
            if pg:
                break
            time.sleep(1.0)
        if pg:
            break
        log("  还是读不到页码，可能 Story 点击被吞，重来")
    if not pg:
        # Liang 2026-10-25 定：读不到页码时直接点一次 Next 再读 — 翻页后
        # 页码指示器重绘，往往就能读出总页码；读到后照常回第 1 页开始截。
        x, y = rel(rect, NEXT_BTN)
        click_abs(x, y)
        log(f"读不到页码，点 Next 探读: ({x},{y})")
        time.sleep(1.5)
        for _ in range(2):
            pg = read_page(win_id, rect, tmpdir)
            if pg:
                break
            time.sleep(0.8)
        if pg:
            log(f"Next 后读到页码: {pg[0]}/{pg[1]}")
    if not pg:
        shot_window(out / "debug_no_page_number.png", win_id, rect)
        if not in_classroom:
            log("读不到页码：一直没等到教室（Preview Mode）— 确认久趣已打开并点进了教室。已存 debug_no_page_number.png，停。")
        elif not any_popup:
            log("读不到页码：在教室里但所有关弹窗点击都没产生画面变化 — 点击没落到久趣上（窗口被盖住/不在最前）。把久趣提到最前后重跑。已存 debug_no_page_number.png，停。")
        else:
            log("读不到页码：弹窗关了但还是进不到 Story 页。已存 debug_no_page_number.png，停。")
        return 2
    cur, total = pg
    log(f"读到页码: {cur}/{total}")

    # 4) 回第 1 页（Reset -> Prev 逐页回退，每步验证）
    #    Liang 2026-10-25 定：Reset/Prev 连点不动时，先点一次 Next 探活 —
    #    Next 能翻动说明点击是通的（多半是弹窗没关挡住了往回翻），再关一次
    #    弹窗继续回退；Next 也不动说明点击根本没落到久趣上（窗口被盖住），
    #    立刻停并说明原因，不再空转。
    def click_read(pt, wait=1.0):
        x, y = rel(rect, pt)
        click_abs(x, y)
        time.sleep(wait)
        return read_page(win_id, rect, tmpdir)

    if cur != 1:
        pg = click_read(RESET_BTN, 1.2)
        log(f"点 Reset 后页码: {pg}")
        if pg:
            cur, total = pg
        stuck = 0
        probed = False
        t = 0
        while cur > 1 and t < 14:
            before = cur
            pg = click_read(PREV_BTN, 0.9)
            t += 1
            log(f"点 Prev 后页码: {pg}")
            if pg:
                cur, total = pg
            stuck = stuck + 1 if cur == before else 0
            if stuck >= 3 and not probed:
                probed = True
                pg = click_read(NEXT_BTN, 1.2)
                if pg is None:
                    pg = read_page(win_id, rect, tmpdir)
                log(f"Prev 点不动，点 Next 探活: {pg}")
                if not pg or pg[0] == before:
                    log("Next 点了页码也不动 — 点击没落到久趣上（窗口被别的窗口盖住/不在最前）。把久趣提到最前后重跑。停。")
                    return 2
                cur, total = pg
                log("Next 能翻动：点击是通的。再关一次弹窗，继续 Prev 回第 1 页。")
                close_popup(win_id, rect, "WordBook2", WORDBOOK_CLOSE_CANDS, WORDBOOK_REGION, tmpdir)
                close_popup(win_id, rect, "教学提示4", TEACHING_CLOSE_CANDS, TEACHING_REGION, tmpdir)
                stuck = 0
    if cur != 1:
        log(f"没回到第 1 页（{cur}/{total}），停，避免从中间截。")
        return 2

    # 5) 逐页截 + 验证
    saved = []
    for i in range(1, total + 1):
        p = out / f"page-{i:02d}-of-{total:02d}.png"
        ok, err = shot_window(p, win_id, rect)
        if not ok:
            log(f"第 {i} 页截图失败: {err}")
            return 1
        saved.append(p)
        log(f"已截 {i}/{total} -> {p.name} ({p.stat().st_size} bytes)")
        if i == total:
            break
        advanced = False
        for attempt in range(1, 4):
            x, y = rel(rect, NEXT_BTN)
            click_abs(x, y)
            time.sleep(1.2)
            pg = None
            for _r in range(2):  # 先重读两次（OCR 偶发读空），读不到才算没翻动
                pg = read_page(win_id, rect, tmpdir)
                if pg:
                    break
                time.sleep(0.6)
            log(f"  Next 第{attempt}次后页码: {pg}")
            if pg and pg[0] == i + 1:
                advanced = True
                break
            if pg and pg[0] > i + 1:
                log("  页码跳过了，停，避免漏页")
                return 2
            time.sleep(0.5)
        if not advanced:
            shot_window(out / "debug_stuck.png", win_id, rect)
            log(f"翻不到第 {i+1} 页，已存 debug_stuck.png；前面 {i} 页都在。")
            return 2

    # 6) 近重复检查
    removed, prev = 0, None
    for p in saved:
        if prev and p.exists() and prev.exists():
            d = mean_diff(prev, p)
            log(f"相邻比对 {prev.name} vs {p.name}: diff={d:.2f}")
            if d < 1.5:
                p.unlink()
                removed += 1
                log(f"  近重复，已删 {p.name}")
                continue
        prev = p
    kept = [p.name for p in saved if p.exists()]
    log(f"完成：{folder} 保留 {len(kept)} 张，删近重复 {removed} 张 -> {kept}")

    # 7) 退出教室（OCR 验证回到详情页，被吞就原位重点）
    exit_classroom(win_id, rect, out, tmpdir)

    # 8) 清理（Liang 2026-10-22 定）：备课成功后文件夹只保留绘本页图，
    #    _tmp、capture.log、after_exit.png 全删。中途失败的返回路径不走
    #    这里，它们的日志/调试图保留供排查。
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
        (out / "after_exit.png").unlink(missing_ok=True)
        Path(LOG_PATH).unlink(missing_ok=True)
        print(f"已清理：{folder} 里只保留 {len(kept)} 张页图（_tmp/日志/退出图已删）", flush=True)
    except Exception as e:
        print(f"清理没做完（不影响截图）: {e}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except _Deadline:
        try:
            log("全局时限到点，停（这次运行卡得太久；日志停在哪一步，就是卡在哪一步）。")
        except Exception:
            print("全局时限到点，停。", flush=True)
        raise SystemExit(2)
