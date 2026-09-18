#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立复核器（格子级，不依赖 solve_fast.py 的连通块模型）

目的：交付前用**另一套实现**再算一遍「一直点同一格」的所有可行解，
      两边给出的「步数 / 可用点击格数量 / 颜色顺序」必须一致。
      本项目已经靠它抓到过两版脚本给出不同颜色顺序的问题。

做法：完全按格子操作 —— 每步对整张 63 格棋盘做一次洪水填充，不用连通块图、不用状态压缩。

用法:
  python crosscheck.py --board board.txt [--colors RYGB] [--max-len 6]
  报告写到 <board同目录>/crosscheck_report.txt
"""
import argparse
import itertools
import os

NAMES = {"R": "红", "Y": "黄", "G": "绿", "B": "蓝",
         "P": "紫", "O": "橙", "C": "青", "K": "黑", "W": "白"}


def region(g, r, c):
    """(r,c) 所在的四邻连通同色区域（格子列表）"""
    nr, nc = len(g), len(g[0])
    col = g[r][c]
    seen, stack = {(r, c)}, [(r, c)]
    while stack:
        y, x = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < nr and 0 <= nx < nc and (ny, nx) not in seen and g[ny][nx] == col:
                seen.add((ny, nx))
                stack.append((ny, nx))
    return list(seen)


def n_blocks(g):
    """当前棋盘的非目标色连通块数（只用于信息展示）"""
    nr, nc = len(g), len(g[0])
    seen = set()
    cnt = 0
    for r in range(nr):
        for c in range(nc):
            if (r, c) in seen:
                continue
            cells = region(g, r, c)
            seen.update(cells)
            cnt += 1
    return cnt


def run_fixed(grid, target, colors, pt, seq):
    """一直点 pt，按 seq 的顺序画色。返回 (是否通关, 每步染色格数, 快照)"""
    g = [list(row) for row in grid]
    sizes, snaps = [], []
    for col in seq:
        cells = region(g, pt[0], pt[1])
        if g[pt[0]][pt[1]] == col:      # 画笔色 == 当前色 = 空操作
            return False, sizes, snaps
        sizes.append(len(cells))
        g = [row[:] for row in g]
        for (y, x) in cells:
            g[y][x] = col
        snaps.append([row[:] for row in g])
    return all(ch == target for row in g for ch in row), sizes, snaps


def solve_same_cell(grid, target, colors, max_len=6):
    """枚举「一直点同一格」的全部最短解，返回 (最短步数, {步数: [((r,c),seq,sizes,snaps), ...]})。

    两处**严格等价**的剪枝（不改变任何结论，只省算力）：
      1) 首色 == 该格起始色 -> run_fixed 第一步就是空操作，必失败；
      2) 相邻两步同色 -> 第 2 步时该格已是前一颜色，必空操作。
    实测能砍掉约 3/4 的候选序列。
    """
    NR, NC = len(grid), len(grid[0])
    best, found = None, {}
    for L in range(1, max_len + 1):
        for r in range(NR):
            for c in range(NC):
                start = grid[r][c]
                for seq in itertools.product(colors, repeat=L):
                    if seq[0] == start:
                        continue
                    if any(seq[i] == seq[i + 1] for i in range(L - 1)):
                        continue
                    ok, sizes, snaps = run_fixed(grid, target, colors, (r, c), seq)
                    if ok:
                        found.setdefault(L, []).append(((r, c), seq, sizes, snaps))
        if found.get(L):
            best = L
            break
    return best, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--colors", default=None)
    ap.add_argument("--max-len", type=int, default=6)
    a = ap.parse_args()

    # utf-8-sig：兼容 Windows PowerShell 写出的带 BOM 文件
    with open(a.board, encoding="utf-8-sig") as f:
        ls = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if len(ls) < 2:
        raise SystemExit("棋盘文件至少要有 1 行棋盘 + 1 行目标色")
    target, grid = ls[-1], ls[:-1]
    if len(set(len(r) for r in grid)) != 1:
        raise SystemExit("棋盘各行长度不一致：%s" % [len(r) for r in grid])
    colors = a.colors or "".join(dict.fromkeys("".join(grid)))
    bad = sorted(set("".join(grid) + target) - set(colors))
    if bad:
        raise SystemExit("棋盘里出现了 --colors 里没有的颜色 %s，请补进 --colors" % bad)
    NR, NC = len(grid), len(grid[0])

    out = []
    out.append("=" * 76)
    out.append("独立复核（格子级洪水填充实现，不复用 solve_fast.py）")
    out.append("棋盘 %d 行 x %d 列；可用色 %s；目标 %s" % (NR, NC, colors, NAMES.get(target, target)))
    out.append("当前连通块总数 = %d" % n_blocks(grid))
    out.append("=" * 76)

    best, found = solve_same_cell(grid, target, colors, a.max_len)
    found = {best: found.get(best, [])} if best else found

    out.append("")
    out.append("同格法最短步数 = %s" % best)
    items = found.get(best, []) if best else []
    out.append("同格法最短解共 %d 条，覆盖 %d 个可点格"
               % (len(items), len({it[0] for it in items})))
    out.append("")

    by_cell = {}
    for pt, seq, sizes, snaps in items:
        by_cell.setdefault(pt, []).append((seq, sizes))

    out.append("-" * 76)
    out.append("按点击格列出（每格的可行颜色顺序 + 每步染色格数）")
    out.append("-" * 76)
    for pt in sorted(by_cell):
        r, c = pt
        out.append("点 第%d行第%d列（起始色%s）:" % (r + 1, c + 1, grid[r][c]))
        for seq, sizes in sorted(by_cell[pt], key=lambda t: t[0]):
            out.append("     %s   每步染色 %s   -> 共%d步"
                       % (" → ".join(NAMES.get(x, x) for x in seq), sizes, len(seq)))
    out.append("")

    seqmap = {}
    for pt, seq, sizes, snaps in items:
        seqmap.setdefault(" → ".join(NAMES.get(x, x) for x in seq), []).append(pt)
    out.append("-" * 76)
    out.append("按颜色顺序聚合（用来挑最宽容的一条）")
    out.append("-" * 76)
    for s in sorted(seqmap, key=lambda k: -len(seqmap[k])):
        cells = sorted(seqmap[s])
        out.append("序列 %s ：可点格 %d 个" % (s, len(cells)))
        out.append("     " + ", ".join("(第%d行第%d列)" % (r + 1, c + 1) for r, c in cells))
    out.append("")

    out.append("-" * 76)
    out.append("每条颜色顺序的逐步过程（各取一个代表格）")
    out.append("-" * 76)
    for s in sorted(seqmap):
        pt = sorted(seqmap[s])[0]
        rec = [it for it in items
               if it[0] == pt and " → ".join(NAMES.get(x, x) for x in it[1]) == s][0]
        _pt, seq, sizes, snaps = rec
        out.append("")
        out.append(">>> 一直点 第%d行第%d列，顺序 %s" % (pt[0] + 1, pt[1] + 1, s))
        out.append("    初始:")
        for row in grid:
            out.append("      " + " ".join(row))
        for i, (snap, sz) in enumerate(zip(snaps, sizes), 1):
            out.append("    第%d步 画%s（染了 %d 格）:" % (i, NAMES.get(seq[i - 1], seq[i - 1]), sz))
            for row in snap:
                out.append("      " + " ".join(row))

    p = os.path.join(os.path.dirname(os.path.abspath(a.board)), "crosscheck_report.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("crosscheck done -> %s" % p)


if __name__ == "__main__":
    main()
