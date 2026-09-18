#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画盘类染色棋盘求解器

机制：选画笔颜色点某一格 → 该格所在的整块连通同色区变成画笔色。
目标：全盘变成目标色，步数最少。

关键：区域被并大后再点同一格，染的是「长大了的那块」→ 最优解常常是「一直点同一格」。

用法:
  python solve.py --board board.txt --out <目录>
  board.txt 每行一串颜色字母，最后一行是目标色，例如:
      RGGGBBBBB
      RYYRRRRRR
      ...
      R

输出（写文件）:
  <out>/solve_report.txt   连通块 / 最短步数 / 全部最短解 / 同格法点击格清单
  <out>/solve_route.png    最优同格法路线的逐步通关图
"""
import argparse
import itertools
import os
from collections import deque

from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"
NAMES = {"R": "红", "Y": "黄", "G": "绿", "B": "蓝",
         "P": "紫", "O": "橙", "C": "青", "K": "黑", "W": "白"}
PAL = {"R": (250, 140, 122), "Y": (245, 218, 98), "G": (95, 235, 150),
       "B": (167, 210, 252), "P": (200, 150, 240), "O": (245, 175, 100),
       "C": (130, 220, 220), "K": (90, 90, 90), "W": (240, 240, 240)}


class Board:
    def __init__(self, grid, target, colors):
        self.GRID = grid
        self.NR = len(grid)
        self.NC = len(grid[0])
        self.TARGET = target
        self.COLORS = colors

    def comps(self, g):
        NR, NC = self.NR, self.NC
        lab = [[-1] * NC for _ in range(NR)]
        out = []
        for r in range(NR):
            for c in range(NC):
                if lab[r][c] != -1:
                    continue
                idx = len(out)
                lab[r][c] = idx
                q = deque([(r, c)])
                cells = []
                while q:
                    y, x = q.popleft()
                    cells.append((y, x))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < NR and 0 <= nx < NC and lab[ny][nx] == -1 \
                                and g[ny][nx] == g[y][x]:
                            lab[ny][nx] = idx
                            q.append((ny, nx))
                out.append((g[r][c], cells))
        return lab, out

    def bad(self, g):
        _, cs = self.comps(g)
        return sum(1 for col, _ in cs if col != self.TARGET)

    def key(self, g):
        return "".join("".join(r) for r in g)

    def gen(self, g):
        lab, cs = self.comps(g)
        res = []
        for col, cells in cs:
            for c in self.COLORS:
                if c == col:
                    continue
                ng = [row[:] for row in g]
                for (y, x) in cells:
                    ng[y][x] = c
                res.append((ng, cells[0], col, c, len(cells)))
        return res

    def bfs_all(self, limit=10):
        """逐层 BFS（必须逐层+全局去重，DFS+visited 会误剪最短路径）"""
        start = [list(r) for r in self.GRID]
        if self.bad(start) == 0:
            return 0, [[]]
        seen = {self.key(start)}
        frontier = [(start, [])]
        for depth in range(1, limit + 1):
            nxt, sols = [], []
            for g, path in frontier:
                for ng, cell, _c0, c, _n in self.gen(g):
                    k = self.key(ng)
                    np_ = path + [(cell, c)]
                    if self.bad(ng) == 0:
                        sols.append(np_)
                        continue
                    if k in seen:
                        continue
                    seen.add(k)
                    nxt.append((ng, np_))
            if sols:
                return depth, sols
            if not nxt:
                break
            frontier = nxt
        return None, []

    def fixed_cell(self, pt, maxlen=10):
        """枚举颜色序列，返回「一直点 pt 这一格」能通关的最短序列"""
        for L in range(1, maxlen + 1):
            sols = []
            for seq in itertools.product(self.COLORS, repeat=L):
                g = [list(r) for r in self.GRID]
                frames, sizes, ok = [], [], True
                for c in seq:
                    lab, cs = self.comps(g)
                    c0, cells = cs[lab[pt[0]][pt[1]]]
                    if c == c0:
                        ok = False
                        break
                    ng = [row[:] for row in g]
                    for (y, x) in cells:
                        ng[y][x] = c
                    g = ng
                    frames.append([row[:] for row in g])
                    sizes.append(len(cells))
                if ok and self.bad(g) == 0:
                    sols.append((seq, frames, sizes))
            if sols:
                return L, sols
        return None, []

    def render(self, pt, seq, frames, sizes, out_dir):
        CW, CH = 62, 62
        try:
            ft = ImageFont.truetype(FONT, 26)
            f = ImageFont.truetype(FONT, 22)
            fs = ImageFont.truetype(FONT, 17)
        except Exception:
            ft = f = fs = None
        nframe = len(frames) + 1
        W = (CW * self.NC + 24) * nframe + 40
        H = CH * self.NR + 26 + 140
        canvas = Image.new("RGB", (W, H), (30, 32, 38))
        d = ImageDraw.Draw(canvas)
        if ft:
            d.text((20, 14), "一直点第%d行第%d列那一格（黑圈处），依次用：%s"
                   % (pt[0] + 1, pt[1] + 1, " → ".join(NAMES.get(c, c) for c in seq)),
                   font=ft, fill=(240, 240, 240))
            d.text((20, 50), "目标：全盘变%s   共 %d 步"
                   % (NAMES.get(self.TARGET, self.TARGET), len(seq)), font=f, fill=(120, 235, 150))
        allframes = [([list(r) for r in self.GRID], "初始")] + \
                    [(fr, "第%d步 画%s(%d格)" % (i + 1, NAMES.get(seq[i], seq[i]), sizes[i]))
                     for i, fr in enumerate(frames)]
        x, y0 = 20, 92
        for g, cap in allframes:
            for r in range(self.NR):
                for c in range(self.NC):
                    px0, py0 = x + c * CW, y0 + r * CH
                    d.rectangle([px0, py0, px0 + CW - 3, py0 + CH - 3],
                                fill=PAL.get(g[r][c], (128, 128, 128)), outline=(255, 255, 255))
            d.rectangle([x - 3, y0 - 3, x + CW * self.NC, y0 + CH * self.NR], outline=(90, 94, 106))
            px0, py0 = x + pt[1] * CW, y0 + pt[0] * CH
            cx, cy = px0 + CW // 2 - 1, py0 + CH // 2 - 1
            d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(20, 20, 20), width=3)
            if fs:
                d.text((x, y0 + CH * self.NR + 6), cap, font=fs, fill=(200, 205, 215))
            x += CW * self.NC + 24
        path = os.path.join(out_dir, "solve_route.png")
        canvas.save(path)
        return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, help="棋盘文件：每行一串色字母，末行为目标色")
    ap.add_argument("--out", required=True)
    ap.add_argument("--colors", default=None, help="可用颜色字母，默认从棋盘里去重推断")
    ap.add_argument("--max-depth", type=int, default=10)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    # utf-8-sig：兼容 Windows PowerShell 写出的带 BOM 文件
    with open(a.board, encoding="utf-8-sig") as f:
        ls = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    target = ls[-1]
    grid = ls[:-1]
    if a.colors:
        colors = a.colors
    else:
        colors = "".join(dict.fromkeys("".join(grid)))

    b = Board(grid, target, colors)
    rep = []
    rep.append("棋盘 %d 列 x %d 行，共 %d 格；可用色 %s；目标 %s"
               % (b.NC, b.NR, b.NR * b.NC, colors, target))
    _, cs = b.comps([list(r) for r in grid])
    rep.append("连通块 %d 个：" % len(cs))
    for col, cells in sorted(cs, key=lambda t: -len(t[1])):
        rep.append("   色%s %2d 格" % (col, len(cells)))
    bad0 = b.bad([list(r) for r in grid])
    rep.append("非目标色块 = %d 个" % bad0)
    rep.append("")

    d, sols = b.bfs_all(a.max_depth)
    rep.append("最短步数 = %s" % d)
    rep.append("最短解共 %d 条" % len(sols))
    for i, s in enumerate(sols[:30], 1):
        rep.append("   解%d: %s" % (i, " -> ".join(
            "%s@(第%d行第%d列)" % (NAMES.get(c, c), cell[0] + 1, cell[1] + 1) for cell, c in s)))
    rep.append("")

    good = []
    for r in range(b.NR):
        for c in range(b.NC):
            L, ss = b.fixed_cell((r, c), maxlen=(d or a.max_depth))
            if ss and d is not None and L == d:
                good.append(((r, c), ss[0]))
    rep.append("「一直点同一格」可通关的点击格 %d 个（步数=最短）：" % len(good))
    for (r, c), (seq, _fr, _sz) in good:
        rep.append("   点第%d行第%d列（该格起色%s）：%s"
                   % (r + 1, c + 1, grid[r][c], " → ".join(NAMES.get(x, x) for x in seq)))
    rep.append("")

    if good:
        (r, c), (seq, frames, sizes) = good[0]
        rep.append("推荐路线：一直点第%d行第%d列，依次 %s"
                   % (r + 1, c + 1, " → ".join(NAMES.get(x, x) for x in seq)))
        p = b.render((r, c), seq, frames, sizes, a.out)
        rep.append("通关过程图 -> %s" % p)
    else:
        rep.append("没找到同格法，可从上面的最短解里挑一条（不同步点不同格）")

    with open(os.path.join(a.out, "solve_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print("done")


if __name__ == "__main__":
    main()
