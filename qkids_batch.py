#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qkids_batch.py v9 — 久趣绘本批量截图（自动发现当前列表课程，配合 qkids_capture.py）

v9：页签选中检测 tab_selected 改逐行最大值法（旧版整条均值被细下
划线稀释，实测选中时只有 3.7，误判未选中）；配合 qkids_capture v8。

铁律（Liang 2026-10-21 定的）：每次操作前先重新获取久趣窗口
（重新查找 + 激活 + 固定位置），后面一系列点击/截图/OCR 都基于
这一次拿到的窗口 id 和 rect；绝不拿旧窗口信息一路点下去。

自动模式（默认）：
  获取窗口 -> 回首页 -> 若给了 --day 则切到该页签（验下划线；退出
  教室会把列表上下文扔回「今日课程」，每本书回来都要重切）-> OCR
  读右侧课程列表（按时间行定位）-> 滚动收集全部课
  -> 每节课：重新获取窗口 -> 回列表点进详情页 -> 读标题得准确书名
  -> books/<书名>/ 已有截图则跳过 -> 重新获取窗口 -> 点「进入教室」
  -> 等 Preview Mode -> 调用 qkids_capture.py --book 截图
     （关弹窗/逐页截/退出教室）-> 下一节。
  某本进教室失败（点不进去）-> 直接终止整个批量，不回主界面、
  不试下一本（Liang 2026-10-21 定）。
  本数、书名每天都不一样也没关系。

手动模式：--books "书名1" "书名2"（在列表里按书名 OCR 定位）。

用法（VS Code 集成终端或 Terminal.app 均可，两个宿主都已授权
      辅助功能 + 屏幕录制；运行前久趣窗口要在当前桌面上）：
  cd /Users/mac/workspace/kiki_um/qkids
  /opt/anaconda3/bin/python3 qkids_batch.py
  /opt/anaconda3/bin/python3 qkids_batch.py --day tomorrow  # 截明天的课（页签枚举 today/tomorrow）
  /opt/anaconda3/bin/python3 qkids_batch.py --force        # 已截过的也重截
  /opt/anaconda3/bin/python3 qkids_batch.py --books "Smells"

运行期间不要碰鼠标键盘。每本约 1 分钟。
单本失败存 debug 图到 books/<书名>/ 或 _batch_tmp/ 并继续，最后打印汇总。
"""
import argparse
import ctypes
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/mac/workspace/kiki_um/qkids")
sys.path.insert(0, str(BASE))
import qkids_capture as qc  # noqa: E402

HOME_BTN = (48, 397)        # 左侧边栏「首页」
ENTER_BTN = (887, 902)      # 详情页右下「进入教室」（2026-10-21 详情页实测按钮框 x788-986, y865-938，取正中心）
LIST_POINT = (920, 500)     # 右侧列表滚动点
PREVIEW_REGION = (250, 30, 430, 120)
HEADER_REGION = (150, 70, 620, 150)   # 详情页顶部标题区（实测标题带在纵向 85-135）
TAB_TODAY = (840, 138)      # 首页右上「今日课程」页签（2026-10-21 真窗口图实测）
TAB_TOMORROW = (907, 138)   # 首页右上「明日课程」页签（同上）

TMP = BASE / "books" / "_batch_tmp"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def acquire_window():
    """每次操作前先重新获取久趣窗口：重新查找 + 激活 + 固定到默认位置。
    返回 (win_id, rect)；后面一系列操作都基于这次拿到的窗口。
    找不到（没运行/最小化/不在当前桌面）重试 4 次后返回 (None, None)。"""
    for i in range(4):
        win = qc.find_qkids_window()
        if win:
            qc.activate_qkids()
            qc.set_window_rect(win["owner"], qc.DEFAULT_RECT)
            time.sleep(0.6)
            win2 = qc.find_qkids_window()
            if win2:
                win = win2
            rect = (win["x"], win["y"], win["w"], win["h"])
            say(f"  已获取久趣窗口 id={win['id']} rect={rect}")
            return win["id"], rect
        say(f"  第 {i + 1} 次没找到久趣窗口，3 秒后重试")
        time.sleep(3)
    return None, None


def shot(win_id, rect, name):
    p = TMP / name
    qc.shot_window(p, win_id, rect)
    return p


def ocr_full(path):
    r = qc.run(["/usr/local/bin/tesseract", str(path), "stdout", "--psm", "6"], timeout=60)
    return r.stdout or ""


def ocr_words(path):
    """tesseract TSV -> [(text, x0, y0, x1, y1, conf)]（图像像素坐标）"""
    r = qc.run(["/usr/local/bin/tesseract", str(path), "stdout", "--psm", "6", "tsv"], timeout=60)
    words = []
    for line in (r.stdout or "").splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12:
            continue
        try:
            left, top, w, h = int(f[6]), int(f[7]), int(f[8]), int(f[9])
            conf = float(f[10])
        except ValueError:
            continue
        txt = f[11].strip()
        if txt and conf >= 30:
            words.append((txt, left, top, left + w, top + h, conf))
    return words


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def group_lines(words, H):
    tol = H * 0.02
    words = sorted(words, key=lambda w: ((w[2] + w[4]) / 2, w[1]))
    lines = []
    for w in words:
        cy = (w[2] + w[4]) / 2
        if lines and abs(cy - lines[-1][0]) <= tol:
            ws = lines[-1][1] + [w]
            lines[-1] = (sum((x[2] + x[4]) / 2 for x in ws) / len(ws), ws)
        else:
            lines.append((cy, [w]))
    return [(cy, sorted(ws, key=lambda w: w[1])) for cy, ws in lines]


def find_title(win_id, rect, title):
    """手动模式：在当前窗口截图里找书名所在行，返回千分比点击点。"""
    from PIL import Image
    full = shot(win_id, rect, "nav.png")
    words = ocr_words(full)
    if not words:
        return None
    with Image.open(full) as im:
        W, H = im.size
    tw = norm(title).split()
    probe = tw[:3] if len(tw) >= 3 else tw
    words = [w for w in words if w[1] > W * 0.80]  # 只看右侧列表区，避开封面图上的同名文字
    for _, ws in group_lines(words, H):
        ltoks = [norm(w[0]) for w in ws]
        for i in range(0, max(1, len(ltoks) - len(probe) + 1)):
            if ltoks[i:i + len(probe)] == probe:
                sel = ws[i:i + len(probe)]
                x0 = min(w[1] for w in sel); x1 = max(w[3] for w in sel)
                y0 = min(w[2] for w in sel); y1 = max(w[4] for w in sel)
                return (int((x0 + x1) / 2 / W * 1000), int((y0 + y1) / 2 / H * 1000))
    return None


TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
CODE_RE = re.compile(r"([A-Za-z]{1,2})\s*-\s*(\d+)\.?\s*(.*)")


def discover_rows(win_id, rect):
    """自动模式：读当前屏右侧列表，返回 [{key, time, click}]（click 为千分比）。
    key = 时间+课程代码（如 18:00 C-11），同屏内唯一。"""
    from PIL import Image
    full = shot(win_id, rect, "rows.png")
    words = ocr_words(full)
    if not words:
        return []
    with Image.open(full) as im:
        W, H = im.size
    lines = group_lines(words, H)
    rows = []
    for li, (cy, ws) in enumerate(lines):
        for w in ws:
            if TIME_RE.match(w[0]) and w[1] > W * 0.72:
                code, hint = "", ""
                for cj, cws in lines[li:li + 3]:
                    txt = " ".join(x[0] for x in cws)
                    m = CODE_RE.search(txt)
                    if m:
                        code = f"{m.group(1).upper()}-{m.group(2)}"
                        hint = m.group(3).strip()
                        break
                key = f"{w[0]} {code}".strip()
                tcy = int(cy / H * 1000)
                click = (905, tcy + 26)
                rows.append({"key": key, "time": w[0], "code": code,
                             "hint": hint, "click": click, "tcy": tcy})
                break
    seen, out = set(), []
    for r in rows:
        if r["key"] not in seen:
            seen.add(r["key"])
            out.append(r)
    return out


def poll_rows(win_id, rect, tries=5, wait=1.2):
    """轮询等列表加载：读到行就返回，读不到等一会儿再读（不再读一次就下结论）。"""
    rows = []
    for _ in range(tries):
        rows = discover_rows(win_id, rect)
        if rows:
            return rows
        time.sleep(wait)
    return rows


def parse_detail_title(win_id, rect):
    """从详情页顶部标题 OCR 出书名，如 'C - U1 - 11. Peck, Peck, Peck' -> 书名。"""
    full = shot(win_id, rect, "header.png")
    crop = TMP / "header_crop.png"
    try:
        qc.crop_rel(full, HEADER_REGION, crop)
        txt = qc.ocr_image(crop)
    except Exception:
        txt = ""
    txt = " ".join(txt.split())
    say(f"  标题OCR: {txt[:70]!r}")
    m = re.search(r"-\s*\d+\.\s*(.+)$", txt)
    if m:
        return m.group(1).strip(" .")
    m = re.search(r"\d+\.\s*(.+)$", txt)
    if m:
        return m.group(1).strip(" .")
    return ""


def scroll_list(win_id, rect, delta=-6):
    cg = qc._cg
    try:
        cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
        cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                     ctypes.c_uint32, ctypes.c_int32]
        x, y = qc.rel(rect, LIST_POINT)
        qc._post(5, x, y)
        time.sleep(0.2)
        ev = cg.CGEventCreateScrollWheelEvent(None, 1, 1, int(delta))
        if ev:
            cg.CGEventPost(0, ev)
            qc._cf.CFRelease(ev)
    except Exception as e:
        say(f"  滚动失败（忽略）: {e}")


def click_rel(win_id, rect, pt, wait=1.0):
    x, y = qc.rel(rect, pt)
    qc.click_abs(x, y)
    say(f"  点击 {pt} -> ({x},{y})")
    time.sleep(wait)
    return x, y


def wait_preview(win_id, rect, timeout_s=30):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        full = shot(win_id, rect, "wait.png")
        crop = TMP / "wait_crop.png"
        try:
            qc.crop_rel(full, PREVIEW_REGION, crop)
            txt = qc.ocr_image(crop)
        except Exception:
            txt = ""
        if "preview" in txt.lower():
            return True
        time.sleep(2.0)
    return False


def already_captured(title):
    d = BASE / "books" / qc.slugify(title)
    return d.exists() and any(d.glob("page-*.png"))


def capture_current(title, outdir):
    """进教室前先重新获取窗口；之后一系列操作都基于这次拿到的窗口。
    已在详情页时调用：校验详情页 -> 点进入教室 -> 调单本脚本。"""
    win_id, rect = acquire_window()
    if win_id is None:
        return "窗口获取失败"
    txt = ocr_full(shot(win_id, rect, "detail.png"))
    if "overview" not in txt.lower():
        qc.shot_window(outdir / "debug_batch_nodetail.png", win_id, rect)
        return "未进详情页"
    ready = False
    for _ in range(3):
        click_rel(win_id, rect, ENTER_BTN, wait=2.0)
        if wait_preview(win_id, rect, timeout_s=45):
            ready = True
            break
        say("  教室还没出来，再点一次进入教室（久趣常吞第一次点击）")
    if not ready:
        qc.shot_window(outdir / "debug_batch_noclass.png", win_id, rect)
        return "教室未加载"
    say("  教室已就绪，开始截图…")
    r = subprocess.run([sys.executable, str(BASE / "qkids_capture.py"), "--book", title],
                       cwd=str(BASE), timeout=900)
    return f"capture rc={r.returncode}"


def tab_selected(win_id, rect, day):
    """看页签文字下方有没有蓝色选中下划线（裁条验像素，不靠 OCR 猜）。
    逐行判定：下划线只有几像素高，整条 (B-R) 均值会被稀释 — 实测页签
    真选中时整条均值只有 3.7，旧版误判未选中。改看单行均值的最大值：
    下划线所在行横贯裁条、整行偏蓝，行均值会明显抬高。"""
    from PIL import Image
    cx = TAB_TODAY[0] if day == "today" else TAB_TOMORROW[0]
    full = shot(win_id, rect, "tab.png")
    strip = TMP / "tab_strip.png"
    try:
        qc.crop_rel(full, (cx - 30, 155, cx + 30, 190), strip)
        with Image.open(strip) as im:
            px = im.convert("RGB")
            w, h = px.size
            best = 0.0
            for Y in range(h):
                rs = bs = n = 0
                for X in range(0, w, 2):
                    r, g, b = px.getpixel((X, Y))
                    rs += r
                    bs += b
                    n += 1
                if n:
                    best = max(best, (bs - rs) / n)
            return best > 30
    except Exception:
        return False


def ensure_tab(win_id, rect, day):
    """把页签切到 day（today/tomorrow），用下划线验证；被吞就再点一次。"""
    if tab_selected(win_id, rect, day):
        return True
    pt = TAB_TODAY if day == "today" else TAB_TOMORROW
    for _ in range(2):
        click_rel(win_id, rect, pt, wait=1.2)
        if tab_selected(win_id, rect, day):
            say(f"  页签已切到 {day}（下划线验证通过）")
            return True
        say(f"  页签还没切到 {day}，再点一次")
    return tab_selected(win_id, rect, day)


def goto_list(day=None):
    """先重新获取窗口，再基于它回首页课程列表。
    day 给定时（--day today|tomorrow）：回列表后把页签切到该日并验下划线 —
    退出教室会把列表上下文扔回「今日课程」，每本书回来都要重新切。
    day 不给时读当前页签、绝不点页签。返回 (win_id, rect)。"""
    win_id, rect = acquire_window()
    if win_id is None:
        return None, None
    click_rel(win_id, rect, HOME_BTN, wait=1.8)
    if day:
        ensure_tab(win_id, rect, day)
    for _ in range(2):
        if poll_rows(win_id, rect):
            break
        say("  列表还没读到行，可能首页点击被吞，再点一次")
        click_rel(win_id, rect, HOME_BTN, wait=1.8)
        if day:
            ensure_tab(win_id, rect, day)
    return win_id, rect


def run_auto(force, day=None):
    results = {}
    win_id, rect = goto_list(day)
    if win_id is None:
        say("获取不到久趣窗口，停。")
        return results
    say("  读当前显示的页签列表（今日/明日由 Liang 选，脚本不切页签）")
    for _ in range(3):
        scroll_list(win_id, rect, delta=10)
        time.sleep(0.4)
    keys, seen = [], set()
    for s in range(4):
        for r in discover_rows(win_id, rect):
            if r["key"] not in seen:
                seen.add(r["key"])
                keys.append(r["key"])
        scroll_list(win_id, rect)
        time.sleep(1.0)
    for _ in range(4):
        scroll_list(win_id, rect, delta=10)
        time.sleep(0.4)
    say(f"发现 {len(keys)} 节课: {keys}")
    if not keys:
        qc.shot_window(TMP / "debug_home.png", win_id, rect)
        say("列表是空的？已存 _batch_tmp/debug_home.png")
        return results

    for idx, key in enumerate(keys, 1):
        say(f"=== [{idx}/{len(keys)}] {key} ===")
        # 每节课都先重新获取窗口，再基于它回列表找行（页签按 day 重新切）
        win_id, rect = goto_list(day)
        if win_id is None:
            results[key] = "窗口获取失败"
            continue
        pt = None
        for s in range(4):
            for r in discover_rows(win_id, rect):
                if r["key"] == key:
                    pt = r["click"]
                    break
            if pt:
                break
            scroll_list(win_id, rect)
            time.sleep(1.0)
        if not pt:
            say(f"  找不到行 {key}，跳过")
            results[key] = "行未找到"
            continue
        title = ""
        for cand in [pt, pt, (905, pt[1] + 26), (905, pt[1] - 26)]:
            click_rel(win_id, rect, cand, wait=2.5)
            title = parse_detail_title(win_id, rect)
            if title:
                break
            say("  还没进详情页，再点一次（先原位重点，久趣常吞点击；后两次换位置）")
        if not title:
            qc.shot_window(TMP / f"debug_title_{idx}.png", win_id, rect)
            say("  详情页书名没读出来，跳过（debug 图在 _batch_tmp/）")
            results[key] = "书名未读出"
            continue
        say(f"  书名: 《{title}》")
        outdir = BASE / "books" / qc.slugify(title)
        outdir.mkdir(parents=True, exist_ok=True)
        if not force and already_captured(title):
            say("  已有截图，跳过（--force 可重截）")
            results[title] = "已截过跳过"
            continue
        status = capture_current(title, outdir)
        results[title] = status
        say(f"  《{title}》: {status}")
        if status != "capture rc=0":
            say("  进教室失败，按 Liang 要求直接终止批量（不回主界面、不继续下一本）")
            return results
        time.sleep(1.0)
    return results


def run_manual(books, force):
    results = {}
    for idx, title in enumerate(books, 1):
        say(f"=== [{idx}/{len(books)}] {title} ===")
        outdir = BASE / "books" / qc.slugify(title)
        outdir.mkdir(parents=True, exist_ok=True)
        if not force and already_captured(title):
            say("  已有截图，跳过（--force 可重截）")
            results[title] = "已截过跳过"
            continue
        # 先重新获取窗口，再基于它回首页找这本书
        win_id, rect = acquire_window()
        if win_id is None:
            results[title] = "窗口获取失败"
            continue
        click_rel(win_id, rect, HOME_BTN, wait=2.0)
        pt = None
        for attempt in range(3):
            pt = find_title(win_id, rect, title)
            if pt:
                break
            say(f"  列表里没找到《{title}》，滚动后重试 {attempt + 1}/3")
            scroll_list(win_id, rect)
            time.sleep(1.2)
        if not pt:
            qc.shot_window(outdir / "debug_batch_notfound.png", win_id, rect)
            results[title] = "列表未找到"
            continue
        click_rel(win_id, rect, pt, wait=2.5)
        status = capture_current(title, outdir)
        results[title] = status
        say(f"  《{title}》: {status}")
        time.sleep(1.0)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--day", choices=["today", "tomorrow"], default=None,
                    help="截哪天的课（枚举）：退出教室会把列表扔回今日，所以每次回列表都按这个切页签")
    args = ap.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)

    post_ok, cap_ok = qc.preflight()
    say(f"权限: 点击={post_ok} 截图={cap_ok}")
    if post_ok is False:
        say("点击权限=False，先给运行脚本的终端开辅助功能。停。")
        return 3

    # 开工先获取一次窗口，确认久趣可用；之后每个环节内部还会各自重新获取
    win_id, _rect = acquire_window()
    if win_id is None:
        say("获取不到久趣窗口（没在运行/最小化/不在当前桌面）。停。")
        return 1

    if args.books:
        say(f"手动模式: {args.books}")
        results = run_manual(args.books, args.force)
    else:
        say(f"自动模式：读列表发现全部课程（day={args.day or '当前页签'})")
        results = run_auto(args.force, args.day)

    say("=== 批量汇总 ===")
    for t, s in results.items():
        say(f"  {t}: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
