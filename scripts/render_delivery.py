# -*- coding: utf-8 -*-
"""统一交付格式渲染器 —— 画盘（染色棋盘）类游戏

输出一张 PNG，版式固定为：

    [画盘-N]  ← 深色胶囊 + 白字（26 号，显眼）
    最优解：N 步（预算 M 步，富余 K 步）
    一句话心法
    ┌ 第 1 步 | 选【黄】 ┐   ┌ 第 2 步 | 选【红】 ┐
    │  盘面（本步动手前）│   │      ...          │
    │  圈出要点的格子    │   │                   │
    │  说明第一行        │   │                   │
    │  说明第二行        │   │                   │
    └ ... 2 列或 3 列 ... ┘

    （画布底部**不再有**补充说明那行；确有需要时用 --foot 显式加。）

要点：
- 每个面板展示的是「这一步动手之前」的盘面，圈出本步要点的格子，**圈的颜色 = 本步画笔色**。
- 面板列数：步数 <= 4 用 2 列，>= 5 用 3 列（可用 --cols 强制）。
- 浅色底 + 深色字（用户指定的交付风格），与截图无关、不依赖原图。
- 说明文字按面板宽度自动换行，面板高度随行数自适应。

用法：
    python render_delivery.py --board board4.txt --tap 2,5 --seq RBG \
        --level 4 --budget 3 --out . \
        --sub "先把多块染成同色合并成一片，最后一步整片染绿" \
        --foot "保底打法：先并掉几块同色碎片，剩下逐块刷成绿色即可。"
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------- #
# 字体解析：随仓库自带 > 环境变量 > 系统常见中文字体 > Pillow 默认
#
# 为什么不能写死路径：交付图上全是中文，写死 C:/Windows/Fonts/msyh.ttc 的话
# macOS / Linux 上直接崩；而微软雅黑**不允许随软件再分发**，也不能塞进仓库。
# 所以仓库里放的是 Noto Sans SC（SIL OFL-1.1，可再分发）子集化后改名成的
# CBBoardSans-*，见 assets/fonts/。都找不到时才退回 Pillow 默认（会缺字形，
# 但至少不崩，并在 stderr 给一条警告，方便一眼看出是字体问题不是逻辑问题）。
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

#: 仓库自带字体（相对 scripts/ 定位，clone 到任何位置都能找到）
BUNDLED_R = os.path.join(SKILL_ROOT, "assets", "fonts", "CBBoardSans-Regular.ttf")
BUNDLED_B = os.path.join(SKILL_ROOT, "assets", "fonts", "CBBoardSans-Bold.ttf")

#: 各平台常见的中文字体，兜底用
SYS_FONTS = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]


def _resolve(explicit, bundled):
    for p in (explicit, os.environ.get("CB_FONT_REGULAR"), os.environ.get("CB_FONT_BOLD"),
              bundled if os.path.exists(bundled) else None):
        if p and os.path.exists(p):
            return p
    for p in SYS_FONTS:
        if os.path.exists(p):
            return p
    return None


FONT_R = _resolve(None, BUNDLED_R)
FONT_B = _resolve(None, BUNDLED_B)
if FONT_B is None:
    FONT_B = FONT_R
if FONT_R is None:
    sys.stderr.write("[render] 警告：没找到任何中文字体，交付图上的中文会缺字形。\n"
                     "[render] 请把一个中文字体放到 assets/fonts/ 或设置 CB_FONT_REGULAR。\n")

NAMES = {"R": "红", "Y": "黄", "B": "蓝", "G": "绿"}

# 盘面瓦片色（浅）
CELL = {"R": (238, 122, 106), "Y": (245, 220, 110),
        "B": (168, 210, 240), "G": (122, 220, 160)}
# 文字 / 色条 / 圆圈用的「墨色」（深，保证在浅底上看得清）
INK = {"R": (211, 66, 52), "Y": (183, 132, 8),
       "B": (42, 120, 205), "G": (24, 152, 96)}

BG = (246, 246, 244)
CARD = (255, 255, 255)
EDGE = (231, 229, 223)
FRAME = (213, 203, 189)
DARK = (30, 32, 36)
GRAY = (126, 130, 138)
GRAY2 = (92, 96, 104)
BLUE = (33, 90, 200)
BLUEBG = (230, 239, 254)
TAGBG = (58, 62, 72)        # 关卡标签胶囊底色（深，配白字才够显眼）

# --------------------------------------------------------------------------- #
# 版面尺寸规则（verify_render.py 反查时复用同一套，避免两边各写一份而跑偏）
# --------------------------------------------------------------------------- #
PAD = 30            # 画布外边距
CARD_PAD = 16       # 面板内边距
GAP_X, GAP_Y = 34, 26
PANEL_MIN = 420     # 面板最小宽度
HEADER_H = 34       # 面板表头高度
TAG_FS = 26         # 顶部关卡标签字号（用户要求「加大、更显眼」）
TAG_H = 52          # 标签行占高（含胶囊上下留白）


def cell_px(nc):
    """每个瓦片格在交付图里的边长（px）。"""
    return max(18, min(42, (PANEL_MIN - 2 * CARD_PAD) // nc))


def panel_w_for(nc):
    """面板宽度：棋盘宽 + 两侧内边距，但不小于 PANEL_MIN。"""
    return max(PANEL_MIN, nc * cell_px(nc) + 2 * CARD_PAD)


# --------------------------------------------------------------------------- #
# 棋盘逻辑
# --------------------------------------------------------------------------- #
def read_board(path):
    with open(path, encoding="utf-8-sig") as f:
        ls = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if len(ls) < 2:
        raise SystemExit("board 文件至少要有一行棋盘 + 一行目标色")
    target, grid = ls[-1], ls[:-1]
    if len(set(len(r) for r in grid)) != 1:
        raise SystemExit("board 各行长度不一致")
    bad = set("".join(grid)) | set(target)
    if not bad <= set(NAMES):
        raise SystemExit("board 出现了未知颜色字符: %s" % (bad - set(NAMES)))
    return [list(r) for r in grid], target


def region(g, r, c):
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


def simulate(grid, pt, seq):
    """返回每一步的 (动手前盘面, 染色格数, 本步画笔色)，以及终局盘面。"""
    g = [row[:] for row in grid]
    out = []
    for col in seq:
        before = [row[:] for row in g]
        cells = region(g, pt[0], pt[1])
        for (y, x) in cells:
            g[y][x] = col
        out.append((before, len(cells), col))
    return out, g


def count_blocks(grid, target):
    nr, nc = len(grid), len(grid[0])
    seen, n = set(), 0
    for r in range(nr):
        for c in range(nc):
            if (r, c) in seen:
                continue
            col = grid[r][c]
            st = [(r, c)]
            seen.add((r, c))
            while st:
                y, x = st.pop()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < nr and 0 <= nx < nc and (ny, nx) not in seen \
                            and grid[ny][nx] == col:
                        seen.add((ny, nx))
                        st.append((ny, nx))
            if col != target:
                n += 1
    return n


# --------------------------------------------------------------------------- #
# 绘制
# --------------------------------------------------------------------------- #
def load_fonts():
    def f(name, size):
        try:
            if name:
                return ImageFont.truetype(name, int(size))
        except Exception:
            pass
        try:                      # Pillow >= 9.2 支持指定字号
            return ImageFont.load_default(size=int(size))
        except TypeError:
            return ImageFont.load_default()
    return {
        "tag": f(FONT_B, TAG_FS),
        "title": f(FONT_B, 30),
        "sub": f(FONT_R, 17),
        "step": f(FONT_B, 20),
        "cap": f(FONT_R, 15),
        "foot": f(FONT_R, 15),
    }


def draw_board(d, x, y, cell, grid, pt, ink):
    nr, nc = len(grid), len(grid[0])
    gap = 2
    rad = max(3, cell // 9)
    bw, bh = nc * cell, nr * cell
    d.rounded_rectangle([x - 5, y - 5, x + bw + 5, y + bh + 5],
                        radius=rad + 4, outline=FRAME, width=3, fill=CARD)
    for r in range(nr):
        for c in range(nc):
            p0, q0 = x + c * cell, y + r * cell
            d.rounded_rectangle(
                [p0 + gap, q0 + gap, p0 + cell - gap - 1, q0 + cell - gap - 1],
                radius=rad, fill=CELL.get(grid[r][c], (150, 150, 150)))
    # 圈出要点的格子（圈色 = 本步画笔色）
    cx = x + pt[1] * cell + cell // 2
    cy = y + pt[0] * cell + cell // 2
    rr = int(cell * 0.66)
    w = max(4, cell // 9)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
              outline=(255, 255, 255, 255), width=w + 3)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=ink, width=w)
    return bw, bh


def wrap(d, text, font, maxw):
    lines, cur = [], ""
    for ch in text:
        if not cur or d.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def render(spec):
    grid, target = spec["grid"], spec["target"]
    NR, NC = len(grid), len(grid[0])
    tap, seq = spec["tap"], spec["seq"]
    steps, final = simulate(grid, tap, seq)
    n, total = len(steps), NR * NC

    ncols = spec.get("cols") or (2 if n <= 4 else 3)
    nrows = (n + ncols - 1) // ncols

    F = load_fonts()
    pad = PAD
    card_pad = CARD_PAD
    gap_x, gap_y = GAP_X, GAP_Y
    cell = cell_px(NC)
    bw, bh = NC * cell, NR * cell
    panel_w = panel_w_for(NC)
    inner_w = panel_w - 2 * card_pad
    header_h = HEADER_H

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    caps = []                       # [(第一行lines, 第二行lines), ...]
    for k, (before, size, col) in enumerate(steps):
        if spec.get("caps"):
            cap1 = spec["caps"][k]
        else:
            cap1 = "点第 %d 行第 %d 格" % (tap[0] + 1, tap[1] + 1)
            if k >= 1 and spec.get("same_cell", True):
                cap1 = "再点同一格（第 %d 行第 %d 格）" % (tap[0] + 1, tap[1] + 1)
        if spec.get("notes"):
            cap2 = spec["notes"][k]
        else:
            delta = "（比上一步 +%d 格）" % (size - steps[k - 1][1]) if k else ""
            if k == n - 1:
                cap2 = "这一步把 %d 格染成%s%s，全盘 %d 格变%s，通关" \
                       % (size, NAMES[col], delta, total, NAMES[target])
            else:
                cap2 = "这一步把 %d 格染成%s%s" % (size, NAMES[col], delta)
        caps.append((wrap(probe, cap1, F["cap"], inner_w),
                     wrap(probe, cap2, F["cap"], inner_w)))

    line_h = 22
    nlines = max(len(a) + len(b) for a, b in caps)
    cap_block = 12 + nlines * line_h
    panel_h = card_pad * 2 + header_h + bh + cap_block

    W = 2 * pad + ncols * panel_w + (ncols - 1) * gap_x

    # ---- 底部说明：**默认不画**（用户明确要求去掉那句「注意：非目标色块…」）----
    # 只有显式 `--foot "..."` 时才画；行数参与总高计算，不画时高度归零。
    foot = (spec.get("foot") or "").strip()
    foot_lines = wrap(probe, foot, F["foot"], W - 2 * pad) if foot else []
    foot_h = (18 + len(foot_lines) * 21) if foot_lines else 0

    sub_lines = wrap(probe, spec["sub"], F["sub"], W - 2 * pad)
    head_h = TAG_H + 46 + len(sub_lines) * 24 + 14
    H = pad + head_h + nrows * panel_h + (nrows - 1) * gap_y + foot_h + pad
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # ---- 顶部：关卡标签做成深色胶囊 + 白字（用户要求「加大、更显眼」）----
    y = pad
    tag = spec.get("tag")
    if tag:
        tw = d.textlength(tag, font=F["tag"])
        cap_h = TAG_FS + 20
        d.rounded_rectangle([pad, y, pad + tw + 36, y + cap_h],
                            radius=cap_h // 2, fill=TAGBG)
        d.text((pad + 18, y + 7), tag, font=F["tag"], fill=(255, 255, 255))
    y += TAG_H

    w1 = d.textlength("最优解：", font=F["title"])
    d.text((pad, y), "最优解：", font=F["title"], fill=DARK)
    x = pad + w1
    box = "%d 步" % n
    wb = d.textlength(box, font=F["title"])
    d.rounded_rectangle([x, y + 3, x + wb + 24, y + 41], radius=8, fill=BLUEBG)
    d.text((x + 12, y), box, font=F["title"], fill=BLUE)
    x += wb + 24
    if spec.get("budget") is not None:
        b = spec["budget"]
        rest = b - n
        tail = "（预算 %d 步，%s）" % (b, "刚好用满" if rest == 0 else "富余 %d 步" % rest)
        d.text((x + 8, y + 4), tail, font=F["title"], fill=GRAY2)
    y += 46

    for ln in sub_lines:
        d.text((pad, y), ln, font=F["sub"], fill=GRAY2)
        y += 24
    y += 14

    # ---- 分步面板 ----
    for k, (before, size, col) in enumerate(steps):
        rr, cc = k // ncols, k % ncols
        px = pad + cc * (panel_w + gap_x)
        py = y + rr * (panel_h + gap_y)
        d.rounded_rectangle([px, py, px + panel_w, py + panel_h],
                            radius=12, fill=CARD, outline=EDGE, width=2)
        hx, hy = px + card_pad, py + card_pad
        d.rounded_rectangle([hx, hy + 2, hx + 6, hy + 22], radius=3, fill=INK[col])
        tx = hx + 16
        s1 = "第 %d 步" % (k + 1)
        d.text((tx, hy), s1, font=F["step"], fill=DARK)
        tx += d.textlength(s1, font=F["step"]) + 6
        d.text((tx, hy), "|", font=F["step"], fill=(190, 192, 198))
        tx += d.textlength("|", font=F["step"]) + 6
        d.text((tx, hy), "选【", font=F["step"], fill=DARK)
        tx += d.textlength("选【", font=F["step"])
        d.text((tx, hy), NAMES[col], font=F["step"], fill=INK[col])
        tx += d.textlength(NAMES[col], font=F["step"])
        d.text((tx, hy), "】", font=F["step"], fill=DARK)

        bx = px + (panel_w - bw) // 2
        by = py + card_pad + header_h
        draw_board(d, bx, by, cell, before, tap, INK[col])

        ty = by + bh + 12
        tx0 = px + card_pad
        for ln in caps[k][0]:
            d.text((tx0, ty), ln, font=F["cap"], fill=DARK)
            ty += line_h
        for ln in caps[k][1]:
            d.text((tx0, ty), ln, font=F["cap"], fill=GRAY2)
            ty += line_h

    # ---- 底部 ----
    fy = H - pad - len(foot_lines) * 21
    for ln in foot_lines:
        d.text((pad, fy), ln, font=F["foot"], fill=GRAY)
        fy += 21

    out = os.path.join(spec["out"], spec["name"])
    img.save(out)
    ok = all(ch == target for row in final for ch in row)
    return out, ok, [s[1] for s in steps]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--tap", required=True, help="1 基坐标 r,c（行列均从 1 计）")
    ap.add_argument("--seq", required=True, help="画笔颜色序列，如 RBG")
    ap.add_argument("--level", default="")
    ap.add_argument("--budget", type=int, default=None,
                    help="游戏显示的剩余步数；给了才会显示「预算/富余」")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--cols", type=int, default=None, choices=[2, 3])
    ap.add_argument("--sub", default=None, help="副标题（一句话心法）")
    ap.add_argument("--foot", default=None, help="底部补充说明")
    ap.add_argument("--caps", default=None, help="每步第一行文字，用 | 分隔")
    ap.add_argument("--notes", default=None, help="每步第二行文字，用 | 分隔")
    ap.add_argument("--steps-differ", action="store_true",
                    help="各步点的不是同一格，第二行说明不写「再点同一格」")
    a = ap.parse_args()

    grid, target = read_board(a.board)
    r, c = (int(v) for v in a.tap.split(","))
    seq = a.seq.upper()
    os.makedirs(a.out, exist_ok=True)

    spec = dict(
        grid=grid, target=target, tap=(r - 1, c - 1), seq=seq,
        level=a.level, budget=a.budget, out=a.out,
        name=a.name or ("画盘%s_通关路线.png" % a.level),
        cols=a.cols,
        tag="画盘-%s" % a.level if a.level else "画盘",
        sub=a.sub or "先把多块染成同色合并成一片，最后一步整片染成【%s】" % NAMES[target],
        foot=a.foot,
        caps=a.caps.split("|") if a.caps else None,
        notes=a.notes.split("|") if a.notes else None,
        same_cell=not a.steps_differ,
    )
    out, ok, sizes = render(spec)
    print("saved=%s  final_ok=%s  sizes=%s" % (out, ok, sizes))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
