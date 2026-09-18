#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画盘棋盘取色工具

子命令:
  auto    --img <截图> --out <目录>
          自动标定格线 + 逐格取色 + 输出重建复核图（首选）
  scan    --img <截图> --out <目录> [--y 580 ...] [--x 1080 ...]
          沿行/列做游程扫描，自动标定不准时用来人工标定
  extract --img <截图> --x0 .. --px .. --y0 .. --py .. --cols .. --rows .. --out <目录>
          用给定网格参数取色 + 重建复核图

输出（全部写文件）:
  <out>/grid_recon.png   左=原图裁剪放大  右=程序重建  ← 必须人眼核对这张
  <out>/grid_report.txt  标定参数 + 颜色矩阵 + 每格平均RGB + 可直接喂给 solve.py 的棋盘行
"""
import argparse
import colorsys
import os
import statistics

from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"


def classify(p):
    r, g, b = [v / 255.0 for v in p]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    deg = h * 360
    if s < 0.10:
        return "?"
    if deg < 25 or deg >= 330:
        return "R"
    if 25 <= deg < 75:
        return "Y"
    if 75 <= deg < 175:
        return "G"
    if 175 <= deg < 260:
        return "B"
    return "?"


PAL = {"R": (250, 140, 122), "Y": (245, 218, 98), "G": (95, 235, 150),
       "B": (167, 210, 252), "?": (128, 128, 128)}


def rle(line_pixels, min_len=6):
    """粗量化游程（cmd_scan 用）"""
    out, prev, start = [], None, 0
    for i, p in enumerate(line_pixels):
        q = (p[0] // 24, p[1] // 24, p[2] // 24)
        if q != prev:
            if prev is not None and i - start >= min_len:
                out.append((start, i - 1, line_pixels[start], i - start))
            prev, start = q, i
    if len(line_pixels) - start >= min_len:
        out.append((start, len(line_pixels) - 1, line_pixels[start], len(line_pixels) - start))
    return out


def flat_runs(line, tol=32, min_len=4):
    """按「与色段起始像素的色差」合并成长色段。

    格子内部有笔触纹理，不能按相邻像素差分段，要跟「本段起始像素」比；
    背景是平滑渐变，会一路合成超长段，交给长度窗口排掉。
    """
    runs, start = [], 0
    for i in range(1, len(line)):
        if max(abs(line[i][k] - line[start][k]) for k in range(3)) > tol:
            if i - start >= min_len:
                runs.append((start, i - 1, line[start], i - start))
            start = i
    if len(line) - start >= min_len:
        runs.append((start, len(line) - 1, line[start], len(line) - start))
    return runs


def _tile_chain(runs, min_run=20, max_run=320, min_chain=4):
    """在一行/一列的游程里找最长的「等宽等距」瓦片链，返回链上的段列表。

    棋盘一行的本质特征是：**一串宽度相近的瓦片色段，起点等间距，段间夹着细缝**。
    这条判据与"缝是什么颜色"无关，因此不受截图底色影响，也不含任何绝对像素窗口
    （老版本写死「段长 58~118px」，换个分辨率就全废）。

    逐段链接的四个约束：
      a) 段本身接近四种瓦片色（_pal_close）、长度在合理区间；
      b) 段间必须有缝（seam > 0）且缝很细（< 0.55 × 起点间距）；
      c) 起点间距 > 前一段长度（两格不可能重叠）；
      d) 与链内已有段的**宽度相近**、且**间距与前几段一致**（±25% / ±35%）。
    任一不满足就断开，换下一个起点重新起链，最后取最长的那条。
    """
    cand = [r for r in runs if min_run <= r[3] <= max_run and _pal_close(r[2])]
    if len(cand) < min_chain:
        return []
    best = []
    for i in range(len(cand)):
        chain = [cand[i]]
        for j in range(i + 1, len(cand)):
            prev, cur = chain[-1], cand[j]
            d = cur[0] - prev[0]
            seam = cur[0] - prev[1] - 1
            if seam <= 0 or seam > 0.55 * d or d <= prev[3] * 1.02:
                break
            med_w = statistics.median([c[3] for c in chain])
            if abs(cur[3] - med_w) > max(12, 0.28 * med_w):
                break
            if len(chain) > 1:
                p = statistics.median([b[0] - a[0] for a, b in zip(chain, chain[1:])])
                if not (0.75 * p <= d <= 1.35 * p):
                    break
            chain.append(cur)
        if len(chain) > len(best):
            best = chain
    return best if len(best) >= min_chain else []


def find_line(img, horizontal, lo, hi, step=2):
    """在一堆扫描线里挑出「瓦片链最长」的那条，返回 (位置, 瓦片链)。

    链的每段是 (起点, 终点, 段色, 段长)，同一行/列上的格子。

    注意：这条判据**只能算是"候选"**——棋盘最后一格的右边是外框而不是缝隙，
    所以最右一列常被漏掉；卡片/画笔面板也可能凑出假链。
    列数/行数必须再用 _count_tile_runs 向外扩展确认，见 auto_calibrate。
    """
    W, H = img.size
    px = img.load()
    best = None
    for t in range(lo, hi, step):
        if horizontal:
            line = [px[x, t] for x in range(W)]
        else:
            line = [px[t, y] for y in range(H)]
        chain = _tile_chain(flat_runs(line))
        if chain and (best is None or len(chain) > len(best[1])):
            best = (t, chain)
    return best


# ---------------------------------------------------------------------------
# 棋盘范围确认：靠「瓦片色连续段计数」判断某一列/行到底在不在棋盘里面
# ---------------------------------------------------------------------------
TILE_COLS = ((250, 140, 122), (245, 218, 98), (95, 235, 150), (167, 210, 252))


def _pal_close(p, thr=40):
    """像素是否接近四种瓦片标准色之一。
    暖色背景实测离最近的瓦片色约 54，白卡片更远，所以 thr=40 能把它们排掉。"""
    return min(sum((p[i] - c[i]) ** 2 for i in range(3)) for c in TILE_COLS) <= thr * thr


def _tile_runs(img, horizontal, fixed, halfw=10, min_run=18):
    """在 fixed 这一条（列/行）上取出「瓦片色段」，返回 [(起点, 终点), ...]。

    真棋盘列 -> 每行一格，得到 rows 段（本项目 7 段）；
    背景 / 白卡片 -> 0 段；立绘角色 / 按钮图标 -> 只有 1~2 段。
    为了抗纹理噪点，垂直于扫描方向取 3 个偏移点，3 个里 2 个算瓦片色才算。

    min_run 这道过滤是必需的：**瓦片内部有一条 1~10px 的竖向高光带**（近白，
    既不像瓦片色也不像缝隙色），会把「一格」切成两三段，缝里也散落若干 1px 杂点。
    第 3 关实测 x=792 处一格被 (784,784) 这 1px 像素切开、缝里还夹着
    (735,737,743,746) 四个 1px 杂点 —— 正是这些东西让"数段数"的判据整条失效。
    """
    W, H = img.size
    px = img.load()
    lim = H if horizontal else W
    runs, run = [], None
    for t in range(lim):
        votes = 0
        for off in (-halfw, 0, halfw):
            if horizontal:
                x, y = fixed + off, t
            else:
                x, y = t, fixed + off
            if 0 <= x < W and 0 <= y < H and _pal_close(px[x, y]):
                votes += 1
        if votes >= 2:
            if run is None:
                run = [t, t]
            else:
                run[1] = t
        else:
            if run is not None:
                runs.append(tuple(run))
                run = None
    if run is not None:
        runs.append(tuple(run))
    return [(a, b) for a, b in runs if b - a + 1 >= min_run]


def _count_tile_runs(img, horizontal, fixed, halfw=10, min_run=18):
    """同 _tile_runs，只返回 (段数, 各段起点)。"""
    runs = _tile_runs(img, horizontal, fixed, halfw, min_run)
    return len(runs), [a for a, _b in runs]


def _is_board_line(img, horizontal, fixed, pitch, min_span=3.2, min_fill=0.75):
    """判定 fixed 这一条是不是真棋盘里的一行/一列。

    做法：把这一条上的瓦片色段用「≤0.45 格距」的间距并起来（缝隙再宽也远不到半格，
    所以这一步恰好把"一格挨一格"并成整条棋盘带），取最长的那条带，再要求：
      a) 带够长（≥ min_span 格）—— 挡住背景/立绘凑出的一小段；
      b) 带里**还能分辨出足够多的格子**（独立段数 ≥ min_fill × 带长/格距）。
        这一条是关键：标题栏、立绘、卡片凑出的"一整块纯色"虽然可能很长，
        但里面分不出格子，会被排掉 —— 第 11/12 关最初就是把上方标题栏误判成棋盘行
        （rows=10、y0 跑到画面外），第 1 关的合成图上标题右侧一段纯色背景也凑过假行。

    判据与"缝隙是什么颜色、有多宽"完全无关：实测第 1~3 关的缝是米色 (207,174,145)、
    宽 15~24px，第 8 关的缝近白、宽约 20px，合成图的缝是 4px 纯白 —— 全都适用。
    """
    runs = _tile_runs(img, horizontal, fixed)
    if not runs:
        return False
    g = 0.45 * pitch
    zones, cur = [], None
    for a, b in runs:
        if cur is not None and a - cur[1] - 1 <= g:
            cur[1] = b
        else:
            if cur is not None:
                zones.append(cur)
            cur = [a, b]
    if cur is not None:
        zones.append(cur)
    L, R = max(zones, key=lambda z: z[1] - z[0])
    span = R - L + 1
    if span < min_span * pitch:
        return False
    n_cells = max(1, round(span / pitch))
    n_fill = sum(1 for a, b in runs if L <= a and b <= R)
    return n_fill >= min_fill * n_cells


def auto_calibrate(img, verbose=None):
    """自动标定：先靠 find_line 拿到格距和一粒"种子格"，再靠等间距瓦片色段向左右/上下扩展。

    只靠 find_line 数段数的老做法会漏掉最后一列（它右边是外框不是缝隙），
    第 11/12 关就栽在这里：判成 8 列 / 直接失败。
    """
    log = verbose if verbose is not None else []
    W, H = img.size

    # --- 横向：格距 + 种子列 ---
    y, hcl = find_line(img, True, int(H * 0.22), int(H * 0.80))
    if not hcl:
        log.append("横向未找到「等宽等距」的瓦片链")
        return None
    px_pitch = statistics.median([b[0] - a[0] for a, b in zip(hcl, hcl[1:])])
    seed_cx = (hcl[0][0] + hcl[0][1]) / 2.0        # 用段中点当列中心，避开瓦片内缩误差
    log.append("横向种子 %d 段，格距=%.2f，种子列中心 x=%.1f" % (len(hcl), px_pitch, seed_cx))

    # --- 纵向：格距 + 种子行 ---
    x, vcl = find_line(img, False, int(W * 0.30), int(W * 0.85))
    if not vcl:
        log.append("纵向未找到「等宽等距」的瓦片链")
        return None
    py_pitch = statistics.median([b[0] - a[0] for a, b in zip(vcl, vcl[1:])])
    seed_cy = (vcl[0][0] + vcl[0][1]) / 2.0
    log.append("纵向种子 %d 段，格距=%.2f，种子行中心 y=%.1f" % (len(vcl), py_pitch, seed_cy))

    if not (24 <= px_pitch <= 400 and 24 <= py_pitch <= 400):
        log.append("格距不合理，放弃")
        return None

    # --- 种子自检：种子行/列本身必须真的像棋盘 ---
    # 这里防的是"种子落在棋盘外一行/一列"这类错误。此时扩展会照常成功，
    # 但整块棋盘偏一格，取色全错却**不会报错**——是最危险的一种失败。
    # 宁可标定失败（转人工 scan），也不要静默给错。
    if not _is_board_line(img, True, int(seed_cx), px_pitch):
        log.append("种子列 x=%.1f 未通过棋盘列校验，标定失败" % seed_cx)
        return None
    if not _is_board_line(img, False, int(seed_cy), py_pitch):
        log.append("种子行 y=%.1f 未通过棋盘行校验，标定失败" % seed_cy)
        return None

    # --- 向左右扩展列数 ---
    def col_ok(k):
        return _is_board_line(img, True, int(seed_cx + k * px_pitch), px_pitch)

    lo_c = hi_c = 0
    capped = False
    for _ in range(20):
        if not col_ok(lo_c - 1):
            break
        lo_c -= 1
    else:
        capped = True
    for _ in range(20):
        if not col_ok(hi_c + 1):
            break
        hi_c += 1
    else:
        capped = True
    cols = hi_c - lo_c + 1
    x0 = seed_cx - (0.5 - lo_c) * px_pitch

    # --- 向上下扩展行数 ---
    def row_ok(k):
        return _is_board_line(img, False, int(seed_cy + k * py_pitch), py_pitch)

    lo_r = hi_r = 0
    for _ in range(20):
        if not row_ok(lo_r - 1):
            break
        lo_r -= 1
    else:
        capped = True
    for _ in range(20):
        if not row_ok(hi_r + 1):
            break
        hi_r += 1
    else:
        capped = True
    rows = hi_r - lo_r + 1
    y0 = seed_cy - (0.5 - lo_r) * py_pitch

    log.append("扩展结果：左+%d 右+%d -> cols=%d；上+%d 下+%d -> rows=%d"
               % (-lo_c, hi_c, cols, -lo_r, hi_r, rows))

    if not (3 <= cols <= 16 and 3 <= rows <= 16):
        log.append("行列数超出合理范围，放弃")
        return None
    if capped:
        log.append("扩展触到上限，可能没走完，放弃")
        return None
    return {"x0": x0, "px": px_pitch, "y0": y0, "py": py_pitch,
            "cols": cols, "rows": rows}


def extract(img, cal, out_dir, tag=""):
    NC, NR = cal["cols"], cal["rows"]
    X0, PX, Y0, PY = cal["x0"], cal["px"], cal["y0"], cal["py"]
    grid, detail = [], []
    for r in range(NR):
        row, drow = [], []
        for c in range(NC):
            cx = X0 + PX * (c + 0.5)
            cy = Y0 + PY * (r + 0.5)
            hw, hh = PX * 0.25, PY * 0.25
            box = (int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh))
            crop = img.crop(box).convert("RGB")
            # 用 resize 到 1x1 求均值：比 getdata() 快，且避开 Pillow 14 的弃用告警
            avg = crop.resize((1, 1), Image.BOX).getpixel((0, 0))
            lab = classify(avg)
            row.append(lab)
            drow.append("%s%s" % (lab, avg))
        grid.append("".join(row))
        detail.append(drow)

    CW, CH = 56, 56
    crop = img.crop((int(X0), int(Y0), int(X0 + PX * NC), int(Y0 + PY * NR)))
    crop = crop.resize((CW * NC, CH * NR), Image.LANCZOS)
    recon = Image.new("RGB", (CW * NC, CH * NR), (255, 255, 255))
    dr = ImageDraw.Draw(recon)
    try:
        f = ImageFont.truetype(FONT, 24)
        fl = ImageFont.truetype(FONT, 20)
    except Exception:
        f = fl = None
    for r in range(NR):
        for c in range(NC):
            x, y = c * CW, r * CH
            dr.rectangle([x, y, x + CW - 2, y + CH - 2], fill=PAL[grid[r][c]], outline=(255, 255, 255))
            if f:
                dr.text((x + 18, y + 14), grid[r][c], font=f, fill=(40, 40, 40))
    canvas = Image.new("RGB", (CW * NC * 2 + 40, CH * NR + 60), (28, 30, 36))
    canvas.paste(crop, (10, 45))
    canvas.paste(recon, (CW * NC + 30, 45))
    d = ImageDraw.Draw(canvas)
    if fl:
        d.text((10, 12), "原图裁剪（放大）", font=fl, fill=(240, 240, 240))
        d.text((CW * NC + 30, 12), "程序重建（逐格取色）", font=fl, fill=(240, 240, 240))
    canvas.save(os.path.join(out_dir, "grid_recon.png"))

    unknown = sum(1 for row in grid for ch in row if ch == "?")
    rep = ["标定: x0=%.2f px=%.2f y0=%.2f py=%.2f cols=%d rows=%d%s"
           % (X0, PX, Y0, PY, NC, NR, tag), ""]
    rep.append("无法归类(=?)的格子数 = %d  %s"
               % (unknown, "OK" if unknown == 0 else "偏多则标定不准，请用 scan 手工标定"))
    rep.append("")
    rep.append("GRID:")
    rep += ["  " + " ".join(g) for g in grid]
    rep.append("")
    rep.append("DETAIL:")
    rep += ["  " + " ".join(x) for x in detail]
    rep.append("")
    rep.append("棋盘行（喂给 solve.py，最后自己补一行目标色）：")
    rep += grid
    with open(os.path.join(out_dir, "grid_report.txt"), "w", encoding="utf-8") as fo:
        fo.write("\n".join(rep))
    return grid, unknown


def cmd_scan(a):
    img = Image.open(a.img).convert("RGB")
    W, H = img.size
    px = img.load()
    lines = ["IMAGE %dx%d" % (W, H)]
    for y in (a.y or [int(H * f) for f in (0.37, 0.54, 0.70)]):
        lines.append("=== ROW y=%d ===" % y)
        for s, e, col, ln in rle([px[x, y] for x in range(W)]):
            lines.append("  x %4d..%4d len=%3d rgb=%s" % (s, e, ln, col))
    for x in (a.x or [int(W * f) for f in (0.36, 0.56, 0.75)]):
        lines.append("=== COL x=%d ===" % x)
        for s, e, col, ln in rle([px[x, y] for y in range(H)]):
            lines.append("  y %4d..%4d len=%3d rgb=%s" % (s, e, ln, col))
    with open(os.path.join(a.out, "grid_scan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("scan -> grid_scan.txt")


def cmd_auto(a):
    img = Image.open(a.img).convert("RGB")
    log = []
    cal = auto_calibrate(img, verbose=log)
    if not cal:
        with open(os.path.join(a.out, "grid_report.txt"), "w", encoding="utf-8") as f:
            f.write("自动标定失败。请用 scan 模式手工标定，再用 extract 模式取色。\n\n")
            f.write("--- 标定过程日志 ---\n")
            f.write("\n".join(log) + "\n")
        print("auto failed -> use scan")
        return
    grid, unknown = extract(img, cal, a.out, tag="  (auto)")
    with open(os.path.join(a.out, "grid_report.txt"), "a", encoding="utf-8") as f:
        f.write("\n\n--- 标定过程日志 ---\n")
        f.write("\n".join(log) + "\n")
    print("auto done, unknown=%d" % unknown)


def cmd_extract(a):
    img = Image.open(a.img).convert("RGB")
    cal = {"x0": a.x0, "px": a.px, "y0": a.y0, "py": a.py, "cols": a.cols, "rows": a.rows}
    grid, unknown = extract(img, cal, a.out, tag="  (manual)")
    print("extract done, unknown=%d" % unknown)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("auto")
    p.add_argument("--img", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("scan")
    p.add_argument("--img", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--y", nargs="*", type=int)
    p.add_argument("--x", nargs="*", type=int)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("extract")
    for k in ("img", "out"):
        p.add_argument("--" + k, required=True)
    for k in ("x0", "px", "y0", "py"):
        p.add_argument("--" + k, type=float, required=True)
    for k in ("cols", "rows"):
        p.add_argument("--" + k, type=int, required=True)
    p.set_defaults(func=cmd_extract)

    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    a.func(a)


if __name__ == "__main__":
    main()
