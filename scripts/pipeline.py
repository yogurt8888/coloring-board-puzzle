# -*- coding: utf-8 -*-
"""画盘求解交付流水线 —— 一条命令从截图跑到「交付图 + 一页简报」。

为什么有它：
  原流程要依次跑 5 个脚本，每跑一条都得等下一条的输出来决定下一步，单关光"等结果"就要
  6~8 轮往返；实测脚本本身合计才 20 秒，剩下 4~9 分钟全花在往返上。
  把整条链路并成一次调用后，单关交付从 5~10 分钟压到 1~2 分钟。

做什么（顺序固定，任一步失败即中止并写明卡在哪）：
  1. 标定 + 逐格取色（截图模式）或直接读棋盘文件
  2. 求解：「一直点同一格」最短步数（分层枚举，一到 L 就停）
  3. 证明最短：BFS 只穷举到 L-1 层，确认没有更短的走法
  4. 独立复核：crosscheck 用另一套格子级实现在算一遍，两边必须对得上
  5. 出交付图：render_delivery 统一版式
  6. 成品反查：从 PNG 逐帧逐格取色 + 校验圈

用法（--img 与 --board 二选一）：
  python pipeline.py --img 截图.png --level 13 --target B --budget 5 --out <目录>
  python pipeline.py --board board13.txt --level 13 --target B --budget 5 --out <目录>

产出：
  <out>/画盘<level>_通关路线.png        交付物（只交这一张）
  <work>/pipeline_summary.txt          一页结论（推荐路线/三道校验/耗时）
  <work>/board<level>.txt              取色得到的棋盘（可留档复用）
  <work>/grid_recon.png                原图 vs 重建对照（内部核对用）
"""
import argparse
import os
import shutil
import sys
import time

# 中文一律按 utf-8 输出，避免控制台代码页不是 936 时 print 直接抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import board_tool                                    # noqa: E402
import render_delivery                               # noqa: E402
import level_index                                   # noqa: E402
from solve_fast import Model, recommend, group_by_seq, NAMES       # noqa: E402
from crosscheck import solve_same_cell               # noqa: E402
from verify_render import verify                     # noqa: E402
from PIL import Image                                # noqa: E402


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _timing(T):
    return "  ".join("%s %.2fs" % (k, v) for k, v in T) + \
           "  | 合计 %.2fs" % sum(v for _, v in T)


def _meta_lines(meta, budget=None):
    """把索引里的一关元数据显示成简报那几行（和求解出来的写法保持一致）。"""
    steps, bud = meta["steps"], budget if budget is not None else meta.get("budget")
    if bud is None:
        budtxt = ""
    elif bud == steps:
        budtxt = "（刚好用满）"
    elif bud > steps:
        budtxt = "（富余 %d 步）" % (bud - steps)
    else:
        budtxt = "（预算 %d 步 < 最短 %d 步，这关不可能通关）" % (bud, steps)
    out = ["  目标色：%s(%s)   最短 %d 步   预算 %s 步 %s"
           % (NAMES.get(meta["target"], meta["target"]), meta["target"],
              steps, bud, budtxt),
           "  推荐打法：一直点【第%d行第%d列】这一格（该初始连通块共 %d 格，块内点哪个都一样）"
           % (meta["tap"][0], meta["tap"][1], meta["block_cells"]),
           "  颜色顺序：%s" % " → ".join(
               NAMES.get(c, c) for c in meta["seq"]),
           "  每步染色：%s 格" % " → ".join(str(s) for s in meta["sizes"])]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", help="游戏截图")
    ap.add_argument("--board", help="已有棋盘文件（与 --img 二选一）")
    ap.add_argument("--level", default=None, help="关卡号，用于文件名与标题")
    ap.add_argument("--target", default=None,
                    help="目标色字母，如 B；截图模式必填，只给 --level 时从索引取")
    ap.add_argument("--budget", type=int, default=None, help="游戏显示的剩余步数")
    ap.add_argument("--out", default=".", help="交付图输出目录")
    ap.add_argument("--work", default=None, help="中间产物目录（默认 <out>/_pipeline/h<level>）")
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--cols", type=int, default=None, choices=[2, 3],
                    help="交付图的面板列数（默认：步数<=4 用 2 列，>=5 用 3 列）")
    ap.add_argument("--expect-cols", type=int, default=None,
                    help="棋盘应有的列数，给了就强校验（防标定偏行/偏列）")
    ap.add_argument("--expect-rows", type=int, default=None,
                    help="棋盘应有的行数，给了就强校验")
    ap.add_argument("--sub", default=None, help="交付图副标题（一句话心法）")
    ap.add_argument("--foot", default=None,
                    help="交付图底部补充说明；默认不画（用户已要求去掉那行，平时别传）")
    ap.add_argument("--no-cache", action="store_true",
                    help="禁用「已解关卡直接复用」，强制重新求解")
    ap.add_argument("--list-levels", action="store_true",
                    help="列出索引里已解好的关卡，然后退出")
    ap.add_argument("--sync-levels", action="store_true",
                    help="强制拉一次远端最新关卡索引 + 缺失的成品图，然后列出全部已解关卡并退出")
    ap.add_argument("--no-sync", action="store_true",
                    help="不联网同步远端关卡（默认：本地查不到该关时会联网取一次）")
    a = ap.parse_args()

    if a.no_sync:
        os.environ["CB_OFFLINE"] = "1"

    if a.list_levels:
        print("\n".join(level_index.levels_summary()) or "（索引为空）")
        return 0

    if a.sync_levels:
        log = []
        st, why = level_index.sync_remote(force=True, log=log)
        print("远端同步：%s" % why)
        for l in log:
            print("  " + l)
        print("")
        print("\n".join(level_index.levels_summary()) or "（索引为空）")
        return 0 if st in ("updated", "nochange") else 1

    if not a.level:
        raise SystemExit("必须给 --level（或 --list-levels / --sync-levels）")

    # 联网同步一次远端关卡（作者推了第 13 关之类的情况）。
    # 只在本地查不到时触发，失败静默降级：断网也要能照常求解。
    sync_note = None          # 同步成功 -> 写进简报的来源说明
    sync_why = None           # 最近一次尝试的结果（含失败原因），查不到关时打给用户看

    if a.img and a.board:
        raise SystemExit("--img 与 --board 只能给一个")
    if not a.img and not a.board and not a.level:
        raise SystemExit("必须给 --img/--board 之一，或只给 --level 查已解关卡")
    target = (a.target or "").strip().upper()
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work or os.path.join(out, "_pipeline", "h%s" % a.level))
    os.makedirs(out, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    sum_path = os.path.join(work, "pipeline_summary.txt")

    T, brief = [], []
    brief.append("画盘 %s 关 交付简报" % a.level)
    brief.append("=" * 68)

    def abort(stage, detail):
        brief.append("")
        brief.append("交付中止：%s" % stage)
        brief.append("-" * 68)
        brief.extend(detail)
        brief.append("")
        brief.append("耗时：" + _timing(T))
        _write(sum_path, brief)
        print("FAIL: %s -> %s" % (stage, sum_path))
        return 1

    # ---------------- 0) 只给了 --level：直接查已解关卡索引 ----------------
    # 用户说「第 8 关怎么过」却没发图时走这里，不跑任何求解。
    if not a.img and not a.board:
        meta = level_index.by_level(a.level)
        if not meta:
            # 本地没有 -> 试一次远端（作者可能在 GitHub 上更新了新关卡）
            st, why = level_index.sync_remote(level=a.level)
            sync_why = why
            if st == "updated":
                sync_note = why
                meta = level_index.by_level(a.level)
        if not meta:
            have = sorted(level_index.load().get("levels", {}), key=int)
            print("FAIL: 索引里没有第 %s 关；已解关卡：%s"
                  % (a.level, ", ".join(have) or "（空）"))
            if sync_why:
                print("远端同步：%s" % sync_why)
            print("提示：发一张截图，或先跑 tools/build_level_index.py 建索引。")
            return 1
        src_png = level_index.png_path(meta)
        if not src_png:
            print("FAIL: 第 %s 关的成品图不在 assets/levels/ 下：%s"
                  % (a.level, meta.get("png")))
            return 1
        t0 = time.perf_counter()
        dst = os.path.join(out, "画盘%s_通关路线.png" % a.level)
        shutil.copy(src_png, dst)
        T.append(("查索引/取图", time.perf_counter() - t0))
        brief.append("")
        brief.append("结论（已解存档直接取用，未重算）")
        brief.append("-" * 68)
        brief.extend(_meta_lines(meta, a.budget))
        brief.append("")
        brief.append("交付物")
        brief.append("  交付图：%s" % dst)
        brief.append("  来源：  assets/levels/%s" % meta["png"])
        if sync_note:
            brief.append("  索引更新：%s（本次从远端同步，已写回本地）" % sync_note)
        brief.append("")
        brief.append("耗时：" + _timing(T))
        _write(sum_path, brief)
        print("OK(索引命中): %s -> %s" % (a.level, dst))
        return 0

    # ---------------- 1) 标定 + 取色 ----------------
    t0 = time.perf_counter()
    if a.img:
        if not target:
            return abort("截图模式必须给 --target",
                         ["目标色只能从截图上读（棋盘顶部的提示），脚本猜不出来",
                          "例：--target B"])
        if not os.path.exists(a.img):
            return abort("截图不存在", [a.img])
        img = Image.open(a.img).convert("RGB")
        log = []
        cal = board_tool.auto_calibrate(img, verbose=log)
        if not cal:
            return abort("自动标定失败", log +
                         ["", "请用 board_tool.py scan 手工标定后，改用 --board 传入棋盘文件。"])
        grid, unknown = board_tool.extract(img, cal, work, tag="  (pipeline)")
        if unknown:
            return abort("取色不干净：%d 格没能归类" % unknown,
                         log + ["", "标定可能偏了，看 %s/grid_recon.png 对比原图与重建。" % work])
        src = "截图自动标定（x0=%.1f px=%.2f y0=%.1f py=%.2f %dx%d）" % (
            cal["x0"], cal["px"], cal["y0"], cal["py"], cal["cols"], cal["rows"])
    else:
        if not os.path.exists(a.board):
            return abort("棋盘文件不存在", [a.board])
        g, _tgt = render_delivery.read_board(a.board)
        grid, unknown = ["".join(r) for r in g], 0
        if not target and _tgt:            # 棋盘文件末行就是目标色，没传就取它
            target = str(_tgt).strip().upper()
        src = "棋盘文件 %s" % a.board
    T.append(("标定/取色", time.perf_counter() - t0))

    # 落一份棋盘文件：utf-8 无 BOM，solve_fast / crosscheck 用 utf-8-sig 读都兼容
    board_path = os.path.join(work, "board%s.txt" % a.level)
    _write(board_path, list(grid) + [target])

    colors = "".join(dict.fromkeys("".join(grid)))
    if target not in colors:
        colors += target          # 目标色可能不在初始盘面里
    NR, NC = len(grid), len(grid[0])

    # 网格强校验：标定偏一行/一列时后续全部取色都会错，但流程不会自己报错
    if a.expect_cols or a.expect_rows:
        bad = []
        if a.expect_cols and NC != a.expect_cols:
            bad.append("列数 %d != 预期 %d" % (NC, a.expect_cols))
        if a.expect_rows and NR != a.expect_rows:
            bad.append("行数 %d != 预期 %d" % (NR, a.expect_rows))
        if bad:
            return abort("棋盘网格与预期不符（标定很可能偏了）",
                         bad + ["截图模式下看 %s/grid_recon.png：左原图右重建，一比就知道偏在哪"
                                % work,
                                "若确认游戏棋盘确实是 %sx%s，可去掉 --expect-cols/--expect-rows"
                                % (a.expect_cols or "?", a.expect_rows or "?")])

    # ---------------- 1.5) 命中已解关卡 -> 直接复用成品图 ----------------
    # 只认 63 格逐格相同 + 目标色相同，差一格都不复用：这类关卡长得像的太多，
    # 拿别的关的答案冒充是最难被发现的错。宁可重算（也就 1~3 秒）。
    if not a.no_cache:
        hit, meta, note = level_index.match(grid, target or None)
        if not hit:
            # 本地没匹配上，先联网补一次最新关卡再比一次（别人可能已经在远端解过这关）
            st, why = level_index.sync_remote()
            if st == "updated":
                sync_note = why
                hit, meta, note = level_index.match(grid, target or None)
        if note:
            brief.append("  " + note)
        if hit:
            src_png = level_index.png_path(meta)
            if src_png:
                t0 = time.perf_counter()
                name = "画盘%s_通关路线.png" % a.level
                dst = os.path.join(out, name)
                shutil.copy(src_png, dst)
                T.append(("查索引/复用", time.perf_counter() - t0))
                brief.append("")
                brief.append("结论：棋盘与已解的第 %d 关逐格一致（%d 格，目标色同为%s）"
                             " -> 直接复用成品图，未重算"
                             % (hit, sum(len(r) for r in grid),
                                NAMES.get(target, target)))
                brief.append("-" * 68)
                brief.extend(_meta_lines(meta, a.budget))
                if str(hit) != str(a.level):
                    brief.append("")
                    brief.append("  注意：你标的是第 %s 关，但棋盘和第 %d 关完全一样 —— "
                                 "以棋盘为准，输出文件名仍按你标的号。" % (a.level, hit))
                brief.append("")
                brief.append("交付物")
                brief.append("  交付图：%s" % dst)
                brief.append("  来源：  assets/levels/%s" % meta["png"])
                if sync_note:
                    brief.append("  索引更新：%s（本次从远端取到，已写回本地）" % sync_note)
                brief.append("")
                brief.append("棋盘来源：" + src)
                brief.append("耗时：" + _timing(T))
                _write(sum_path, brief)
                print("OK(索引命中 第%s关): %s" % (hit, dst))
                return 0

    # ---------------- 2) 求解 + 3) 最短性证明 ----------------
    t0 = time.perf_counter()
    m = Model(grid, target, colors)
    Lf, by_comp = m.fixed_all(a.max_depth)
    if Lf is None:
        return abort("「一直点同一格」在 %d 步内无解" % a.max_depth,
                     ["本关需要不同步点不同格的走法，pipeline 不覆盖这种情况",
                      "请跑：solve_fast.py --board %s --full" % board_path])
    if Lf <= 1:
        d_short, proof = None, "初始局面 1 步即可全盘变%s" % NAMES.get(target, target)
    else:
        d_short, _ = m.bfs(Lf - 1, first_only=True)
        proof = ("BFS 穷举 ≤%d 步的全部走法，均不能通关 -> %d 步即最短"
                 % (Lf - 1, Lf)) if d_short is None else \
                ("BFS 在第 %d 步就找到解，比同格法(%d 步)更短，同格法不是最优" % (d_short, Lf))
    if d_short is not None:
        return abort("同格法不是最优解", [proof, "请跑 --full 取 BFS 的通用最短解"])
    T.append(("求解", time.perf_counter() - t0))

    good = []
    for ci, ss in by_comp.items():
        for s in ss:
            good.append((ci, s))
    n_cells = sum(len(m.comps[ci]) for ci in by_comp)

    # ---------------- 4) 独立复核 ----------------
    t0 = time.perf_counter()
    best_cc, found_cc = solve_same_cell(grid, target, colors, a.max_depth)
    n_cells_cc = len({it[0] for it in found_cc.get(best_cc, [])}) if best_cc else 0
    T.append(("独立复核", time.perf_counter() - t0))

    cc_ok = (best_cc == Lf and n_cells_cc == n_cells)
    if not cc_ok:
        return abort("两套实现对不上（不能交付）",
                     ["solve_fast : %s 步 / %d 个可点格" % (Lf, n_cells),
                      "crosscheck : %s 步 / %d 个可点格" % (best_cc, n_cells_cc),
                      "这是本项目最危险的失败模式，必须先查清再交付。"])

    # ---------------- 推荐路线 ----------------
    ci, seq, frames, sizes, best_key = recommend(m, good, colors)
    tap = min(m.comps[ci])                        # 0 基
    tap1 = (tap[0] + 1, tap[1] + 1)
    seq_str = "".join(colors[c] for c in seq)
    blk_cells = len(m.comps[ci])
    # 本条颜色顺序下可用于起手的格子数（复用同一套聚合规则，避免两处口径漂移）
    seqs_map = group_by_seq(m, good, colors)
    n_seq_cells = len({c for i2 in set(seqs_map[best_key]) for c in m.comps[i2]})

    # ---------------- 5) 出交付图 ----------------
    t0 = time.perf_counter()
    name = "画盘%s_通关路线.png" % a.level
    spec = dict(
        grid=[list(r) for r in grid], target=target,
        tap=tap, seq=seq_str,
        level=a.level, budget=a.budget, out=out, name=name,
        cols=a.cols,
        tag="画盘-%s" % a.level,
        sub=a.sub or "先把多块染成同色合并成一片，最后一步整片染成【%s】"
                     % render_delivery.NAMES.get(target, target),
        foot=a.foot,
        caps=None, notes=None, same_cell=True,
    )
    png, final_ok, step_sizes = render_delivery.render(spec)
    T.append(("出图", time.perf_counter() - t0))
    if not final_ok:
        return abort("出图后终局校验失败（渲染出的盘面没通关）", ["渲染路径 %s" % png])

    # ---------------- 6) 成品反查 ----------------
    t0 = time.perf_counter()
    ok_v, vlines = verify(png, [list(r) for r in grid], target, tap1, seq_str, a.cols)
    T.append(("反查", time.perf_counter() - t0))
    if not ok_v:
        return abort("成品反查 FAIL（画出来的和算出来的不一致）", vlines)

    # ---------------- 简报 ----------------
    if a.budget is None:
        bud = ""
    elif a.budget == Lf:
        bud = "刚好用满"
    elif a.budget > Lf:
        bud = "富余 %d 步" % (a.budget - Lf)
    else:
        bud = "!! 超出预算 %d 步" % (Lf - a.budget)

    brief.append("结论")
    brief.append("  目标色：%s(%s)      最短步数：%d 步%s"
                 % (NAMES.get(target, target), target, Lf,
                    ("      游戏预算：%d 步（%s）" % (a.budget, bud)) if a.budget else ""))
    brief.append("  推荐打法：一直点【第%d行第%d列】这一格"
                 "（该初始连通块共 %d 格，块内点哪个都一样）"
                 % (tap1[0], tap1[1], blk_cells))
    brief.append("  颜色顺序：%s" % best_key)
    brief.append("  每步染色：%s 格" % " → ".join(str(s) for s in step_sizes))
    brief.append("  宽容度：本关共有 %d 个可点格（分布在 %d 个初始连通块）；"
                 "本条颜色顺序下 %d 个" % (n_cells, len(by_comp), n_seq_cells))
    brief.append("")
    brief.append("校验（三道，缺一不可）")
    brief.append("  [1] 双实现对账：solve_fast 与 crosscheck 均为 %d 步 / %d 个可点格 -- 一致"
                 % (Lf, n_cells))
    brief.append("  [2] 最短性证明：%s" % proof)
    brief.append("  [3] 成品反查：PASS -- %d 帧盘面逐格一致，圈色/圈心全部 OK" % len(step_sizes))
    brief.append("  取色质量：%d/%d 格全部归类成功" % (NR * NC - unknown, NR * NC))
    brief.append("")
    brief.append("交付物")
    brief.append("  交付图：%s" % png)
    brief.append("  棋盘：  %s" % board_path)
    brief.append("  中间件：%s" % work)
    brief.append("")
    brief.append("棋盘来源：%s" % src)
    brief.append("耗时：" + _timing(T))
    _write(sum_path, brief)
    print("ok -> %s" % sum_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
