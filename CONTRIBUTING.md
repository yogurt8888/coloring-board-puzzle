# 维护指南（第 22 关及以后怎么加）

这份文件是给**仓库维护者**看的。只使用技能的人不需要读 —— README 里已经说明
「新关卡会自动同步，不用重装」。

---

## 一、加一关新关卡（并让所有装过的人都拿到）

1. 把棋盘存成 `examples/board_level<N>.txt`：7 行颜色字母 + 末行目标色；
2. 在 `tools/build_level_index.py` 的 `BUDGET` 里补上这关的截图预算
   （不补则回退为最短步数）；
3. 出成品图：

   ```bash
   python scripts/pipeline.py --board examples/board_level22.txt --level 22 \
       --target B --budget 5 --out assets/levels --no-cache
   ```

   首次必须加 `--no-cache`，否则可能被索引判成"与某个旧关卡相同"而直接复用旧图；
4. 重建索引：

   ```bash
   python tools/build_level_index.py
   ```

   它会自动扫描 `examples/` 下**全部** `board_level*.txt`（新增关卡不用改代码），
   并把 `assets/levels/levels.json` 的 `version` 加一 —— **用户端就是靠这个版本号
   判断"远端有更新"的**；
5. 把这一关写进文档：`SKILL.md` 的索引表 + 详细解法、`README.md` 的关卡表。
   **别漏了 `SKILL.md` frontmatter 里的 `description`** —— 那句「自带 1~N 关答案索引」容易忘记同步。
   另外若新关卡的「可点格 / 起点块」比旧关更宽或更窄，记得回去改旧关卡里"1~N 关里最窄/最宽松"这类相对说法。
   写「第 N 步并了哪几片」之前**先跑一次**：

   ```bash
   python tools/step_detail.py 21
   ```

   它按 `levels.json` 里的 tap / seq 现算每一步并进来的原始色块（片数 / 格数 / 坐标），
   并列出**全部可用的起点块**与各自可行的颜色顺序（写"宽容度"时要用）。
   这一步别省：靠肉眼数格子写详解必错，本项目已经因此返工过一次。
6. 提交推送：

   ```bash
   git add -A && git commit && git push
   ```

推送之后，装过技能的人不需要重装：下一次有人问「第 22 关怎么过」，
本地索引里没有 → 自动取远端 `levels.json` → 合并写回本地 + 补下成品图 → 秒回。
也可以让他们手动跑一次 `python scripts/pipeline.py --sync-levels` 立刻拉全量。

> 冒烟自测建议：`python tools/selfcheck.py`，再做一次**全新 clone** 跑同一脚本，
> 确认新关卡的成品图真的进了仓库（中文文件名容易被忽略）。

---

## 二、改了版式 / 求解器 / 标定之后

1. 重跑全部关卡（改了几关就传 `--levels 8,9`，否则跑全量）：

   ```bash
   python tools/build_level_index.py --levels 8,9      # 重建索引
   python tools/build_level_index.py --check           # 只校验不写
   ```

2. 重新渲染受影响的成品图（`--out assets/levels`，各关都要过一次）；
3. `python tools/selfcheck.py` 必须全绿（环境 / 字体 / 索引一致性 / 三道校验）；
4. 提交推送。

**不要手工编辑 `levels.json` 或 README 里的关卡表** —— 两者都由
`tools/build_level_index.py` 从棋盘与求解器现算，手改必然与求解器漂移。

---

## 三、版本号与兼容性

- `levels.json` 的 `version` 每重建一次 +1；用户端只做「远端 version 比本地新就合并」，
  不做降级。**连跑两次 `build_level_index.py` 会让 version 跳过若干号（无副作用，用户端只比大小），
  但正式发布前建议只跑一次。**
- 索引条目带 63 格逐格指纹，合并时按指纹与关号双重判断，不会把已有关卡覆盖坏。
- 远端地址默认取 `raw.githubusercontent.com`；改域名 / 自建镜像设 `CB_LEVELS_BASE`
  指向放 `levels.json` 与成品图的目录即可。

---

## 四、发布清单

- [ ] `python tools/selfcheck.py` 全绿
- [ ] 全新 clone 后同样全绿（验证成品图、字体都在仓库里）
- [ ] `levels.json` 的 `version` 已递增
- [ ] README 的「已解关卡」表与实际一致
- [ ] 提交信息保持**简短一句话**（历史已压成单条 `v1.0.0`；以后加关卡用普通提交即可，
      不要按目录写长描述 —— GitHub 文件列表那列会截断成「…」，很难看）
- [ ] `git remote -v` 里不含明文 token
