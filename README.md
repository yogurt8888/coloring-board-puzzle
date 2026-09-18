# 画盘 · 染色棋盘通关求解器

给 AI Agent 用的技能：**发一张「画盘 / 染色棋盘」小游戏截图，或直接说"第 8 关怎么过"，
自动产出通关步骤 + 一张统一格式的通关路线图。**

纯 Python，只依赖 Pillow，Windows / macOS / Linux 通用。已经内置第 1~12 关的答案，
重复的关卡和直接报关卡号都是秒回。

---

## 怎么用（把下面这句话整段发给你的 AI）

> 帮我安装这个 skill，保证后续我发图就能给到解法：`https://github.com/yogurt8888/coloring-board-puzzle`

适用于 Claude Code、ChatGPT / Codex、豆包、Cursor、WorkBuddy、通义灵码 等任何能跑命令行的 agent。

> **⚠️ 建议用带识图（多模态）能力的模型**，例如 **hy4**、**DeepSeek V4.0 PRO / V4.1 FLASH**、
> **GLM 5.3 / 5.3 FLASH** 等。
> 原因：走「直接发截图」这条路，需要模型自己看清棋盘配色、目标色和「剩余步数」提示；
> 纯文本模型读不到图，只能走「报关卡号」的入口（"第 8 关怎么过"）。

### 用户侧的三种问法

| 你说 | AI 会做 |
|---|---|
| 发一张截图，附一句「全染成蓝色，剩 5 步」 | 标定取色 → 求解 → 出图，最快 |
| 只发一张截图 | AI 先看图上的目标色和剩余步数，再跑（多花几秒） |
| 只打字：「第 8 关怎么过」「画盘 9 的解法」 | 直接取已解存档，秒回 |

三种问法都会得到：**一段结论 + 一张 `画盘N_通关路线.png`**。

---

## 已解关卡（第 1~12 关）

9 列 × 7 行 = 63 格，4 色（红黄蓝绿）。行列从 1 计。

| 关 | 目标 | 最短 / 预算 | 一直点这一格 | 颜色顺序 | 每步染色格数 |
|---|---|---|---|---|---|
| 1 | 黄 | 1 / 1 | 第2行第5列 | 黄 | 30 |
| 2 | 绿 | 2 / 2 | 第1行第4列 | 蓝 → 绿 | 28 → 42 |
| 3 | 蓝 | 3 / 3 | 第1行第3列 | 红 → 绿 → 蓝 | 7 → 31 → 47 |
| 4 | 绿 | 3 / 3 | 第2行第1列 | 红 → 蓝 → 绿 | 9 → 39 → 55 |
| 5 | 红 | 4 / 4 | 第3行第9列 | 绿 → 黄 → 蓝 → 红 | 8 → 24 → 43 → 56 |
| 6 | 绿 | 4 / 4 | 第3行第3列 | 黄 → 红 → 蓝 → 绿 | 9 → 23 → 37 → 50 |
| 7 | 红 | 4 / 4 | 第2行第6列 | 蓝 → 黄 → 绿 → 红 | 6 → 11 → 35 → 50 |
| 8 | 蓝 | 5 / 5 | 第1行第8列 | 蓝 → 黄 → 绿 → 红 → 蓝 | 12 → 26 → 35 → 49 → 61 |
| 9 | 蓝 | 4 / 4 | 第1行第4列 | 绿 → 红 → 黄 → 蓝 | 6 → 19 → 31 → 50 |
| 10 | 红 | 4 / 4 | 第2行第4列 | 黄 → 绿 → 蓝 → 红 | 7 → 18 → 25 → 50 |
| 11 | 红 | 5 / 5 | 第3行第8列 | 红 → 蓝 → 黄 → 绿 → 红 | 5 → 22 → 34 → 45 → 58 |
| 12 | 绿 | 5 / 5 | 第1行第8列 | 黄 → 蓝 → 黄 → 红 → 绿 | 6 → 23 → 36 → 54 → 61 |

成品图在 `assets/levels/`，逐关对应。

> 想直接看某关的图：`python scripts/pipeline.py --level 8 --out /tmp/out`
> 列出所有已解关卡：`python scripts/pipeline.py --list-levels`

### 关卡会自动更新，不用重装

> **已实装：最新关卡自动更新。** 装过 skill 的人**不用重装、也不用升级** ——
> 以 9 月 19 日才会出的新关卡为例，那天你问一句「第 13 关怎么过」，
> 就会自动同步到这一关，然后照常给答案。想立刻拉一次全量也行：
> `python scripts/pipeline.py --sync-levels`。

它是这么工作的：

- 本地索引里没有这一关时 → 脚本联网取一次远端
  `assets/levels/levels.json`（约 4 KB），版本更新就合并写回本地，
  并把缺的成品图（约 100~200 KB）下载到 `assets/levels/`，然后照常秒回；
- 本地已经有的关卡（1~12 关这种）**完全不联网**，仍是 0.05 秒；
- 断网或远端不可用时**静默降级**：照常走本地索引或完整求解，不会报错；
  失败后冷却 6 小时不再重试，免得离线用户每次都等超时；
- 想手动拉最新：`python scripts/pipeline.py --sync-levels`；
- 想彻底离线：`--no-sync`，或设环境变量 `CB_OFFLINE=1`；
- 自建镜像 / 内网分发：设 `CB_LEVELS_BASE` 指向放 `levels.json` 和成品图的目录。

> 联网只发生在「本地查不到这一关」时，且只访问 `raw.githubusercontent.com` 这一个域名，
> 只写入 `assets/levels/` 这一个目录。

---

## 安装

```bash
git clone https://github.com/yogurt8888/coloring-board-puzzle.git
cd coloring-board-puzzle
pip install -r requirements.txt          # 只有 Pillow
python tools/selfcheck.py                # 自检：环境 / 字体 / 索引 / 求解链路
```

中文字体已经随仓库自带（`assets/fonts/`，SIL OFL-1.1，可自由分发），不需要额外装字体。

**想让它被 agent 自动识别**（而不是每次手动指路）：把整个目录放进该 agent 的技能目录即可，
例如 `~/.workbuddy/skills/`、`~/.claude/skills/`、`.cursor/rules/` 之类；
`SKILL.md` 就是给 agent 读的入口文档。

## 命令行用法

```bash
# 1) 从截图求解（最常用）
python scripts/pipeline.py --img 截图.png --level 13 --target B --budget 5 \
    --expect-cols 9 --expect-rows 7 --out .

# 2) 只报关号，取已解存档（秒回，不重算）
python scripts/pipeline.py --level 8 --out .

# 2b) 本地没有这关时会自动联网同步；也可以手动拉一次远端最新关卡
python scripts/pipeline.py --sync-levels

# 2c) 完全离线（不联网同步）
python scripts/pipeline.py --level 8 --out . --no-sync

# 3) 棋盘已知，只想重出图
python scripts/pipeline.py --board board8.txt --level 8 --out .
```

`--target` 是目标色字母（`R` 红 / `Y` 黄 / `B` 蓝 / `G` 绿），`--budget` 是截图上的剩余步数。
建议始终带上 `--expect-cols 9 --expect-rows 7`：标定偏一行/一列时取色会全错却不会自己报错，
这道校验专门拦它。

跑完会打印一行结论，中间产物在 `<out>/_pipeline/hN/`：

| 文件 | 用途 |
|---|---|
| `<out>/画盘N_通关路线.png` | **交付物，就这一张** |
| `<out>/_pipeline/hN/pipeline_summary.txt` | 一页结论：推荐路线 + 三道校验 + 耗时 |
| `<out>/_pipeline/hN/boardN.txt` | 取色得到的棋盘，可留档复用 |

---

## 它凭什么可信：三道校验

| 校验 | 做法 | 不通过的后果 |
|---|---|---|
| 双实现对账 | 两套**独立**实现（组件图状态 BFS / 格子级洪水填充）分别算「最短步数 + 可点格数」，必须相同 | 立即中止，不交付 |
| 最短性证明 | BFS 只穷举 `≤ L-1` 步，确认没有更短的走法 | 说明同格法不是最优，中止 |
| 成品反查 | 从最终 PNG **逐格取色**，核对每一帧盘面与圆圈（圈色 = 该步画笔色，圈心偏移 ≤ 6px） | 立即中止 |

任一道不过，脚本非零退出并在简报里写明卡在哪。前两道保证"算得对"，第三道保证"画得对"。

## 核心机制

选一个画笔颜色 → 点棋盘上某一格 → **该格所在的整块连通同色区**全部变成画笔色。

关键认知：**区域被并大之后，再点"同一格"，染的是那块「长大了的区域」**。
所以最优解几乎总是「选定一格，一直点它，只轮换画笔颜色」（等价于从该格做 Flood-It 洪水填充）。
这就是为什么"7 个色块只给 4 步"往往是够的 —— 不等于每步只能染一块。

---

## 目录结构

```
├── README.md                  ← 你正在看的
├── SKILL.md                   ← 给 AI 的完整作业指令（agent 读它）
├── CONTRIBUTING.md            ← 维护指南（加新关卡 / 改版式 / 发布）
├── requirements.txt           ← Pillow
├── scripts/
│   ├── pipeline.py            ← 唯一入口：标定→求解→复核→出图→反查
│   ├── board_tool.py          ← 截图标定 + 逐格取色（跨平台判据，不依赖缝隙颜色）
│   ├── solve_fast.py          ← 首选求解器（组件图状态 + 同格法枚举 + 最短性证明）
│   ├── crosscheck.py          ← 独立复核器（另一套实现）
│   ├── render_delivery.py     ← 统一版式交付图渲染
│   ├── verify_render.py       ← 成品像素级反查（盘面 + 圈）
│   ├── level_index.py         ← 已解关卡索引：查关 / 指纹匹配 / 远端同步
│   └── solve.py               ← 早期实现，仅留档
├── assets/
│   ├── fonts/                 ← 自带中文字体（OFL-1.1）+ 许可原文
│   └── levels/                ← 12 关成品图 + levels.json 索引
├── examples/                  ← 12 关棋盘存档（board_level1..12.txt）
├── tools/
│   ├── selfcheck.py           ← 自检：环境 / 字体 / 索引 / 三道校验
│   ├── build_level_index.py   ← 从棋盘现算并重建关卡索引
│   └── make_font_subset.py    ← 复现自带中文字体
└── references/
    ├── dev-machine-notes.md   ← 开发者本机备注（使用时不必看）
    └── methodology.md         ← 求解器的设计取舍与踩过的坑
```

## 适配别的同类游戏

棋盘尺寸、颜色数、关卡布局都不写死：`board_tool.py` 自动标定行列与格距，
求解器按连通块工作。只要游戏规则是「点一格，整块连通同色区变色」，就能直接用；
换棋盘尺寸只需改 `--expect-cols/--expect-rows`。

---

## 授权

- **代码**：MIT，见 `LICENSE`。
- **自带字体** `assets/fonts/CBBoardSans-*.ttf`：由 Google 的 Noto Sans SC 子集化并改名而来，
  遵循 SIL Open Font License 1.1，许可原文见 `assets/fonts/OFL.txt`。
  按 OFL 要求，修改后的字体不得沿用原名，故改名为 CBBoardSans；再分发时请一并保留 `OFL.txt`。

---

维护 / 二次开发（加新关卡、改交付版式、发新版本）：见 `CONTRIBUTING.md`。

