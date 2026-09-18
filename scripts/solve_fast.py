#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画盘类染色棋盘求解器（高效版）

为什么需要这一版：
  solve.py 用「整盘字符串」做 BFS 状态，深度 5 时状态数爆炸（每态都要重跑连通块分析），
  实测第 11/12 关跑不出来。本脚本改用**组件图状态**：

  【关键不变量】染色永远不会把一块拆开 —— 一个当前的连通块 = 若干**初始连通块的并集**。
  所以每块初始连通块在任意时刻都是单色的，整个局面可由「每块初始块当前什么颜色」唯一表示。
  状态数上限从 4^63 降到 4^(初始块数)，且每次转移只动连通块图上的几个节点。

  对第 10~12 关实测：初始块约 10 个，深度 5 的 BFS 秒级完成。

用法与 solve.py 一致:
  python solve_fast.py --board board.txt --out <目录> [--colors RYGB] [--max-depth 6]
输出:
  <out>/solve_report.txt    连通块图 / 最短步数 / 全部最短解 / 同格法清单
  <out>/solve_route.png     推荐同格法路线的逐步通关图
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


# ---------------------------------------------------------------- 建图

class Model:
    def __init__(self, grid, target, colors):
        self.GRID = [list(r) for r in grid]
        self.NR, self.NC = len(self.GRID), len(self.GRID[0])
        self.TARGET = target
        self.COLORS = colors

        # 1) 初始连通块（四邻同色）
        lab = [[-1] * self.NC for _ in range(self.NR)]
        comps = []
        for r in range(self.NR):
            for c in range(self.NC):
                if lab[r][c] != -1:
                    continue
                idx = len(comps)
                lab[r][c] = idx
                q = deque([(r, c)])
                cells = []
                while q:
                    y, x = q.popleft()
                    cells.append((y, x))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < self.NR and 0 <= nx < self.NC \
                                and lab[ny][nx] == -1 \
                                and self.GRID[ny][nx] == self.GRID[y][x]:
                            lab[ny][nx] = idx
                            q.append((ny, nx))
                comps.append(cells)

        self.lab = lab
        self.comps = comps
        self.N = len(comps)
        self.c0 = tuple(self.COLORS.index(self.GRID[cells[0][0]][cells[0][1]])
                        for cells in comps)
        # 加速用：每块的代表格（块内坐标最小）预存，省掉 BFS 里反复 min()
        self.comp_first = [cells[0] for cells in comps]
        # 加速用：classes() 的结果缓存。同一个状态在 BFS 与同格法枚举里会反复出现，
        # 连通性分析是纯函数，缓存不改变任何结果。
        self._cls_cache = {}
        self.adj = [set() for _ in range(self.N)]
        for r in range(self.NR):
            for c in range(self.NC):
                a = lab[r][c]
                for dr, dc in ((0, 1), (1, 0)):
                    nr, nc = r + dr, c + dc
                    if nr < self.NR and nc < self.NC:
                        b = lab[nr][nc]
                        if a != b:
                            self.adj[a].add(b)
                            self.adj[b].add(a)
        self.ti = self.COLORS.index(target)

    # --- 状态工具 -------------------------------------------------
    def classes(self, st):
        """把当前局面按「同色且相邻连通」分组，返回 [tuple(块索引), ...]"""
        hit = self._cls_cache.get(st)
        if hit is not None:
            return hit
        seen = [False] * self.N
        out = []
        for i in range(self.N):
            if seen[i]:
                continue
            col = st[i]
            grp = [i]
            seen[i] = True
            q = deque([i])
            while q:
                v = q.popleft()
                for w in self.adj[v]:
                    if not seen[w] and st[w] == col:
                        seen[w] = True
                        grp.append(w)
                        q.append(w)
            out.append(tuple(sorted(grp)))
        out = tuple(out)
        self._cls_cache[st] = out
        return out

    def expand(self, st):
        """state -> 二维颜色字母网格"""
        g = [["?"] * self.NC for _ in range(self.NR)]
        for i, cells in enumerate(self.comps):
            ch = self.COLORS[st[i]]
            for (y, x) in cells:
                g[y][x] = ch
        return ["".join(row) for row in g]

    def done(self, st):
        return all(v == self.ti for v in st)

    # --- BFS 求最短 ----------------------------------------------
    def bfs(self, limit=6, cap=4_000_000, first_only=False):
        """逐层 BFS + 全局去重（BFS 首次到达即最短，去重安全）。
        剪枝：只有棋盘上当前存在的颜色才值得点（点到场上没有的颜色不可能并块，纯浪费步）。

        limit 之内无解 -> (None, [])。first_only=True 时某层一发现可行解就立刻返回，
        只用于判定「这一层到底有没有解」，不必收全解（验证最短性时用，省下大量展开）。
        """
        if self.done(self.c0):
            return 0, [[[], self.c0]]
        seen = {self.c0}
        frontier = [(self.c0, [])]
        for depth in range(1, limit + 1):
            nxt, sols = [], []
            for st, path in frontier:
                present = sorted(set(st))   # 场上当前存在的颜色
                for grp in self.classes(st):
                    cur = st[grp[0]]
                    tap = min(self.comp_first[i] for i in grp)
                    for c in present:
                        if c == cur:
                            continue
                        ns = list(st)
                        for i in grp:
                            ns[i] = c
                        ns = tuple(ns)
                        np_ = path + [(tap, c)]
                        if self.done(ns):
                            sols.append(np_)
                            if first_only:
                                return depth, sols
                            continue
                        if ns in seen:
                            continue
                        seen.add(ns)
                        nxt.append((ns, np_))
                        if len(seen) > cap:
                            return None, []
            if sols:
                return depth, sols
            if not nxt:
                break
            frontier = nxt
        return None, []

    # --- 「一直点同一格」 -----------------------------------------
    def _fixed_exact(self, ci, L):
        """枚举「一直点块 ci，恰好 L 步」的全部可行颜色序列。

        两处**严格等价**的剪枝（和 crosscheck.py 里的一致，不改变结论）：
          首色 == 起始色 -> 第 1 步就是空操作；
          相邻两步同色   -> 下一步该格已经是前一颜色，必空操作。
        所以序列执行过程中永远不会出现空操作，无需再判 ok。
        """
        out = []
        nc = len(self.COLORS)
        start = self.c0[ci]
        for seq in itertools.product(range(nc), repeat=L):
            if seq[0] == start:
                continue
            if any(seq[i] == seq[i + 1] for i in range(L - 1)):
                continue
            st = self.c0
            frames, sizes = [], []
            for c in seq:
                grp = next(g for g in self.classes(st) if ci in g)
                ns = list(st)
                for i in grp:
                    ns[i] = c
                st = tuple(ns)
                frames.append(st)
                sizes.append(sum(len(self.comps[i]) for i in grp))
            if self.done(st):
                out.append((seq, frames, sizes))
        return out

    def fixed_all(self, maxlen=6):
        """分层求「一直点同一格」的最短步数。

        逐层推进：L=1 试完所有块，再 L=2……一旦某层出现解，它就是同格法最短，
        不必再枚举更深（原实现是每个块各枚举到 maxlen，白跑很多）。
        返回 (L, {块索引: [解, ...]})。
        """
        for L in range(1, maxlen + 1):
            found = {}
            for ci in range(self.N):
                ss = self._fixed_exact(ci, L)
                if ss:
                    found[ci] = ss
            if found:
                return L, found
        return None, {}

    # --- 渲染 -----------------------------------------------------
    def render(self, ci, seq, frames, sizes, out_dir):
        CW, CH = 62, 62
        try:
            ft = ImageFont.truetype(FONT, 26)
            f = ImageFont.truetype(FONT, 22)
            fs = ImageFont.truetype(FONT, 17)
        except Exception:
            ft = f = fs = None
        snaps = [self.c0] + list(frames)
        W = (CW * self.NC + 26) * len(snaps) + 40
        H = CH * self.NR + 26 + 150
        canvas = Image.new("RGB", (W, H), (30, 32, 38))
        d = ImageDraw.Draw(canvas)
        tap = min(self.comps[ci])
        if ft:
            d.text((20, 14), "一直点第%d行第%d列那一格（黑圈处），依次用：%s"
                   % (tap[0] + 1, tap[1] + 1,
                      " → ".join(NAMES.get(self.COLORS[c], self.COLORS[c]) for c in seq)),
                   font=ft, fill=(240, 240, 240))
            d.text((20, 50), "目标：全盘变%s   共 %d 步"
                   % (NAMES.get(self.TARGET, self.TARGET), len(seq)),
                   font=f, fill=(120, 235, 150))
        x, y0 = 20, 92
        for k, st in enumerate(snaps):
            g = self.expand(st)
            for r in range(self.NR):
                for c in range(self.NC):
                    px0, py0 = x + c * CW, y0 + r * CH
                    d.rectangle([px0, py0, px0 + CW - 3, py0 + CH - 3],
                                fill=PAL.get(g[r][c], (128, 128, 128)), outline=(255, 255, 255))
            d.rectangle([x - 3, y0 - 3, x + CW * self.NC, y0 + CH * self.NR],
                        outline=(90, 94, 106))
            px0, py0 = x + tap[1] * CW, y0 + tap[0] * CH
            cx, cy = px0 + CW // 2 - 1, py0 + CH // 2 - 1
            d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(20, 20, 20), width=3)
            if fs:
                if k == 0:
                    cap = "初始"
                else:
                    cap = "第%d步 画%s(%d格)" % (
                        k, NAMES.get(self.COLORS[seq[k - 1]], self.COLORS[seq[k - 1]]), sizes[k - 1])
                d.text((x, y0 + CH * self.NR + 6), cap, font=fs, fill=(200, 205, 215))
            x += CW * self.NC + 26
        path = os.path.join(out_dir, "solve_route.png")
        canvas.save(path)
        return path


# ---------------------------------------------------------------- 推荐路线
def group_by_seq(m, good, colors):
    """按「颜色顺序」聚合可通关的初始块，返回 {顺序文本: [块索引, ...]}"""
    seqs = {}
    for ci, (seq, _fr, _sz) in good:
        key = " → ".join(NAMES.get(colors[c], colors[c]) for c in seq)
        seqs.setdefault(key, []).append(ci)
    return seqs


def recommend(m, good, colors):
    """从同格法可行解里挑一条最宽容的推荐路线。

    打分（依次比较，前者相同时才看后者）：
      1. 可用点击格数 —— 越多越宽容，用户点错一格也能成；
      2. 末步区域大小 —— 越大说明被卷进来的格子越多，剩下"没被染到"的越少；
      3. 最小单步增量 —— 越大越好，避免出现「某一步几乎没长大」的走法
         （第 8 关两条 12 格路线就是靠这条分开的：一条 11→20→22→46→60
         第 3 步只长 2 格，另一条 12→26→35→49→61 每步都实打实地涨）。
    这三维都相同时取 good 里的第一条（构造顺序固定，所以结果稳定可复现）。

    返回 (ci, seq, frames, sizes, best_key)；good 为空时返回 None。

    抽成模块级函数是为了 pipeline.py 复用同一套挑选规则 —— 两边各写一份必然漂移。
    """
    if not good:
        return None
    seqs = group_by_seq(m, good, colors)

    def n_cells_of_seq(k):
        return len({c for ci in set(seqs[k]) for c in m.comps[ci]})

    def key_of(item):
        ci, (sq, _fr, sz) = item
        k = " → ".join(NAMES.get(colors[c], colors[c]) for c in sq)
        growth = [sz[0]] + [sz[i] - sz[i - 1] for i in range(1, len(sz))]
        return (n_cells_of_seq(k), sz[-1], min(growth))

    ci, rec = max(good, key=key_of)
    seq, frames, sizes = rec
    best_key = " → ".join(NAMES.get(colors[c], colors[c]) for c in seq)
    return ci, seq, frames, sizes, best_key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--colors", default=None)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--full", action="store_true",
                    help="完整 BFS 并列出全部最短解（慢）。默认走快路径："
                         "同格法求最短 + BFS 只穷举到该步数-1 层证明最优")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    # utf-8-sig：Windows PowerShell 的 Set-Content -Encoding UTF8 会写 BOM，
    # 用 utf-8 读会把 BOM 留在第一格，导致棋盘少一格、颜色对不上（本项目踩过）。
    with open(a.board, encoding="utf-8-sig") as f:
        ls = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if len(ls) < 2:
        raise SystemExit("棋盘文件至少要有 1 行棋盘 + 1 行目标色")
    target = ls[-1]
    grid = ls[:-1]
    if len(set(len(r) for r in grid)) != 1:
        raise SystemExit("棋盘各行长度不一致：%s（检查是否有 BOM、空行或多余字符）"
                         % [len(r) for r in grid])
    colors = a.colors or "".join(dict.fromkeys("".join(grid)))
    bad = sorted(set("".join(grid) + target) - set(colors))
    if bad:
        raise SystemExit("棋盘里出现了 --colors 里没有的颜色 %s，请补进 --colors" % bad)

    m = Model(grid, target, colors)
    rep = []
    rep.append("棋盘 %d 列 x %d 行 = %d 格；可用色 %s；目标 %s"
               % (m.NC, m.NR, m.NR * m.NC, colors, target))
    rep.append("初始连通块 %d 个（按格子数降序）：" % m.N)
    for i, cells in sorted(enumerate(m.comps), key=lambda t: -len(t[1])):
        rep.append("   块%2d 色%s %2d 格  代表格(第%d行第%d列)"
                   % (i, grid[cells[0][0]][cells[0][1]], len(cells),
                      cells[0][0] + 1, cells[0][1] + 1))
    bad = sum(1 for i in range(m.N) if m.c0[i] != m.ti)
    rep.append("初始非目标色块 = %d 个" % bad)
    rep.append("")

    # ---- ① 先求「一直点同一格」最短步数（便宜：分层枚举，一到 L 就停）----
    Lf, by_comp = m.fixed_all(a.max_depth)

    # ---- ② 再证明它最优：只穷举到 Lf-1 层，确认没有更短的走法 ----
    # 这一步是关键提速：原实现一路 BFS 到 max_depth，最贵的一层（最深那层状态最多）
    # 完全是为了"找解"；而我们已经有解了，只需要排除更短的解。
    if a.full or Lf is None:
        d, sols = m.bfs(a.max_depth)
        rep.append("最短步数 = %s" % d)
        rep.append("最短解共 %d 条" % len(sols))
        for i, s in enumerate(sols[:40], 1):
            rep.append("   解%d: %s" % (i, " -> ".join(
                "%s@(第%d行第%d列)" % (NAMES.get(colors[c], colors[c]), t[0] + 1, t[1] + 1)
                for t, c in s)))
    elif Lf <= 1:
        d, sols = Lf, []
        rep.append("最短步数 = %d（初始局面 1 步即可全盘变%s）" % (Lf, NAMES.get(target, target)))
    else:
        d_short, _ = m.bfs(Lf - 1, first_only=True)
        if d_short is None:
            d, sols = Lf, []
            rep.append("最短步数 = %d" % Lf)
            rep.append("  最短性证明：同格法（一直点同一格）给出 %d 步解；"
                       "另用 BFS 穷举 ≤ %d 步的全部走法，均不能通关。" % (Lf, Lf - 1))
        else:
            d, sols = d_short, []
            rep.append("最短步数 = %d（BFS 得出）" % d_short)
            rep.append("  注意：BFS 在第 %d 步就找到了解，比同格法（%d 步）更短，"
                       "同格法不是最优。" % (d_short, Lf))
    rep.append("")

    good = []
    working_comps = set()
    if Lf is not None and Lf == d:
        for ci, ss in by_comp.items():
            working_comps.add(ci)
            for s in ss:            # 同一个格可能有多种颜色顺序都成立，必须全收
                good.append((ci, s))
    elif Lf is None:
        # 同格法在 max_depth 内无解，退回逐个块试：看恰好等于全局最短 d 步时有没有同格法解
        for ci in range(m.N):
            ss = m._fixed_exact(ci, d) if d else []
            if ss:
                working_comps.add(ci)
                for s in ss:
                    good.append((ci, s))

    n_cells = sum(len(m.comps[ci]) for ci in working_comps)
    rep.append("「一直点同一格」可通关：%d 个初始连通块（= %d 个可点格）能行，步数 = 最短的 %s 步"
               % (len(working_comps), n_cells, Lf if Lf is not None else d))
    seqs = group_by_seq(m, good, colors)
    for key in sorted(seqs, key=lambda k: -len(set(seqs[k]))):
        comps_of_seq = sorted(set(seqs[key]))
        cells = sorted(c for ci in comps_of_seq for c in m.comps[ci])
        rep.append("   颜色顺序 %s ：可用点击格 %d 个（分布在 %d 个初始块）"
                   % (key, len(cells), len(comps_of_seq)))
        rep.append("       " + ", ".join("(第%d行第%d列)" % (r + 1, c + 1) for r, c in cells))
    if working_comps:
        rep.append("   注：同一初始块内的格子完全等价，点块内哪个都行。")
    rep.append("")

    rec = recommend(m, good, colors)
    if rec:
        ci, seq, frames, sizes, best_key = rec
        tap = min(m.comps[ci])
        rep.append("推荐路线：一直点第%d行第%d列，依次 %s（每步染色 %s 格）"
                   % (tap[0] + 1, tap[1] + 1, best_key, "→".join(str(s) for s in sizes)))
        p = m.render(ci, seq, frames, sizes, a.out)
        rep.append("通关过程图 -> %s" % p)
    else:
        if sols:
            rep.append("没找到同格法，从上面的最短解里挑一条（不同步点不同格）")
        else:
            rep.append("没找到同格法；如需全部最短解（不同步点不同格）请加 --full 重跑。")

    with open(os.path.join(a.out, "solve_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print("done")


if __name__ == "__main__":
    main()
