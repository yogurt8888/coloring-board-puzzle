# -*- coding: utf-8 -*-
"""已解关卡索引 —— 支持「打个字就出答案」和「重复截图秒出图」。

两种用法：
  1. 用户说「第 8 关 / 画盘 9 怎么过」  ->  by_level(8) 直接取结论和成品图
  2. 用户发来截图，取色后发现棋盘和某一关一模一样 ->  match(grid, target)
     命中就直接复用那关的成品图，跳过求解/复核/出图/反查（1 秒 -> 0.05 秒）

命中判据刻意定得很严：**棋盘 63 格逐格相同 且 目标色相同**才复用。
宁可多算一遍（也就 1~3 秒），也不能拿别的关的答案冒充 —— 这类游戏关卡
长得像的很多，差一格结论就完全不同。
"""
import json
import os
import time
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
LEVELS_DIR = os.path.join(SKILL_ROOT, "assets", "levels")
INDEX_PATH = os.path.join(LEVELS_DIR, "levels.json")

#: 远端索引的候选地址（按顺序尝试，用上第一个能连通的）。
#: raw.githubusercontent.com 是官方源，但在国内经常超时/被阻断；jsDelivr 是可直取的 GitHub 镜像，
#: 实测国内可达性好得多，所以排在第一备选。
#: 想自建镜像/内网分发：设环境变量 CB_LEVELS_BASE —— **一旦设置就只用它**，不再回落到公网源。
REMOTE_BASES_DEFAULT = (
    "https://raw.githubusercontent.com/yogurt8888/"
    "coloring-board-puzzle/main/assets/levels",
    "https://cdn.jsdelivr.net/gh/yogurt8888/"
    "coloring-board-puzzle@main/assets/levels",
    "https://fastly.jsdelivr.net/gh/yogurt8888/"
    "coloring-board-puzzle@main/assets/levels",
)
DEFAULT_TIMEOUT = 4.0
COOLDOWN_HOURS = 6                      # 联网失败后的冷却时间，免得离线用户每次都干等
COOLDOWN_PATH = os.path.join(LEVELS_DIR, ".sync_cooldown")

_CACHE = None


def load():
    """读索引；文件不在时返回空索引而不是抛异常（索引是加速项，不是必需项）。"""
    global _CACHE
    if _CACHE is None:
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {"version": 1, "levels": {}}
    return _CACHE


def by_level(level):
    """按关卡号取元数据（键在 JSON 里是字符串）。找不到返回 None。"""
    lv = load().get("levels", {})
    return lv.get(str(level)) or lv.get(str(level).lstrip("0"))


def norm_grid(grid):
    """把棋盘统一成 63 字符的串，方便比对。

    grid 可能是 list[str]（每行一串）或 list[list[str]]，也可能带 \\r。
    """
    if grid and isinstance(grid[0], (list, tuple)):
        return "".join("".join(r) for r in grid)
    return "".join(str(r).strip() for r in grid)


def match(grid, target=None):
    """在已解关卡里找完全相同的棋盘。

    一律返回三元组 (关卡号, 元数据, 提示串)：
      命中   -> (第几关, 那关的元数据, None)
      未命中 -> (None, None, 提示串或 None)

    **不要**复用「命中给元数据、未命中给提示」这种两元组写法 ——
    同一个位置两种类型，调用方很容易顺着写错（已踩过一次）。

    target 给了就一起比对；不给则只比棋盘。
    """
    g = norm_grid(grid)
    lv = load().get("levels", {})
    tgt = (target or "").strip().upper() or None
    near = None
    for k, meta in lv.items():
        mg = norm_grid(meta["grid"])
        if mg != g:
            # 记录「最接近」的一关，方便未命中时给人一句有用的提示
            d = sum(1 for a, b in zip(g, mg) if a != b)
            if near is None or d < near[0]:
                near = (d, int(k))
            continue
        if tgt and meta.get("target", "").upper() != tgt:
            continue
        return int(k), meta, None
    if near and near[0] <= 6:
        return None, None, ("与第 %d 关只差 %d 格，但并非完全相同，已按新关卡重新求解"
                            % (near[1], near[0]))
    return None, None, None


def png_path(meta):
    """元数据对应的成品图绝对路径；文件缺失返回 None。"""
    if not meta or not meta.get("png"):
        return None
    p = os.path.join(LEVELS_DIR, meta["png"])
    return p if os.path.exists(p) else None


def levels_summary():
    """一行一关的摘要，给 agent 列目录用。"""
    out = []
    for k in sorted(load().get("levels", {}), key=lambda x: int(x)):
        m = load()["levels"][k]
        out.append("第 %-2s 关  目标%s  最短 %s 步（预算 %s）  点第%d行第%d列  %s"
                   % (k, m.get("target"), m.get("steps"), m.get("budget"),
                      (m.get("tap") or [0, 0])[0], (m.get("tap") or [0, 0])[1],
                      " → ".join(m.get("seq", ""))))
    return out


# ---------------------------------------------------------------------------
# 远端关卡同步：作者往 GitHub 推了新关（第 13 关、14 关 …），
# 已经装过 skill 的人不用重装，下一次问「第 13 关怎么过」时会自动取到。
#
# 设计要点：
#   * 只在**本地查不到**时才联网 —— 1~12 关这种本地就有的路径仍然是零网络、秒回；
#   * 拉的是一份 4KB 的 levels.json，命中后才按需下载对应成品图（约 100~200KB）；
#   * 网络不可用一律静默降级（照常走本地/求解），绝不因为断网让整个流程失败；
#   * 失败后写冷却标记，6 小时内不再重试，免得离线用户每次等超时。
# ---------------------------------------------------------------------------

def offline():
    """CB_OFFLINE=1 / --no-sync 时不联网。"""
    return os.environ.get("CB_OFFLINE", "").strip().lower() not in ("", "0", "false", "no")


def remote_bases():
    """本次同步要依次尝试的候选地址。

    设了 CB_LEVELS_BASE（自建镜像 / 内网分发）就**只用它** —— 内网环境不该偷偷回落到公网。
    """
    env = os.environ.get("CB_LEVELS_BASE", "").strip()
    if env:
        return [env.rstrip("/")]
    return [u.rstrip("/") for u in REMOTE_BASES_DEFAULT]


def remote_base():
    """候选里的第一个（保留旧接口，给只想看主源的地方用）。"""
    return remote_bases()[0]


def _get(url, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "coloring-board-skill"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _safe_name(name):
    """远端给的文件名只允许落在 assets/levels/ 里（防目录穿越）。"""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    return os.path.basename(name)


def _cooldown_active():
    try:
        with open(COOLDOWN_PATH, encoding="utf-8") as f:
            return (time.time() - float(f.read().strip())) < COOLDOWN_HOURS * 3600
    except Exception:
        return False


def _mark_cooldown():
    try:
        with open(COOLDOWN_PATH, "w", encoding="utf-8") as f:
            f.write("%.0f" % time.time())
    except Exception:
        pass


def _clear_cooldown():
    try:
        os.remove(COOLDOWN_PATH)
    except Exception:
        pass


def sync_remote(level=None, timeout=DEFAULT_TIMEOUT, log=None, force=False):
    """拉远端最新索引合并到本地，并补齐缺失的成品图。

    返回 (状态, 一句话说明)：
      "updated"   合并成功（本地 levels.json 已改写）
      "nochange"  远端版本不比本地新（或远端也没有要找的那一关）
      "offline"   离线开关打开 / 正在冷却
      "error"     网络或远端不可用 —— 静默降级，调用方继续走本地逻辑

    **任何异常都不外抛**：索引同步是增益项，不是必经步骤。
    """
    def say(s):
        if log is not None:
            log.append(s)

    if offline():
        return "offline", "已设置离线（CB_OFFLINE / --no-sync），跳过远端同步"
    if not force and _cooldown_active():
        return "offline", "距上次联网失败不足 %d 小时，跳过远端同步" % COOLDOWN_HOURS

    bases = remote_bases()
    remote, base, errs = None, None, []
    for b in bases:
        try:
            remote = json.loads(_get(b + "/levels.json", timeout).decode("utf-8"))
            base = b
            break
        except Exception as e:
            errs.append("%s（%s）" % (b.split("//")[-1].split("/")[0], e))
    if remote is None:
        detail = "；".join(errs) or "没有可用地址"
        say("远端索引不可用：" + detail)
        _mark_cooldown()
        return "error", "远端索引不可用（%s）" % detail
    if base != bases[0]:
        say("主源不可用，已回落到镜像：%s" % base)

    try:
        rlv = remote.get("levels") or {}
        if not rlv:
            return "error", "远端索引为空"
        cur = load()
        cver = int(cur.get("version", 0))
        rver = int(remote.get("version", 0))
        if not force and rver <= cver:
            return "nochange", "远端索引版本 %d 不高于本地 %d" % (rver, cver)
        if level is not None and str(level) not in rlv:
            # 明确要找的那一关远端也没有：不必写回，下次再试
            return "nochange", "远端索引里也没有第 %s 关（远端版本 %d）" % (level, rver)

        new_keys = [k for k in rlv if k not in cur.get("levels", {})]
        merged = dict(cur.get("levels", {}))
        merged.update(rlv)
        cur["levels"] = merged
        cur["version"] = max(cver, rver)
        if remote.get("updated"):
            cur["updated"] = remote["updated"]
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)

        got = []
        for k, meta in rlv.items():
            name = _safe_name((meta or {}).get("png") or "")
            if not name:
                continue
            p = os.path.join(LEVELS_DIR, name)
            if os.path.exists(p):
                continue
            try:
                with open(p, "wb") as f:
                    f.write(_get(base + "/" + quote(name), timeout))
                got.append(name)
            except Exception as e:
                say("第 %s 关成品图下载失败：%s" % (k, e))
        _clear_cooldown()
        return ("updated",
                "已同步远端索引 v%d（原 v%d）：新增 %d 关，补下成品图 %d 张"
                % (rver, cver, len(new_keys), len(got)))
    except Exception as e:
        say("合并远端索引失败：%s" % e)
        _mark_cooldown()
        return "error", "合并远端索引失败（%s）" % e
