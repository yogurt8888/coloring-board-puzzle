# -*- coding: utf-8 -*-
"""把 Noto Sans SC（SIL OFL-1.1）子集化成随仓库分发的小字体。

仓库里已经放好了产物（assets/fonts/CBBoardSans-*.ttf），**平时不需要跑这个脚本**；
只有在想调整字符覆盖范围、或升级上游字体时才用。

用法：
    pip install fontTools brotli
    python tools/make_font_subset.py --src-dir <含 NotoSansSC-*.ttf 的目录>

--src-dir 里需要有两个文件（可从 https://github.com/notofonts/noto-cjk 获取）：
    NotoSansSC-Regular.ttf / NotoSansSC-Bold.ttf

OFL 要求：子集化属于"修改"，修改后的字体**不得再使用保留字体名（Reserved Font Name）**，
因此输出一律改名为 CBBoardSans-*，并在 assets/fonts/ 下附 OFL 原文。

保留字符集 =
    ASCII 可见字符
  + 本技能所有文本文件里出现过的非 ASCII 字符（注释 + 交付图文案，覆盖实际用字）
  + GB2312 全部汉字与中文标点（安全垫：别人改文案也不会出现豆腐块）
  + 若干常用符号（箭头等，GB2312 不含）
"""
import argparse
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DST = os.path.join(ROOT, "assets", "fonts")
SCAN_EXT = (".py", ".md", ".txt")


def gb2312_chars():
    out = set()
    for hi in range(0xA1, 0xFF):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except Exception:
                pass
    return out


def source_chars():
    out = set()
    for root, _dirs, files in os.walk(ROOT):
        if "__pycache__" in root or os.sep + ".git" in root:
            continue
        for fn in files:
            if not fn.endswith(SCAN_EXT) or fn == os.path.basename(__file__):
                continue
            with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as f:
                out |= set(f.read())
    return out


def rename(font, family, style):
    """按 OFL 要求改名，去掉上游的保留字体名。"""
    full = "%s %s" % (family, style)
    ps = "%s-%s" % (family, style)
    want = {1: family, 2: style, 3: ps, 4: full, 6: ps, 16: family, 17: style}
    for rec in font["name"].names:
        if rec.nameID in want:
            s = want[rec.nameID]
            rec.string = s.encode("utf-16-be") if (rec.platformID == 3 or rec.isUnicode()) \
                else s.encode("latin-1", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", required=True, help="含 NotoSansSC-Regular/Bold.ttf 的目录")
    a = ap.parse_args()
    os.makedirs(DST, exist_ok=True)

    chars = {chr(c) for c in range(0x20, 0x7F)} | gb2312_chars() | source_chars()
    chars |= set("→←↑↓≥≤×·—…“”‘’《》【】、。，：；！？（）％")
    chars = {c for c in chars if c.isprintable()}
    cs_path = os.path.join(DST, "_charset.txt")
    with open(cs_path, "w", encoding="utf-8") as f:
        f.write("".join(sorted(chars)))
    print("字符集大小 = %d" % len(chars))

    jobs = [("NotoSansSC-Regular.ttf", "CBBoardSans-Regular.ttf", "Regular"),
            ("NotoSansSC-Bold.ttf", "CBBoardSans-Bold.ttf", "Bold")]
    for src_name, dst_name, style in jobs:
        src = os.path.join(a.src_dir, src_name)
        if not os.path.exists(src):
            print("缺少源字体：%s" % src)
            return 1
        dst = os.path.join(DST, dst_name)
        subset.main([src, "--text-file=" + cs_path, "--output-file=" + dst,
                     "--layout-features=", "--no-hinting",
                     "--desubroutinize", "--drop-tables+=DSIG"])
        ft = TTFont(dst)
        rename(ft, "CBBoardSans", style)
        ft.save(dst)
        bad = [r.toUnicode() for r in ft["name"].names
               if r.nameID in (1, 4, 6) and "Noto" in r.toUnicode()]
        print("%-26s -> %-24s %7.1f KB  上游名残留=%d"
              % (src_name, dst_name, os.path.getsize(dst) / 1024.0, len(bad)))
    os.remove(cs_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
