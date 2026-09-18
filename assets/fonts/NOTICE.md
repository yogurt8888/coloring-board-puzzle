# 自带字体说明与授权

## 文件

| 文件 | 说明 |
|---|---|
| `CBBoardSans-Regular.ttf` | 正文用（标题、步骤说明、注释） |
| `CBBoardSans-Bold.ttf` | 加粗用（关卡标签、`最优解：N 步`、每步表头） |
| `OFL.txt` | SIL Open Font License 1.1 许可原文 |

## 来源与修改

- 上游字体：**Noto Sans SC**（Google / notofonts），许可 **SIL Open Font License 1.1**。
- 本仓库内的两份文件是它的**子集化衍生版本**，改动如下：
  1. 只保留交付图可能用到的字符（ASCII + GB2312 全部汉字与中文标点 + 常用符号，共约 7500 字）；
  2. 去掉 hinting、OpenType layout 特性与 DSIG；
  3. 按 OFL 对"修改版不得沿用保留字体名（Reserved Font Name）"的要求，
     将内部 name 表改名为 **CBBoardSans**。
- 复现脚本：`tools/make_font_subset.py`（需要 `pip install fontTools`）。

## 为什么自带字体

交付图上全是中文，渲染必须依赖一个真实的中文字体：

- Windows 的微软雅黑等系统字体**允许使用但禁止随软件再分发**，不能放进公开仓库；
- macOS / Linux 系统字体名与路径各异，写死路径必然在别的机器上崩掉。

所以仓库自带一份体积可控（各约 1.5 MB）且**明确允许再分发**的中文字体，
渲染器按「自带字体 → 环境变量 `CB_FONT_REGULAR` / `CB_FONT_BOLD` → 系统常见中文字体」的顺序解析。

## 再分发要求

再分发本项目（或其中字体）时，请一并保留 `OFL.txt` 与本文档，
且不要把这些字体改回 `Noto Sans SC` 之类的保留名称使用。
