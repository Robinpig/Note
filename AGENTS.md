# AGENTS.md

面向 AI Agent 的项目说明。修改本仓库前请先读这一页。

## 项目是什么

`Note` 是**个人计算机知识库**，同一份 Markdown 有两种使用形态：

1. **docsify 站点**：根目录 `index.html` 是站点入口与全部配置，`README.md` 是首页，内容全部在 `docs/`，通过 GitHub Pages 发布。
2. **Obsidian vault**：本机通常存在 `.obsidian/`（不入库），日常用 Obsidian 编辑，靠双向链接导航。

硬约束：**文件名与目录名就是笔记标识**（重命名/移动会同时打断 Obsidian 双链和 docsify 绝对路径链接）；**笔记必须同时满足 docsify 渲染和 Obsidian 阅读**。

**不要在文档里写任何文件总数或目录篇数**——`README.md`、`docs/CS/CS.md`、本文件一律不标注，新增/删除不需要回头改数字。需要精确值时现场跑脚本（见「常见任务」）。

## 环境约定

本仓库会在**多台机器、多个 IDE Agent** 下被读取，刻意不绑定操作系统、绝对路径、也不绑定某台机器的现状：

- **命令一律写成 POSIX shell**（macOS / Linux 直接可用）；Windows 下用 Git Bash / WSL 执行或改写。**不要把本文件里的命令当成"只在我这台机器上验证过的脚本"**。
- **`python3` 是"仓库约定的 Python 解释器"的写法**，Windows 上换成 `python` 或 `py -3` 即可。
- **只用相对路径**，一律相对**仓库根目录**；不要假定仓库被克隆到哪里，也不要写死任何用户目录。
- **不要假定本机存在任何东西**（内核源码树、缓存、已装工具、上一次会话的产物）：需要时先 `ls` 确认，不存在就走远程端点、或按语义手工核对。
- **不要假定任何 IDE 专有目录存在**：`.claude/`、`.cursor/`、`.vscode/`、`.obsidian/`、`.workbuddy/` 都只是**本机工具目录且不入版本控制**（见 `.gitignore`）。**本文件是所有 Agent 的唯一说明来源**，不要另建 IDE 专有指令文件（`CLAUDE.md`、`.cursorrules` 之类）。
- **凡是带"实测"字样的结论都带环境前提**（网络可达性、源码版本、工具行为），换机器或换网络需重测。

## 目录地图

```
Note/
├── index.html          docsify 入口 + 全站配置（插件、主题、首页 CSS）
├── README.md           站点首页（同时也是 GitHub 仓库首页）—— 只做总入口
├── AGENTS.md           本文件
├── scripts/            质量门禁脚本（`kb-check.sh` + 校验工具，**随仓库入库**）
├── .github/workflows/  CI 定义（已入库，调用 `scripts/` 下的同一批脚本）
├── docs/               全部笔记内容
│   ├── CS/             CS 主体
│   ├── Mathematics/    分支学科枢纽页 + 各分支
│   ├── Medicine/       医学与护理学
│   ├── Psychology/     分支学科枢纽页 + 各分支
│   ├── Philosophy/
│   ├── Economics/
│   └── Sports/         运动生理学与训练应用
└── out/                IDE 编译产物副本 —— 只读，不要改（本机、不入库）
```

其余文件（`src/`、`wiki/`、`knowledge-base/`、`outputs/`）是忽略占位，不要改；根目录散落的 `电源管理-v7.2-事实清单.md`、`k3cfg.json` 等不是笔记，不要据此推断目录结构。

**CS 子树主要入口**：

| 领域 | 目录 | 入口 |
| :--- | :--- | :--- |
| 操作系统 | `CS/OS/` | `OS.md` |
| Linux 内核 | `CS/OS/Linux/` | `Linux.md`（**唯一枢纽，不要改名**） |
| 框架与中间件 | `CS/Framework/` | `Framework/README.md`（**无 Framework.md**） |
| Java | `CS/Java/` | `Java.md`（语言）+ `JDK/JDK.md`（内部机制） |
| 数据库 | `CS/DB/` | `DB.md` |
| 分布式 | `CS/Distributed/` | `Distributed.md` |
| 计算机网络 | `CS/CN/` | `CN.md` |
| 软件工程 | `CS/SE/` | `Engineering.md`（**无 SE.md**） |
| 云原生 | `CS/Container/` | `Container.md` |
| 人工智能 | `CS/AI/` | `AI.md`；`LLM/` 子树入口 `LLM.md` |
| 推荐系统 | `CS/RecommenderSystem/` | `RecommenderSystem.md` |
| 消息队列 | `CS/MQ/` | `MQ.md` |
| Golang | `CS/Go/` | `Go.md` |
| Python | `CS/Python/` | `Python.md` + `README.md` |

较小目录（`CO/`、`C/`、`Compiler/`、`BuildTool/`、`Tool/`、`front-end/` 等）详见 `docs/CS/CS.md`。跨领域索引页：`CS/CS.md`（CS 总纲 + 全部主题目录清单，**不要在其它地方重复 CS 主题列表**）、`CS/term.md`（术语表）、`CS/Languages.md`（语言横向对比）。

**首页与总纲的分工**：`README.md` 只做**总入口**（学习路径 + 各领域卡片），不放任何 CS 主题清单；`docs/CS/CS.md` 是 CS 的**唯一目录来源**。

## 各领域组织规则指针

本子树或领域的专属组织规则、核实口径、反模式清单等，**就近存放于该子树的枢纽页末尾**，不在本文件重复：

| 子树 / 领域 | 规则存放位置 |
| :--- | :--- |
| Linux 内核 | `CS/OS/Linux/Linux.md` → `## Subtree Organization` |
| Higress | `CS/Framework/Higress/Higress.md`（`Introduction` + `Three Threads`，已含版本锚点、已证伪清单、核实口径） |
| 医学 / 护理学 | `Medicine/Medicine.md` → `## Organization Conventions` |
| 运动学三专题 | `Sports/Sports.md` → `## Organization Conventions` |

**通用组织原则**（适用于所有子树）：

- 新增子目录后**必须回本领域枢纽页挂入口**。
- 枢纽页导航**禁止两列表格形式**的笔记索引，必须写成有因果递进的叙述性章节（讲清为什么需要它、与相邻笔记的关系）。
- 同一结论**只有归属分册可以展开写**，其它页只链接不重述。

## 渲染管线

docsify 4.x，主题 `docsify-darklight-theme` + `themes/vue.css`。

已加载插件：搜索、图片缩放、字数统计、上下页、flexible-alerts、tabs、copy-code、hide-code、remote-markdown、footer、progress、share、sidebar-collapse、link-preview、emoji、slides、sequence-diagram、puml、plantuml、katex。

**没有页内目录**（`docsify-toc` 已整体移除）。**不做站点级侧边栏**（`loadSidebar: false` 是既定设计，`_sidebar.md` 不生成）。全站导航靠首页目录树（`README.md` + `docs/CS/CS.md`）+ 每篇笔记末尾的 `## Links`。

Markdown 增强写法：
- 公式：` ```tex ` → KaTeX 渲染
- 图：` ```dot ` → Graphviz；` ```sequence ` → 时序图；` ```puml ` → PlantUML
- 提示块：`> [!NOTE]` / `[!TIP]` / `[!WARNING]`（flexible-alerts）
- 标签页：docsify-tabs 语法

首页专用 CSS 写在 `index.html` 的 `<style>` 里（选择器 `.kb-home`），不要塞进 Markdown。

## 笔记写作规范

1. **结构顺序**：`## Introduction` → 正文 → `## Links` → `## References`。正文不内嵌「来源：…」引用块。
2. **内容标题一律英文**：除固定骨架（`Introduction` / `Links` / `References`，不得汉化）外，正文小节标题一律英文；正文保持中文、代码/配置名/产品名保留英文、References 保留原文。
   - **系统/算法/产品专有名词**原样保留（如 `## GFS`、`## Paxos`、`qspinlock`），不要"译成中文+附英文"。
   - **描述性概念**译成英文（如 `## 消息代理` → `## Message Brokers`），同一概念在不同文件**译名必须一致**。
   - 代码块内的 `#` / `//` 注释不算标题，保持中文。
   - **被 `?id=` 引用的标题不要带半角括号**（会被 markdown 链接截断）；改动标题前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就同步修。
   - 批量改标题的核心流程（6000+ 条已跑通，**不要简化**）：脚本按文件替换标题行（跳过代码块）→ 收集 `old_slug → new_slug` 映射 → **按「目标文件路径 + 旧 slug」作用域**同步 `?id=`（**绝不能无作用域全局替换**，否则误伤其它文件同名标题）→ 校验 `BAD ANCHOR = 0`。
3. **站内链接**用 docsify 绝对路径（示例 `/docs/CS/OS/Linux/proc/process.md`）；锚点用 `?id=slug`。
4. **slug 规则**：`[A-Z]+` → 小写，删半角标点，全角标点（`：（）、→`）保留，空白转 `-`，数字开头前缀 `_`。算不准直接跑：
   ```bash
   python3 -c "import sys;sys.path.insert(0,'scripts');from validate_links import slugify;print(slugify('标题'))"
   ```
5. **`## Links`** 放 1~6 条最相关**站内**笔记，只写一行带真实 docsify 绝对路径的列表项，不加后缀说明；正文里已出现过的内部链接不重复列入。
6. **`## References`** 位于全文最后，放外部文章/论文/官方文档，每条一行标题加链接。KEP/RFC/issue 编号必须核实再写。
7. 代码片段保持原样，中文解释写在代码块外。图片放同目录或上级 `img/`。对比与选型优先用 Markdown 表格。

## 修改前必读的禁区

- **不要重命名或移动 `docs/` 下已有文件/目录**。确需移动时走完整流程（`git mv` → 全库替换 → 复核 → 回枢纽挂入口 → 死链扫描），并告知用户外链有 404 风险。
- **不要修改** `out/`、`src/`、`wiki/`、`knowledge-base/`、`outputs/`。
- `index.html` 只动配置和样式区块，**不要重排脚本加载顺序**（插件依赖 docsify 主脚本先加载）。
- `.obsidian/`、`.claude/`、`.workbuddy/` 是**本机工具目录，不入版本控制**，不要依赖、也不要删。
- 新增链接前先确认目标文件存在。以下目录的入口**不等于目录名**：
  - `CS/BuildTool/` → `BuildTools.md`
  - `CS/Tool/` → 无 `Tool.md`，代表文件 `Vim.md`
  - `CS/front-end/` → 无 `front-end.md`，代表文件 `Nodejs.md`
  - `CS/Java/` → 两级入口：`Java.md`（语言）+ `JDK/JDK.md`（内部机制）
  - `CS/SE/` → `Engineering.md`
  - `CS/Framework/` → 无 `Framework.md`，总入口 `Framework/README.md`
  - `docs/Test.md` 是测试页，可忽略

## 校验工具（`scripts/`）

脚本已随仓库入库（之前在 `.workbuddy/tools/`，CI 拿不到），仓库根一律由自身位置推导，可在任意 cwd 下调用。

| 脚本 | 用途 | 用法 |
| :--- | :--- | :--- |
| `kb-check.sh` | **一键全量门禁**：链接校验 + 密度门禁 + 全库 dot 校验 + CDN 可达性（仅告警） | `bash scripts/kb-check.sh` |
| `validate_links.py` | **主力校验**：死链 DEAD / 坏锚点 BAD ANCHOR / 相对链接 RELATIVE / 西里尔字母 CYRILLIC（均致命）+ 中英夹杂 GARBLED（告警） | `python3 scripts/validate_links.py <file\|dir>` |
| `analyze_crosslinks.py` | 量化链入/链出、孤立页、弱链出页；`--gate` 做密度门禁。**目录只能用 `--root`/`--dirs` 传** | `python3 scripts/analyze_crosslinks.py --root docs/CS/Framework` |
| `check_dot.js` | 复现 dot 图渲染，防 Graphviz 语法错误导致白屏（需 node） | `node scripts/check_dot.js <dir>` |
| `check_cdn.sh` | 逐条验证外部资源可达 | `bash scripts/check_cdn.sh` |
| `fix_garbled.py` | 修 `validate_links.py` 报的 GARBLED（CJK 与 Latin 边界补空格） | `python3 scripts/fix_garbled.py <file>` |
| `find_hub_gaps.py` | 定位 hub 页 `## Links` 中未链到的子笔记 | `python3 scripts/find_hub_gaps.py` |
| `fix_framework_hublinks.py` | 框架内 hub 页 Links 补齐（阶段①，消除孤立页） | `python3 scripts/fix_framework_hublinks.py` |
| `fix_framework_crosslinks.py` | 跨框架双向链接矩阵（阶段②） | `python3 scripts/fix_framework_crosslinks.py` |

`validate_links.py` 选项：`--verbose` 逐行打印 GARBLED 告警，`--strict` 把 GARBLED 也当致命；`import` 可取出 `slugify()`。

> [!WARNING]
>
> `analyze_crosslinks.py --gate` 失败时**退出码为 1**，写 shell 门禁脚本时务必显式检查每一步的退出码（`set -e` 只看最后一条命令）。`scripts/kb-check.sh` 用 `check()` 包装函数处理，改脚本时务必保留该包装。

**CI 与本地范围不同**：`.github/workflows/ci.yml` 只跑 Framework + Linux 的链接校验与密度门禁；`kb-check.sh` 额外跑 MQ 校验和全库 dot 校验。

**站点白屏排查**（外部依赖挂 `cdn.jsdelivr.net`，不要用 `unpkg.com` 或 `cdn.staticfile.org`）：

1. `bash scripts/check_cdn.sh` —— 外部资源是否都 200。这是最常见原因（docsify 原本挂 unpkg，2026-10 实测 unpkg + staticfile 都连不上 → 整站白屏，但内容校验全绿）。
2. `bash scripts/kb-check.sh` —— 才是内容层面（死链 / dot 图语法）。

⚠️ 不要用 headless Chrome 验证这个站点，viz.js（2.4MB）会挂死数分钟。

## 常见任务

**统计各目录篇数**
```bash
for d in docs/CS/*/; do printf "%-24s %s\n" "${d#docs/CS/}" "$(find "$d" -name '*.md' | wc -l)"; done | sort -k2 -rn
```

**新增一篇笔记**
1. 确定归属目录，文件名用术语英文名（同目录内保持风格一致）。
2. 按「笔记写作规范」写正文，结尾补 `## Links` 与 `## References`。
3. 挂进索引：所属目录的 `README.md` 或父级入口页的叙述性章节 / 表格。
4. 在相关笔记的 `## Links` 里补回链。
5. 跑校验（`validate_links.py` + 死链扫描）。

**本地预览**
```bash
python3 -m http.server 8899   # 打开 http://127.0.0.1:8899/index.html
```

**死链快速扫描**（路径必须 `unquote`，否则含 `%20` 的路径全误报）
```bash
grep -rhoE '/docs/[^)` ]+\.md' docs README.md | sort -u | python3 -c "
import sys, os, urllib.parse as u
for line in sys.stdin:
    p = u.unquote(line.strip())
    if not os.path.isfile('.' + p): print('BROKEN:', p)
"
```

## Open Gaps

全库仍有若干主题零覆盖（DAMON、dm-crypt / LUKS、md / RAID、kTLS、Landlock），部分主题偏薄（livepatch、kdump、pidfd、psi、MPTCP）。定时任务主题的缺口（Python / Rust / C++ 定时器、Go 运行时深处、K8s CronJob、crontab / systemd timer）单独记在 `docs/CS/SE/Scheduled_Task.md` 的 Open Gaps 一节，**以那里为准，不在本文件重复列**。
