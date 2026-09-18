# -*- coding: utf-8 -*-
"""出图后的「成品反查」——从 render_delivery.py 产出的 PNG 里把每帧面板逐格取色，
与「该步动手前应有的盘面」比对，确认*画出来的*和*算出来的*一致。

为什么需要这一步：Read 工具显示的是缩略图，红/黄在缩小后极易看错（本项目实测踩过：
第 6 关把红读成黄、第 8 关把蓝圈看成红圈），人眼验收不可靠。本脚本直接对像素做最近色归类。

校验两件事：
  1) 每帧盘面 63 格与求解结果逐格一致；
  2) 每帧的**圈**存在、颜色 = 本步画笔墨色、且圈心落在要点的格子上。
     （圈是交付图的灵魂——"点哪一格"全靠它传达，只查瓦片颜色是查不出圈画错的。）

版面参数与 render_delivery.py 共用同一套规则（panel_w_for / cell_px），不再硬编码；
棋盘的**原点也不硬编码**——逐列扫描"瓦片色像素带"自动定位，
这样顶部标题行数、副标题折行数、面板说明行数变化都不会让校验跑偏。

用法：
    python verify_render.py --png 画盘8_通关路线.png --board board8.txt \
        --tap 1,4 --seq YBRGB

退出码非 0 表示盘面或圈对不上（会打印差异）。

也可作为模块调用：
    from verify_render import verify
    ok, lines = verify(png, grid, target, (r, c), seq)
"""
import argparse
import os
import sys
from collections import Counter

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_delivery import (read_board, simulate, CELL, INK,   # noqa: E402
                             cell_px, panel_w_for, GAP_X, PAD, CARD_PAD)

TOL = 2600          # 与标准色的平方距离上限，超过判为「?」
INK_TOL = 1500      # 圈墨色的判定阈值
RING_MIN = 200      # 圈应有的墨色像素数（实测 628）
RING_OFF_MAX = 6.0  # 圈心允许的最大偏移（px）


def classify(p):
    best, bd = "?", 10 ** 9
    for k, v in CELL.items():
        d = sum((p[i] - v[i]) ** 2 for i in range(3))
        if d < bd:
            bd, best = d, k
    return best if bd < TOL else "?"


def locate_boards(img, x0, nc, nr, cell, panel_w):
    """在某一列面板的 x 区间内，扫描出该列各面板的棋盘上边缘 y。

    做法：逐行统计 [bxl, bxl+nc*cell) 里"瓦片色像素"的个数，比例够高就算"有棋盘"，
    连续的 y 归成一条"瓦片带"（= 棋盘的 1 行），每 nr 条带 = 一个面板。
    这样完全不依赖顶部标题/副标题/说明文字占了几行。
    """
    W, H = img.size
    px = img.load()
    bxl = x0 + (panel_w - nc * cell) // 2

    def row_ok(y):
        n = 0
        for c in range(nc):
            for dx in (5, cell // 2, cell - 6):
                x = bxl + c * cell + dx
                if 0 <= x < W and classify(px[x, y]) != "?":
                    n += 1
        return n >= int(nc * 3 * 0.7)

    ys = [y for y in range(60, H) if row_ok(y)]
    if not ys:
        return [], bxl
    segs, cur = [], [ys[0]]
    for a, b in zip(ys, ys[1:]):
        if b - a <= 3:
            cur.append(b)
        else:
            segs.append(cur)
            cur = [b]
    segs.append(cur)

    tops, i = [], 0
    while i + nr - 1 < len(segs):
        # 只接受"连续 nr 条、间距合理"的一组，防止把别的色带当成棋盘行
        grp = segs[i:i + nr]
        gaps = [grp[j + 1][0] - grp[j][0] for j in range(nr - 1)]
        if gaps and abs(sum(gaps) / len(gaps) - cell) <= 3:
            tops.append(grp[0][0] - 2)      # 瓦片外还有 2px 留白
            i += nr
        else:
            i += 1
    return tops, bxl


def sample(img, bx, by, nc, nr, cell):
    px = img.load()
    out = []
    for r in range(nr):
        row = []
        for c in range(nc):
            x = int(bx + (c + 0.5) * cell)
            y = int(by + (r + 0.5) * cell)
            row.append(classify(px[x, y]))
        out.append(row)
    return out


def ring_check(img, bx, by, cell, tap, col):
    """返回 (墨色像素数, 圈心偏移px 或 None, 圈色是否为本步墨色)"""
    W, H = img.size
    px = img.load()
    cx = bx + tap[1] * cell + cell // 2
    cy = by + tap[0] * cell + cell // 2
    ink = INK[col]
    pts = []
    for y in range(max(0, cy - 40), min(H, cy + 41)):
        for x in range(max(0, cx - 40), min(W, cx + 41)):
            p = px[x, y]
            if sum((p[i] - ink[i]) ** 2 for i in range(3)) < INK_TOL:
                pts.append((x, y))
    if not pts:
        return 0, None, False
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    off = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
    return len(pts), off, True


def verify(png_path, grid, target, tap, seq, cols=None):
    """校验一张交付图。tap=(行,列) 均从 1 计。返回 (ok, lines)。"""
    nr, nc = len(grid), len(grid[0])
    r, c = tap
    steps, _final = simulate(grid, (r - 1, c - 1), seq.upper())
    n = len(steps)
    ncols = cols or (2 if n <= 4 else 3)
    cell = cell_px(nc)
    panel_w = panel_w_for(nc)

    img = Image.open(png_path).convert("RGB")
    W, H = img.size
    lines = ["png=%dx%d  cell=%d  panel_w=%d" % (W, H, cell, panel_w)]

    # ---- 自动定位每列各面板的棋盘原点 ----
    origins = {}
    for ck in range(ncols):
        x0 = PAD + ck * (panel_w + GAP_X)
        want = sum(1 for k in range(n) if k % ncols == ck)   # 末列面板数可能少于行数
        tops, bxl = locate_boards(img, x0, nc, nr, cell, panel_w)
        if len(tops) != want:
            lines.append("FAIL: 第 %d 列扫到 %d 个面板，期望 %d 个（版面规则不匹配？）"
                         % (ck + 1, len(tops), want))
            return False, lines
        cols_k = [kk for kk in range(n) if kk % ncols == ck]
        for i, k in enumerate(cols_k):
            origins[k] = (bxl, tops[i])
    lines.append("自动定位棋盘原点：" + "  ".join(
        "面板%d=(%d,%d)" % (k + 1, origins[k][0], origins[k][1]) for k in sorted(origins)))

    ok = True
    for k, (before, size, col) in enumerate(steps):
        bx, by = origins[k]
        got = sample(img, bx, by, nc, nr, cell)
        diff = [(i + 1, j + 1, before[i][j], got[i][j])
                for i in range(nr) for j in range(nc) if before[i][j] != got[i][j]]
        tag = "第 %d 帧（选【%s】，染 %d 格）" % (k + 1, col, size)
        if diff:
            ok = False
            lines.append("  %s  x 盘面 %d 格不符：%s" % (tag, len(diff), diff[:8]))
        else:
            cnt = Counter(v for row in before for v in row)
            lines.append("  %s  OK 盘面逐格一致 %s" % (tag, dict(sorted(cnt.items()))))
        npix, off, found = ring_check(img, bx, by, cell, (r - 1, c - 1), col)
        if not found or npix < RING_MIN:
            ok = False
            lines.append("       x 圈缺失或圈色不对（墨色像素 %d < %d）" % (npix, RING_MIN))
        elif off > RING_OFF_MAX:
            ok = False
            lines.append("       x 圈心偏移 %.1f px（上限 %.1f）" % (off, RING_OFF_MAX))
        else:
            lines.append("       OK 圈：墨色 %d px、圈心偏移 %.1f px、圈色=本步画笔色"
                         % (npix, off))
    lines.append("RESULT: " + ("PASS 交付图与求解结果一致" if ok else "FAIL 交付图与求解结果不符"))
    return ok, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", required=True)
    ap.add_argument("--board", required=True)
    ap.add_argument("--tap", required=True, help="1 基 r,c")
    ap.add_argument("--seq", required=True)
    ap.add_argument("--cols", type=int, default=None, choices=[2, 3])
    a = ap.parse_args()

    grid, target = read_board(a.board)
    r, c = (int(v) for v in a.tap.split(","))
    ok, lines = verify(a.png, grid, target, (r, c), a.seq.upper(), a.cols)
    for ln in lines:
        print(ln)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
