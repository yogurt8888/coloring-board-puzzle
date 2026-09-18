# -*- coding: utf-8 -*-
"""装完/改完后跑一遍，确认这套东西在这台机器上真的能用。

    python tools/selfcheck.py

检查项：
  1. Python 版本、Pillow 是否可用
  2. 自带中文字体能否加载，且真能画出中文（不是豆腐块）
  3. 索引与成品图是否一一对应
  4. 只报关号的路径（--level N）能否出图
  5. 完整求解路径能否跑通三道校验

任何一项 FAIL 都会在最后汇总里列出来，并以非零码退出。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

OK, BAD = [], []


def ok(msg):
    OK.append(msg)
    print("  [OK]   " + msg)


def bad(msg):
    BAD.append(msg)
    print("  [FAIL] " + msg)


def check_env():
    print("\n1) 运行环境")
    if sys.version_info < (3, 8):
        bad("Python %s 太老，需要 >= 3.8" % sys.version.split()[0])
    else:
        ok("Python %s" % sys.version.split()[0])
    try:
        import PIL
        ok("Pillow %s" % PIL.__version__)
    except Exception as e:
        bad("Pillow 不可用：%s（pip install -r requirements.txt）" % e)


def check_font():
    print("\n2) 中文字体")
    try:
        import render_delivery as R
        from PIL import Image, ImageDraw
        if not R.FONT_R:
            bad("没找到任何中文字体（自带字体缺失？）")
            return
        name = os.path.basename(R.FONT_R)
        if not name.startswith("CBBoardSans"):
            print("       注意：当前用的是系统字体 %s" % R.FONT_R)
        im = Image.new("L", (220, 60), 255)
        d = ImageDraw.Draw(im)
        d.text((6, 10), "画盘 最优解 63 格", font=R.load_fonts()["step"], fill=0)
        ink = sum(1 for p in im.tobytes() if p < 200)
        if ink > 200:
            ok("字体可加载且能画出中文（墨迹像素 %d，%s）" % (ink, name))
        else:
            bad("字体渲染几乎没出墨迹（墨迹像素 %d）—— 很可能画成了豆腐块" % ink)
    except Exception as e:
        bad("字体检查异常：%s" % e)


def check_index():
    print("\n3) 关卡索引")
    try:
        import level_index as LI
        data = LI.load()
        lv = data.get("levels", {})
        if not lv:
            bad("索引为空（assets/levels/levels.json 缺失或损坏）")
            return
        miss = [k for k, m in lv.items() if not LI.png_path(m)]
        if miss:
            bad("这些关卡缺成品图：%s" % ", ".join(sorted(miss, key=int)))
        else:
            ok("%d 关索引齐全，成品图一一对应" % len(lv))
        dup = {}
        for k, m in lv.items():
            dup.setdefault(LI.norm_grid(m["grid"]), []).append(k)
        same = {tuple(v) for v in dup.values() if len(v) > 1}
        if same:
            bad("索引里有完全相同的棋盘（会让复用指错关）：%s" % same)
        else:
            ok("各关棋盘互不相同")
    except Exception as e:
        bad("索引检查异常：%s" % e)


def run(cmd, cwd=ROOT):
    return subprocess.run([sys.executable] + cmd, cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def check_lookup(tmp):
    print("\n4) 只报关号的路径（--level）")
    import level_index as LI
    lvs = sorted(LI.load().get("levels", {}), key=int)
    bad_lv = []
    for k in lvs:
        r = run([os.path.join("scripts", "pipeline.py"), "--level", k, "--out", tmp])
        png = os.path.join(tmp, "画盘%s_通关路线.png" % k)
        if r.returncode != 0 or not os.path.exists(png):
            bad_lv.append(k)
    if bad_lv:
        bad("第 %s 关取图失败" % ", ".join(bad_lv))
    else:
        ok("%d 关全部能直接出图（%d 张）" % (len(lvs), len(lvs)))


def check_full_solve(tmp):
    print("\n5) 完整求解路径（三道校验）")
    board = os.path.join(ROOT, "examples", "board_level8.txt")
    if not os.path.exists(board):
        bad("缺 %s" % board)
        return
    out = os.path.join(tmp, "full")
    r = run([os.path.join("scripts", "pipeline.py"), "--board", board, "--level", "8",
             "--no-cache", "--out", out])
    summ = os.path.join(out, "_pipeline", "h8", "pipeline_summary.txt")
    if r.returncode != 0 or not os.path.exists(summ):
        bad("完整求解失败：%s" % (r.stderr or r.stdout or "")[-300:])
        return
    txt = open(summ, encoding="utf-8").read()
    for tag in ("[1] 双实现对账", "[2] 最短性证明", "[3] 成品反查"):
        line = next((l.strip() for l in txt.splitlines() if tag in l), "")
        if "PASS" in line or "一致" in line or "最短" in line:
            ok("%s -> %s" % (tag, line.split("：", 1)[-1][:60]))
        else:
            bad("%s 未通过：%s" % (tag, line or "（简报里没这行）"))


def main():
    print("coloring-board-puzzle 自检")
    print("=" * 60)
    tmp = tempfile.mkdtemp(prefix="cbcheck_")
    try:
        check_env()
        check_font()
        check_index()
        check_lookup(tmp)
        check_full_solve(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 60)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  FAIL: " + b)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
