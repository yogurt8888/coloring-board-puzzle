# 开发机（本机）专用备注

这份是**开发者本机**（Windows + WorkBuddy）的环境细节，跟技能本身的算法无关。
换台机器、换一个 agent 用这个技能时，**不需要看这篇**；只有在同一台机器上继续开发才用得上。

## Python 与依赖

- 用托管版解释器：`C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe`（已装 Pillow）。
- 子集化字体需要额外装 `fontTools`（只有重建字体时才用得到，交付链路不需要）。

## 工具行为（WorkBuddy 特有）

- **PowerShell 工具不返回原生命令的 stdout**（连 `python --version` 都只给 exit code）：
  让脚本自己 `open(path,"w",encoding="utf-8")` 写报告，再用 Read 读那个文件。
- **Bash 工具是可用的**（2026-09-18 实测修正：此前"Bash 不可用"的结论是错的）。
  它能回显 stdout，所以 `... pipeline.py ... && cat summary.txt` 能把"跑完 + 读结论"并成一次调用 ——
  这正是把单关交付从 5~10 分钟压到 1~2 分钟的关键。**优先用 Bash 跑流水线**。
- `Out-File -Encoding utf8` / `Set-Content -Encoding UTF8` 会让中文变成乱码（双重编码），
  需要看中文时用脚本自己写 UTF-8，或 `Set-Content -Encoding UTF8` 后再用 Read 工具读。

## 文件系统

- **删文件会被 safe-delete 钩子拦下**：`Remove-Item` 走回收站，对**含中文的路径**会失败
  （`[safe-delete][SAFE_DELETE_FAIL_CLOSED] ... trash-failed`），而且**报 FAIL 但文件其实已经删掉了** ——
  删完必须 `Test-Path` 复核一次。
- 想保留的东西别删，改成 `Move-Item` 到工作区的 `分析过程/` 归档目录，移动不会被拦。
- 交付物与中间件的固定落点见工作区记忆：`<out>/画盘N_通关路线.png`，
  中间件 `<out>/_pipeline/hN/`（keep，别删）。

## 本机渲染字体

- 交付图**默认用仓库自带的 `assets/fonts/CBBoardSans-*.ttf`**，不再依赖 `C:/Windows/Fonts/msyh.ttc`。
- 微软雅黑**允许个人使用但不可随软件再分发**，所以不能放进公开仓库；
  仓库里那份是由 Noto Sans SC（SIL OFL-1.1）子集化并按 OFL 要求改名而来，复现脚本见
  `tools/make_font_subset.py`。
- 想临时用系统字体对比效果：`CB_FONT_REGULAR="C:/Windows/Fonts/msyh.ttc"`。
