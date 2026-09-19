# -*- coding: utf-8 -*-
"""把某一关推荐路线的每一步拆开看：这一步把哪几片（原始连通块）并了进来、各多少格。

为什么需要它：写 SKILL.md 的关卡详解（"第 2 步够到三片黄…"）时，片数/格数/坐标**必须现算**，
肉眼数格子或凭印象写必然出错 —— 本项目就发生过一次（第 13 关第 4 步漏报 2 格）。
这里的 tap / seq 直接取自 `assets/levels/levels.json`，与求解器同源。

用法：
    python tools/step_detail.py 13 14        # 指定关卡号，可多个
    python tools/step_detail.py --all        # 全部关卡（输出很长）

读法：
    「动手时区域 N 格」= 这一步点击时被染的那块区域有多大（= 简报里的「每步染色」）；
    「并入 1 片X k 格」= 刷完色之后，因为同色而与区域连通、被并进区域的原始色块。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from solve_fast import Model, NAMES  # noqa: E402


def analyze(meta):
    cols = meta["cols"]
    flat = meta["grid"]
    grid = [flat[i:i + cols] for i in range(0, len(flat), cols)]
    target = meta["target"]
    colors = "".join(dict.fromkeys("".join(grid)))
    if target not in colors:
        colors += target
    m = Model(grid, target, colors)

    r, c = meta["tap"][0] - 1, meta["tap"][1] - 1
    ci = m.lab[r][c]
    blk = sorted((y + 1, x + 1) for y, x in m.comps[ci])
    print("=" * 74)
    print("第 %s 关  目标 %s(%s)  最短 %s 步 / 预算 %s 步"
          % (meta["level"], NAMES.get(target, target), target,
             meta.get("steps"), meta.get("budget")))
    print("  起点【第%d行第%d列】所在块 %d 格: %s"
          % (meta["tap"][0], meta["tap"][1], len(blk), blk))
    print("  初始连通块 %d 个；本条颜色顺序下可用起点 %s 个（起点块 %d 格）"
          % (m.N, meta.get("cells_of_seq"), len(blk)))

    st = m.c0
    for step, ch in enumerate(meta["seq"], 1):
        grp_before = next(g for g in m.classes(st) if ci in g)
        size_before = sum(len(m.comps[i]) for i in grp_before)
        newc = colors.index(ch)
        ns = list(st)
        for i in grp_before:
            ns[i] = newc
        ns = tuple(ns)
        grp_after = next(g for g in m.classes(ns) if ci in g)
        size_after = sum(len(m.comps[i]) for i in grp_after)
        added = sorted(set(grp_after) - set(grp_before))
        print("  第 %d 步 选【%s】：动手时区域 %d 格（本步染这 %d 格）-> 并片后 %d 格"
              % (step, NAMES.get(ch, ch), size_before, size_before, size_after))
        if not added:
            print("      （本步没有并片，只是把区域刷成了新颜色）")
        for i in added:
            cells = sorted((y + 1, x + 1) for y, x in m.comps[i])
            print("      并入 1 片%s %d 格: %s"
                  % (NAMES.get(colors[ns[i]], colors[ns[i]]), len(cells), cells))
        st = ns
    cells_final = sum(len(m.comps[i]) for i in range(m.N))
    assert size_after == cells_final, "终局不是全盘一色，出错了"
    print("  终局：全盘 %d 格变%s" % (cells_final, NAMES.get(target, target)))

    # 还有哪些起点块能走出「同格法」最优解（供写文档时说明"宽容度"）
    m2 = Model(grid, target, colors)
    Lf, by_comp = m2.fixed_all(6)
    print("  最短 %d 步；可用的起点块 %d 个：" % (Lf, len(by_comp)))
    for ci2, seqs in sorted(by_comp.items(), key=lambda kv: m2.comp_first[kv[0]]):
        cells = sorted((y + 1, x + 1) for y, x in m2.comps[ci2])
        # by_comp[ci] 的每一项是 (seq, frames, sizes) 三元组，seq 才是颜色索引序列
        shown = "、".join("".join(NAMES.get(colors[c], colors[c]) for c in item[0])
                          for item in seqs[:2])
        more = "" if len(seqs) <= 2 else "…（共 %d 条）" % len(seqs)
        print("    块 %d 格 %s%s｜可行顺序: %s%s"
              % (len(cells), cells, " ←推荐" if ci2 == ci else "", shown, more))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    idx = json.load(open(os.path.join(ROOT, "assets", "levels", "levels.json"),
                         encoding="utf-8"))
    levels = sorted(idx["levels"], key=int) if "--all" in sys.argv or not args else args
    for lv in levels:
        analyze(idx["levels"][lv])


if __name__ == "__main__":
    main()
