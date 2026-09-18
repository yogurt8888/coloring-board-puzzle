# -*- coding: utf-8 -*-
"""生成 assets/levels/levels.json（已解关卡索引）。

什么时候需要跑：新增/替换了一关，或者改了推荐路线的挑选规则后要同步索引。
它对每一关重新求解一遍，所以索引里的步数/路线永远和求解器当前行为一致 ——
**不要手写这个 JSON**，手写必然和求解器漂移。

用法：
    python tools/build_level_index.py            # 重建全部
    python tools/build_level_index.py --check    # 只校验索引与求解器是否一致
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import render_delivery                                    # noqa: E402
from solve_fast import Model, recommend, group_by_seq     # noqa: E402

ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")
LEVELS = os.path.join(ROOT, "assets", "levels")

#: 游戏给出的步数预算（截图上的「剩余步数」）。改关卡时同步这里。
BUDGET = {1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4,
          7: 4, 8: 5, 9: 4, 10: 4, 11: 5, 12: 5}


def solve_one(level):
    path = os.path.join(EXAMPLES, "board_level%d.txt" % level)
    g, target = render_delivery.read_board(path)
    grid = ["".join(r) for r in g]
    target = target.strip().upper()
    colors = "".join(dict.fromkeys("".join(grid)))
    if target not in colors:
        colors += target

    m = Model(grid, target, colors)
    Lf, by_comp = m.fixed_all(6)
    if Lf is None:
        raise RuntimeError("第 %d 关：同格法在 6 步内无解，索引不支持" % level)
    good = [(ci, s) for ci, ss in by_comp.items() for s in ss]
    ci, seq, _frames, sizes, key = recommend(m, good, colors)
    tap = min(m.comps[ci])
    seq_map = group_by_seq(m, good, colors)
    return {
        "level": level,
        "rows": len(grid),
        "cols": len(grid[0]),
        "grid": "".join(grid),
        "target": target,
        "budget": BUDGET.get(level, Lf),
        "steps": Lf,
        "tap": [tap[0] + 1, tap[1] + 1],          # 1 基，和交付图上的说法一致
        "block_cells": len(m.comps[ci]),
        "seq": "".join(colors[c] for c in seq),
        "sizes": list(sizes),
        "cells_of_seq": len({c for i in set(seq_map[key]) for c in m.comps[i]}),
        "png": "画盘%d_通关路线.png" % level,
    }


def discover_levels():
    """扫 examples/board_level*.txt 决定要建哪些关 —— 加新关只要丢文件，不用改代码。"""
    import glob
    out = []
    for p in glob.glob(os.path.join(EXAMPLES, "board_level*.txt")):
        n = os.path.basename(p)[len("board_level"):-len(".txt")]
        if n.isdigit():
            out.append(int(n))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不写入")
    ap.add_argument("--levels", default=None, help="只处理这几关，如 8,9（默认扫 examples 下全部）")
    a = ap.parse_args()

    want = [int(x) for x in a.levels.split(",")] if a.levels else discover_levels()
    out, bad = {}, []
    for lv in want:
        try:
            meta = solve_one(lv)
        except Exception as e:
            bad.append("第 %d 关求解失败：%s" % (lv, e))
            continue
        png = os.path.join(LEVELS, meta["png"])
        if not os.path.exists(png):
            bad.append("第 %d 关缺成品图 %s" % (lv, meta["png"]))
        out[str(lv)] = meta
        print("第 %-2s 关  目标%s  %s 步  点第%d行第%d列  %s  %s"
              % (lv, meta["target"], meta["steps"], meta["tap"][0], meta["tap"][1],
                 "→".join(meta["seq"]), "→".join(str(s) for s in meta["sizes"])))

    if a.check:
        cur = json.load(open(os.path.join(LEVELS, "levels.json"), encoding="utf-8"))
        same = all(cur.get("levels", {}).get(k) == v for k, v in out.items())
        print("\n索引与求解器%s" % ("一致" if same else "不一致（需重建）"))
        return 0 if same and not bad else 1

    # 版本号 +1：装过 skill 的人靠它判断「远端有更新」。
    # 只给 --levels 时不能把其它关抹掉，所以以旧索引为基础合并。
    old = {}
    try:
        with open(os.path.join(LEVELS, "levels.json"), encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        pass
    levels = dict(old.get("levels", {}))
    levels.update(out)
    data = {
        "version": int(old.get("version", 0)) + 1,
        "updated": time.strftime("%Y-%m-%d"),
        "levels": levels,
    }
    with open(os.path.join(LEVELS, "levels.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("\n写入 %s（本次 %d 关，索引共 %d 关，version %d）"
          % (os.path.join(LEVELS, "levels.json"), len(out), len(levels), data["version"]))
    print("提示：git commit + push 之后，装过 skill 的人下次问新关号时会自动同步到这份索引。")
    for b in bad:
        print("  ! " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
