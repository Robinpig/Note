# AGENTS.md

面向 AI Agent 的项目说明。修改本仓库前请先读这一页。

## 项目是什么

`Note` 是**个人计算机知识库**，同一份 Markdown 有两种使用形态：

1. **docsify 站点**：根目录 `index.html` 是站点入口与全部配置，`README.md` 是首页，内容全部在 `docs/`，通过 GitHub Pages 发布（仓库 `Robinpig/Note`，`.nojekyll` 保证下划线目录不被 Jekyll 吞掉）。
2. **Obsidian vault**：本机通常存在 `.obsidian/`（**不入库**，别的机器上可能没有），日常用 Obsidian 编辑，靠双向链接导航。

因此有两条硬约束：**文件名与目录名就是笔记标识**（重命名/移动会同时打断 Obsidian 双链和 docsify 绝对路径链接）；**笔记必须同时满足 docsify 渲染和 Obsidian 阅读**。

规模：`docs/` 下约千篇 Markdown，七大领域，`CS/` 是绝对主体。

**不要在文档里写任何文件总数或目录篇数**：`README.md`、`docs/CS/CS.md`、本文件一律不标注篇数，新增/删除笔记不需要回头改数字。需要精确值时现场跑脚本（见「统计各目录篇数」）。

## 环境约定（跨机器 / 跨 IDE / 跨系统）

本仓库会在**多台机器、多个 IDE Agent** 下被读取，所以本文件**刻意不绑定操作系统、绝对路径、也不绑定某台机器的现状**。读到下面内容时按这几条解读：

- **命令一律写成 POSIX shell**（macOS / Linux 直接可用）。Windows 下用 Git Bash / WSL 执行，或自行改写成等价命令；**不要把本文件里的命令当成"只在我这台机器上验证过的脚本"**。
- **`python3` 是"仓库约定的 Python 解释器"的写法**，不是硬性要求：Windows 上通常是 `python` 或 `py -3`，按本机情况替换即可。`scripts/kb-check.sh` 支持用 `PY=` / `NODE=` 覆盖解释器。
- **只用相对路径**，一律相对**仓库根目录**；不要假定仓库被克隆到哪里，也不要写死任何用户目录。
- **不要假定本机存在任何东西**（内核源码树、缓存、已装工具、上一次会话的产物）：需要时先 `ls` 确认，不存在就走远程端点、或按语义手工核对。
- **不要假定任何 IDE 专有目录存在**：`.claude/`、`.cursor/`、`.vscode/`、`.obsidian/`、`.workbuddy/` 都只是**本机工具目录且不入版本控制**（见 `.gitignore`）；本仓库的校验脚本**已随仓库入库在 `scripts/`**，不要依赖任何本机目录。**本文件是所有 Agent 的唯一说明来源**，不要另建 IDE 专有指令文件（`CLAUDE.md`、`.cursorrules`、`copilot-instructions.md` 之类）来各写一份。
- **凡是带"实测"字样的结论都带环境前提**（网络可达性、源码版本、工具行为）：换机器或换网络需重测。当"某台机器上一次成立"读，不要当永久事实。
- 本文件里**不记任何会随内容变化的快照数字**（篇数、平均链入、孤立页数）——需要时现场跑脚本。

## 目录地图

```
Note/
├── index.html          docsify 入口 + 全站配置（插件、主题、首页 CSS）
├── README.md           站点首页（同时也是 GitHub 仓库首页）—— 只做总入口：学习路径 + 各大领域入口
├── AGENTS.md           本文件
├── scripts/            质量门禁脚本（`kb-check.sh` + 校验工具，**随仓库入库**，见「校验工具」）
├── .github/workflows/  CI 定义（已入库，调用 `scripts/` 下的同一批脚本）
├── .workbuddy/         本机目录：仅 Agent 记忆（**不入库**，换机器可能没有）
├── docs/               全部笔记内容
│   ├── CS/             CS 主体
│   ├── Mathematics/    分支学科枢纽页 + 各分支
│   ├── Medicine/       医学与护理学：学科框架为主，见下节
│   ├── Psychology/     分支学科枢纽页 + 各分支
│   ├── Philosophy/
│   ├── Economics/
│   └── Sports/         Philosophy/Economics/Sports 为少量读书摘录
├── out/                IDE 编译产物副本 —— 只读，不要改（本机、不入库）
├── src/                忽略，不要改
└── wiki/、knowledge-base/、outputs/   空占位，不要改
```

仓库根另有几个**与知识库正文无关的散落文件**（`电源管理-v7.2-事实清单.md`、`.verify-v7.2-btrfs-fuse.md` 是写作期的事实核实清单；`k3cfg.json` 疑似误提交，与本库无关）——**不要把它们当笔记读，也不要据此推断目录结构**。

`docs/CS/` 下按主题分目录（另有 `img/` 存放配图，不算笔记）。主要子树与入口：

| 领域       | 目录                | 入口与说明                                                                                          |
| :------- | :---------------- | :--------------------------------------------------------------------------------------------- |
| 操作系统     | `CS/OS/`          | [OS.md](/docs/CS/OS/OS.md)；下辖 `Linux/`、`unix/`、`Windows/`、`mac/`、`Android/`、`xv6/`、`Fuchsia/`、`Book/`、`Boot/`（仅 `Grub.md`） |
| Linux 内核 | `CS/OS/Linux/`    | [Linux.md](/docs/CS/OS/Linux/Linux.md) 是该子树的**唯一枢纽**，见下节                                   |
| 框架与中间件   | `CS/Framework/`   | 总入口 [Framework/README.md](/docs/CS/Framework/README.md)（按 Java 体系 / 协调与服务注册 / 服务治理 / 网络与 RPC / 网格与网关 / 计算与数据 / 响应式 / 跨语言与 AI 分层）；**无 `Framework.md`**，具体机制仍在各框架子目录 |
| Java     | `CS/Java/`        | 语言入口与目录地图 [Java.md](/docs/CS/Java/Java.md)；JDK 与 JVM 内部机制的枢纽仍是 [JDK/JDK.md](/docs/CS/Java/JDK/JDK.md) |
| 数据库      | `CS/DB/`          | [DB.md](/docs/CS/DB/DB.md)                                                                     |
| 算法       | `CS/Algorithms/`  | [Algorithms.md](/docs/CS/Algorithms/Algorithms.md)                                             |
| 分布式      | `CS/Distributed/` | [Distributed.md](/docs/CS/Distributed/Distributed.md)                                          |
| 计算机网络    | `CS/CN/`          | [CN.md](/docs/CS/CN/CN.md)                                                                     |
| 软件工程     | `CS/SE/`          | 入口 [Engineering.md](/docs/CS/SE/Engineering.md)（`SE/SE.md` 不存在）                               |
| 云原生      | `CS/Container/`   | [Container.md](/docs/CS/Container/Container.md)（`Docker/`、`k8s/`）                              |
| 人工智能     | `CS/AI/`          | [AI.md](/docs/CS/AI/AI.md)；`LLM/` 是 agent 平台专题，入口 [LLM.md](/docs/CS/AI/LLM/LLM.md)；`NLP/`      |
| 推荐系统     | `CS/RecommenderSystem/` | [RecommenderSystem.md](/docs/CS/RecommenderSystem/RecommenderSystem.md)；召回、排序、冷启动、偏差、评估、在线架构、广告（**不是 `AI/` 的子目录**） |
| 消息队列     | `CS/MQ/`          | [MQ.md](/docs/CS/MQ/MQ.md)                                                                     |
| Golang   | `CS/Go/`          | [Go.md](/docs/CS/Go/Go.md)                                                                     |
| Python   | `CS/Python/`      | 语言入口 [Python.md](/docs/CS/Python/Python.md) + 知识地图 [Python/README.md](/docs/CS/Python/README.md)；**无子目录**，运行时层三篇 `GIL.md` / `Memory.md` / `Bytecode.md` 是这一子树的骨架，工程层 `Typing.md` / `Packaging.md` / `Performance.md` |

其余较小目录：`CO/`（组成原理）、`C/`、`C++/`、`Rust/`、`Scala/`、`TypeScript/`、`Dart/`、`assembly/`、`memory/`、`Compiler/`、`BuildTool/`（入口 `BuildTools.md`）、`Tool/`（**无 Tool.md**，代表文件 `Vim.md`）、`front-end/`（**无 front-end.md**，代表文件 `Nodejs.md`）、`Browser/`、`DesignPatterns/`、`VCS/`、`log/`、`compress/`、`Cloud/`、`BigData/`、`Blockchain/`、`Security/`、`GNU/`。

`docs/CS/Flutter.md` 是**没有同名目录的孤立文件**，不要误以为存在 `CS/Flutter/`。

跨领域索引页：`docs/CS/CS.md`（CS 总纲 + 全部主题目录清单）、`docs/CS/term.md`（术语表）、`docs/CS/Languages.md`（语言横向对比）。各目录下的 `README.md` 会被 docsify 当作该目录首页（如 `CS/OS/Linux/proc/README.md` 是进程知识地图）。

**首页与总纲的分工**：`README.md` 只做**总入口**（学习路径 + 各领域卡片，每个领域一张独立卡片，不合并），不放任何 CS 主题清单；`docs/CS/CS.md` 是 CS 的**唯一目录来源**（主题卡片 + 主题目录全展开 + 各学科定义）。不要在两处各写一份主题列表。

## 医学 / 护理学笔记的组织（`docs/Medicine/`）

2026-10 新增的第七领域，与 `Psychology/` 同为「分支学科枢纽页 + 各分支页」结构：

- `Medicine/Medicine.md` 是该领域**唯一总纲**；分支页为 `Basic_Medicine.md`、`Clinical_Medicine.md`、`Diagnosis.md`、`Public_Health.md`、`Medical_History_Ethics.md`。
- 护理学是**唯一有子目录**的分支：`Medicine/Nursing/` 下 `Nursing.md`（总纲）+ 11 篇分支页，按**基础层 / 场景层 / 延伸层**三层组织——基础层 `Nursing_Fundamentals.md`；场景层 `Clinical_Nursing.md`、`Maternal_Pediatric_Nursing.md`、`Psychiatric_Nursing.md`、`OR_Sterile_Supply.md`、`Emergency_Disaster_Nursing.md`、`Palliative_Care.md`、`Gerontological_Nursing.md`；延伸层 `Community_Home_Nursing.md`、`Nursing_Research_Education.md`、`Nursing_Informatics.md`；`Nursing_Management_Ethics.md` 贯穿全部。新增护理学内容一律放 `Nursing/`，不要在 `Medicine/` 根下平铺。
- **护理学已有第二个子目录**：`Nursing/Cardiovascular/`（2026-10 新增，8 篇），是**第一个「专科深化层」**——示范单个科室的疾病谱如何再展开。结构为 `Cardiovascular_Care.md`（总纲，含**三条贯穿主线：缺血与灌注 / 容量与压力 / 节律与电**）+ 7 篇疾病页（`Coronary_Heart_Disease.md`、`Heart_Failure.md`、`Arrhythmia.md`、`Hypertension.md`、`Valvular_Heart_Disease.md`、`Cardiomyopathy_Myocarditis.md`、`Pericardial_Disease.md`）。后续若深化其他科室（如呼吸科、消化科、糖尿病），**照此结构新建 `Nursing/<Specialty>/`，不要平铺进 `Nursing/`**。
- ⚠️ **医学 × CS 的固定交叉点**：`Nursing/Nursing_Informatics.md` 是本库医学与计算机科学**最直接**的交叉页（决策支持、远程护理、可穿戴、AI 辅助），链向 `CS/AI/AI.md` 与 `CS/AI/LLM/LLM.md`。写 AI 相关医学内容时**从这篇转链**，不要重复叙述 AI 原理。
- ⚠️ **内容口径：学科框架为主，谨慎写临床细节**。剂量、诊疗路径、指南推荐等级、各类指标阈值、给药方案与器械参数**不收录**——它们随指南更新而变化，写死必然过时且有出错风险。需要时只写「关注点与判断逻辑」，并在页首用 `> [!WARNING]` 块声明「不收录具体规程，以最新指南与机构规范为准」。
- ⚠️ 医学笔记用**中文术语 + 英文原名**（如「循证医学（evidence-based medicine）」首次出现时），这是本库其他领域（CS/哲学/心理学）一致的做法。
- 医学与本库其他领域的固定交叉点：`Sports/Anatomy.md`（解剖）、`Psychology/Biological_Psychology.md`（生理基础）、`Philosophy/Ethics.md`（伦理四原则的哲学源流）、`Mathematics/Probability_Statistics.md`（研究设计与统计推断）、`CS/AI/AI.md`（AI 辅助决策的算法责任）。新增医学页时优先链到这些已有页，不要重复新建。

## Linux 内核笔记的组织（当前主力方向）

`docs/CS/OS/Linux/` 是全库最活跃的子树，组织规则容易踩错：

- **`Linux/Linux.md` 是唯一枢纽**，全库被引最多的文件，**不要改名**（`Linux/` 下没有 `README.md` 是全库常态——很多目录都缺，别顺手新建）。
- **`Linux/` 根目录放横切机制**（不属于单一子系统）：`Interrupt.md`、`Calls.md`、`timer.md`、`workqueue.md`、`LXC.md` / `namespace.md` / `cgroup.md` / `SELinux.md`、`KVM.md`、`Swap.md`、`ZeroCopy.md`、`performance.md`、`Architecture.md`、`Experience.md`、`build.md`。
- **子系统各建子目录**：`proc/`（进程/调度/信号/IPC）、`mm/`、`fs/`、`net/`、`IO/`、`Lock/`、`dev/`、`boot/`（启动链）、`module/`、`struct/`（内核数据结构）、`Tools/`、`Distribution/`。
- **较新的两个子目录**（2026-10 新增，各有独立 README 枢纽）：`cgroup/`（v2 三篇：知识地图 / 控制器接口 / 委派实践；根目录的 `cgroup.md` 保留为 **v1 视角**入口）、`PM/`（电源管理六篇：知识地图 / cpuidle / cpufreq / suspend / runtime PM / devfreq）。
- **新增子目录后必须回 `Linux.md` 挂入口**（踩过：目录迁移完忘了挂，新目录的 README 引用数一度为 0）。
- ⚠️ **`Linux/0.11.md` 讲的是 Linux 自己 1991 年的早期版本**（`bootsect.s` / `setup.s` / `head.S` / `init/main.c`），是现代内核的直系祖先，**不是教学内核**，不要迁到 `OS/` 根或与 xv6 / rCore / osask 并列。
- ⚠️ **`OS/Boot/` 与 `OS/Linux/boot/` 是两个不同目录**：前者只有旧的 `Grub.md`，启动链主题在后者（`README.md` / `Start.md` / `init.md` / `U-Boot.md` / `arm.md` / `crash.md`）。
- ⚠️ `mm/memory.md` 是 **boot 阶段的初始化笔记**，**不是内存子系统总入口**（全站有旧链接把它当 "Linux Memory"，属历史错配）。
- ⚠️ **`struct/struct.md` 只讲 llist**，文件名覆盖面远大于内容，是历史沿用名；`struct/` 的地图以 `struct/README.md` 为准。同理 `Tools/Tools.md`（命令速查表）与 `Tools/README.md`（笔记导航）**不是一回事**。
- ⚠️ **标题避免用全角标点**（如 `## freezer：冻结与终止`）：`validate_links.py` 的 `anchors_of()` 会按全角冒号把标题切成两个锚点，与 docsify 的 `slugify()` 行为不一致，导致 BAD ANCHOR 误报。中英混排标题用**半角空格**分隔（`## freezer 冻结与终止`）。

**内核源码核实**：**先确认本机有没有源码树**——

```bash
ls -d ~/Tools/linux-* ~/src/linux-* /usr/src/linux-* 2>/dev/null
```

有就优先用本地树（`grep` 最快，还能跨文件检索）；没有再走下面的远程端点。

远程端点用 kernel.org 的 `plain` 接口。**tag 必须写 `v7.2`**（真实 tag 就是 `v7.2` = 7.2.0；**`v7.2.7` 不存在**，写错拿到的是 404 HTML，不是源码）：

```bash
K="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain"
curl -sL -m 40 "$K/kernel/panic.c?h=v7.2"          # → 纯文本源码
```

**端点可用性随机器与网络而变，下面只是某次实测记录，换环境必须重测**：`elixir.bootlin.com` 有 Anubis 反爬，`/source`、`?raw=1`、`/A/` 简写、`/api/v1/source/` 都可能返回 **HTTP 200 但正文是一段约 4KB 的 "Making sure you're not a bot!"** —— 人工浏览可用，自动化不可靠。GitHub API 有 403 限流、`raw` 有 429。**所以"是否真拿到了内容"要看 `wc -l` 与首行是不是 `<!DOCTYPE html>`，不要只看 HTTP 状态码。**

**四个必须知道的操作坑**（都实测踩过）：

1. **判断文件是否存在不能只看 `curl -w %{http_code}`** —— 该状态码会因缓存给出过期值（曾把 404 的 2932 字节 HTML 当成正常响应，导致"文件存在"的错误结论，进而引用了不存在的符号）。可靠做法：`wc -l` 看行数 + `head -1` 判断是否 `<!DOCTYPE html>`。
2. **猜路径极易落空，v7.2 大量文件已搬迁/改名**。用 tree 页取真实清单（比 `Makefile` 反推更准，能拿到未被当前配置编译的文件）：
   ```bash
   curl -sL "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/btrfs?h=v7.2" \
     | grep -oE "fs/btrfs/[a-z0-9_-]+\.(h|c)" | sort -u
   ```
   搬迁大户：`kernel/tty.c` → 拆成 `drivers/tty/tty_{io,ioctl,jobctrl,buffer,ldisc}.c`；`kernel/crash.c` → `kernel/crash_core.c` + `crash_reserve.c`；`fs/fuse/fuse.h` → `fuse_i.h` + `dev.h`；`drivers/input/core.c` → `input.c`；`fs/btrfs/*.h` 改**下划线命名**（`block-group.h`/`delayed-ref.h`）。
3. **结构体定义可能不在你以为的头文件里** —— 例如 btrfs 核心定义搬到了 **uapi 头** `include/uapi/linux/btrfs_tree.h`；`struct btrfs_key` 不在 `fs/btrfs/` 下。
4. **大批量 grep 偶发返回空结果**：对确认含目标串的大文件（数千行）执行 `grep` 曾多次返回空，而同样的检索改用专用搜索工具（Grep / ripgrep）或把源码落盘后再 `grep` 却正常。**若 grep 结果与预期矛盾，换检索方式重试，不要据此认定"符号不存在"** —— 这类"不存在"的结论往往正是旧资料里 API 已删除的来源。

**文件命名反推**：某目录的头文件常与 Makefile 里的 `.o` 名同源（下划线）；`/include/uapi/linux/` 下的类型定义优先于私有头。

**API 迁移强度**（v7.x 相较旧资料改动极大，写作时**必须逐个核实符号是否存在**）：`cpuidle_go_billiard()` 已删、`struct suspend_ops`→`platform_suspend_ops`（成员全变）、cpufreq 的 `name` 从函数指针变定长数组且 `target` 已 Deprecated、`pci_iomap*`→`pcim_*`、`struct spi_master`→`spi_controller`、FUSE 的 `FUSE_CAP_*` 去 `CAP_` 中缀且语义翻转、`FUSE_OPT` 宏移除。**凭印象写必错**。

**版本事实陷阱**：sysctl / feature gate **存在 ≠ 它还生效**。判断"当前实际行为"要读**消费方函数读的是哪个变量**以及**默认值代码**，只看 sysctl 表条目或 gate 状态会写出过时结论。同类陷阱还有两条：① 官方文档可能过时于源码（如 kdump.rst 写 "at least 256M" 而 `DEFAULT_CRASH_KERNEL_LOW_SIZE` 已是 128 MiB）——**常量以源码为准**；② 符号"存在 ≠ 仍是原语义"（`FUSE_INIT_RESERVED` 占 bit 31 导致 64 位能力从 bit 32 起）。

**移动笔记的固定流程**：`git mv` → 脚本全库精确替换旧路径 → grep 复核残留 → **回枢纽页补新目录入口** → 全库死链扫描（路径必须 `urllib.parse.unquote`，否则 `%20` 误报）。同时告知用户 GitHub Pages 上被收藏的 URL 有 404 风险。

**所有锁相关笔记统一放 `Linux/Lock/`**，不要在 `Linux/` 根目录新建 `lock.md`（历史撞名已合并）。

## 渲染管线（index.html）

docsify 4.x，主题 `docsify-darklight-theme` + `themes/vue.css`。

已加载插件：搜索、图片缩放、字数统计（docsify-count）、上下页（pagination）、flexible-alerts、tabs、copy-code、hide-code、remote-markdown、footer（footer-enh）、progress、share、sidebar-collapse、link-preview、emoji、slides、sequence-diagram、puml、plantuml、katex。

**没有页内目录**：`docsify-toc` 插件已整体移除（脚本与 `toc` 配置都删了）。导航靠首页目录树 + 每篇笔记末尾的 `## Links`，**不要在 `index.html` 里把它加回来**。

**不做站点级侧边栏**：`loadSidebar: false` 是既定设计（2026-10-02 用户确认）。**不要生成 `_sidebar.md`，也不要打开 `loadSidebar`** —— 全站导航以首页目录树（`README.md` + `docs/CS/CS.md`）为准。

Markdown 增强写法：

- 公式：` ```tex ` 代码块 → KaTeX 渲染
- 图：` ```dot ` → Graphviz（Viz.js）；` ```sequence ` → 时序图；` ```puml ` / plantuml
- 提示块：`> [!NOTE]` / `[!TIP]` / `[!WARNING]`（flexible-alerts，`style: flat`）
- 标签页：docsify-tabs 语法

**首页专用样式**写在 `index.html` 的 `<style>` 里，选择器以 `.kb-home` 为前缀（`README.md` 用 `<div class="kb-home">` 包裹）。改动首页视觉请改那里，不要把 CSS 塞进 Markdown。

当前配置要点：`name: 'Note'`、`repo: https://github.com/Robinpig/Note`、`loadSidebar: false`、`loadNavbar: false`、`maxLevel: 4`、`sidebarDisplayLevel: 4`、`autoHeader: false`、`externalLinkTarget: '_blank'`、`auto2top: true`，别名 `/.*/_sidebar.md → /_sidebar.md`（侧边栏功能的遗留配置，本项目不生成 `_sidebar.md`，可忽略）。

## 笔记写作规范（必须遵守）

1. **结构顺序**：`## Introduction` 开头 → 正文小节（`##` 子主题、`###` / `####` 细节）→ `## Links` → `## References`。正文不内嵌「来源：…」引用块。
2. **内容标题一律英文**。除固定英文骨架外，正文小节（`##` 子主题、`###` / `####` 细节）标题一律用英文；正文保持中文、代码 / 配置名 / 产品名保留英文、References 保留原文。标题仍是锚点来源，改名会打断全库 `?id=` 引用，必须同步验证。
   - 固定英文骨架（全库统一三段式，不得汉化）：`## Introduction` / `## Links` / `## References`。
   - 保留英文的标题：**系统 / 算法 / 产品专有名词**（如 `## GFS`、`## Paxos`、`### Bigtable`、`## Consensus`），不要为翻译而硬译专名；专有名词可在中文解释后用括号附英文，如 `## 一致性（Consistency）`。
   - ✅ `## Message brokers` → `## 消息代理`、`### Partitioned Logs` → `### 分区日志`（描述性概念译中文）。
   - ⚠️ **锚点 bug 红线**：docsify 的 `?id=` 链接里**不能写带括号的标题**——半角 `( )` 会被 markdown 链接结构提前截断，全角 `（）` 的链接本库也无 `%` 编码先例、实际写不出。因此**被 `?id=` 引用的标题不要用「中文（English）」形式**：要么保留该标题英文（如 `### Read after write` 因被其它笔记 `?id=` 引用而保留），要么改用不被 `?id=` 引用的写法。改动任何标题前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就同步修并重跑 `validate_links.py` —— 改完立刻验证，别留到收尾。
3. **站内链接**一律用 docsify 绝对路径：`/docs/CS/OS/Linux/proc/process.md`；锚点用 `?id=slug`。
4. **slug 规则**（2026-10-02 按 docsify v5.0.0 源码 `src/core/render/slugify.js` 逐条复核；v4.13.1 实现相同。**不要凭标题印象拼**）：
   - `[A-Z]+` → 小写。**对纯 ASCII 标题等价于整串小写**（`MarkWord` → `markword`，`M` 与 `W` 都被小写）；差异只在非 ASCII 大写字母（`École` 保留 `É`）。
   - 删**半角**标点（ASCII 标点 + `\u2000-206F` + `\u2E00-2E7F`）→ **全角标点（：）（，、）与 `→` 一律保留** → 空白转 `-` → 数字开头前缀 `_` → markdown 链接只保留方括号里的显示文本（如 `[文本](https://example.com)` → `text`）。
   - 例：`限额接口（cgroup v2）` → **`限额接口（cgroup-v2）`**；`注意（Attention）` → **`注意（attention）`**。
   - 算不准就当场跑（`slugify()` 定义在 `validate_links.py`，可直接 import）：

     ```bash
     python3 -c "import sys;sys.path.insert(0,'scripts');from validate_links import slugify;print(slugify('标题'))"
     ```
   - ⚠️ `slugify()` 已于 2026-10-02 按 docsify 上游重写：旧版是「整串小写 + 删所有标点」，会把含全角标点的好链接误报成死链。另：全库存在**同文件内重复标题**，docsify 会给第 2、3 个追加 `-1`／`-2` 后缀（`anchors_of()` 已支持）。
   - **改标题会断既有锚点**：动手前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就把旧标题保留为独立小节，不要合并掉。
5. **`## Links`** 放 1~6 条最相关的**站内**笔记，只写一行 `- [标题](/docs/CS/OS/Linux/Linux.md)` 这种形式，**链接后不加任何后缀说明**；正文里已出现过的内部链接不重复列入；新增笔记后要回填相关笔记的 Links，形成双向链接。
6. **`## References`** 位于全文最后（`## Links` 之后），放外部文章 / 论文 / 官方文档，每条只写一行标题加链接，不加后缀说明（形式如 `[Linux Kernel Docs](https://docs.kernel.org/)`）。**KEP / RFC / issue 编号必须核实再写**（凭印象填编号、或照旧目录 slug 写 URL，都会 404）。
7. **代码片段**：从内核 / 框架源码摘录时保持原样（含原注释），中文解释写在代码块外的段落里。
8. **图片**放同目录或上级 `img/`，用相对路径引用。
9. **对比与选型优先用 Markdown 表格**。
10. 目录级索引页用 `README.md`，范式参考 [proc/README.md](/docs/CS/OS/Linux/proc/README.md)（叙述性知识地图 + 分节展开）。
11. **枢纽页导航禁止「`## XX 笔记索引` + `笔记|内容` 两列表格」**，必须写成**有因果递进的叙述性章节**（讲清为什么需要它、解决什么问题、与相邻笔记的关系），链接嵌进句子；不必串联全部笔记。表格只用于内容型对照。同层对比型笔记（如 Coze / Dify）之间不补直接互链，横向跳转交给枢纽页。

## 修改前必读的禁区

- **不要重命名或移动 `docs/` 下已有文件 / 目录**。确需移动时必须按上面「移动笔记的固定流程」执行，并先告知用户外链有 404 风险。
- **不要修改 `out/`**（IDE 产物副本）、`src/`、`wiki/`、`knowledge-base/`、`outputs/`。
- `index.html` 只动配置和样式区块，**不要重排脚本加载顺序**（插件依赖 docsify 主脚本先加载）。
- `.obsidian/`、`.claude/`、`.workbuddy/` 是**本机工具目录，都不入版本控制**（`.gitignore` 里忽略了 `.obsidian/`、`.claude`、`.workbuddy`）—— 换机器克隆下来可能根本不存在，**不要依赖、也不要删**。其中 **`.workbuddy` 存的是 Agent 记忆，不是缓存**；**校验脚本不在那里，在已入库的 `scripts/`**。
- 新增链接前先确认目标文件存在。以下目录的入口**不等于目录名**（或存在两级入口），别写错：
  - `CS/BuildTool/` 入口是 `BuildTools.md`（不是 `BuildTool.md`）
  - `CS/Tool/` 无 `Tool.md`，代表文件 `Vim.md`
  - `CS/front-end/` 无 `front-end.md`，代表文件 `Nodejs.md`
  - `CS/Java/` 有两级入口：语言入口与目录地图是 `Java/Java.md`，JDK/JVM 内部机制的枢纽是 `JDK/JDK.md`（写 JDK 源码细节走后者）
  - `CS/SE/` 入口是 `Engineering.md`
  - `CS/Framework/` 无 `Framework.md`，总入口是 `Framework/README.md`（目录级索引页），具体机制在各框架子目录
  - `docs/Test.md` 是测试页，可忽略

## 校验工具（`scripts/`，随仓库入库，不进站点）

| 脚本 | 用途 |
| :--- | :--- |
| `scripts/kb-check.sh` | **一键全量门禁**（推荐入口）：链接校验 + 密度门禁 + 全库 dot 校验 + CDN 可达性（仅告警）；前几项任一不通过即非零退出 |
| `scripts/validate_links.py <file\|dir...>` | **主力校验**：死链 DEAD / 坏锚点 BAD ANCHOR / 相对链接 RELATIVE / 西里尔字母 CYRILLIC（均致命）+ 中英夹杂 GARBLED（告警）。可 `import` 出 `slugify()` 复用 |
| `scripts/analyze_crosslinks.py --root <目录> --dirs <子目录...> [--gate --min-indegree N]` | 量化链入/链出、孤立页、弱链出页；`--gate` 做密度门禁。**目录只能用 `--root`/`--dirs` 传，写位置参数会报错退出**（`-h` 看完整说明）。默认根是 `docs/CS/Framework`，跑别的子树必须显式 `--root`。带 `?id=`／`#` 片段的链接与 `%20` 转义路径**都计入**图；根目录下的散文件（`CS.md`、`Languages.md`）不作为节点 |
| `scripts/check_dot.js <dir...>` | 用站点实际加载的 viz.js 复现 dot 图渲染，防 Graphviz 语法错误导致整页白屏（需 node）。viz.js 地址**从 `index.html` 现读**（改 CDN 不必回来改脚本），失败回退 unpkg；下载内容会校验首行是否 `<!DOCTYPE html>`。离线/被墙机器用 `VIZ_JS=<本地路径>` 指定手工下载的副本 |
| `scripts/check_cdn.sh` | 逐条验证 `index.html` 的外部资源可达。**「页面完全无法渲染」时先跑这个**（需 curl） |
| `scripts/fix_garbled.py` | 修 `validate_links.py` 报的 GARBLED（在 CJK 与 Latin 边界补空格） |
| `scripts/find_hub_gaps.py` | 定位 hub 页 `## Links` 中未链到的子笔记 |
| `scripts/fix_framework_hublinks.py` | 阶段①：框架内 hub 页 Links 补齐，消除孤立页 |
| `scripts/fix_framework_crosslinks.py` | 阶段②：跨框架双向链接矩阵 |

> [!NOTE]
>
> 这批脚本原先放在 `.workbuddy/tools/`，而那个目录被 `.gitignore` 忽略 → 新机器与 GitHub Actions 上都拿不到（CI 直接 `can't open file`）。2026-10-06 已迁到 `scripts/` 并入库，`.gitignore` 里用 `!scripts/*.py` 放行。**不要再把它们挪回被忽略的目录，也不要写死绝对路径**：脚本的仓库根一律由自身位置（`__file__` / `__dirname`）推导，可在任意 cwd 下调用。

`validate_links.py` 的选项：`--verbose` 逐行打印 GARBLED 告警（默认只汇总计数）、`--strict` 把 GARBLED 也当致命。退出码 0 = 通过。

## 站点白屏排查：先验 CDN，再查内容

**外部依赖必须全部挂 `cdn.jsdelivr.net`，不要用 `unpkg.com` 或 `cdn.staticfile.org`**（2026-10-06 实测这两个域名连接失败，而 docsify 核心原本就挂在 unpkg 上 → **整站白屏、任何页面都打不开**，而笔记内容、链接校验、dot 图校验全绿，**极易误判成笔记写坏了**）。

排查「页面无法渲染 / 白屏」的顺序：
1. `bash scripts/check_cdn.sh` —— 外部资源是否都200。
2. `bash scripts/kb-check.sh` —— 才是内容层面（死链 / dot 图语法）。

两个 jsDelivr 坑：**包版本号可能不存在**（`docsify@4.13.0` 是 404，要用不带版本的 `docsify/lib/...`）；写脚本抽 URL 时**先剥 HTML 注释块**，否则已停用的插件（mermaid/disqus 等）会被计入而产生误报。
⚠️ **不要用 headless Chrome 验证这个站点**：`--dump-dom` 会因 viz.js（2.4MB）挂死数分钟。用「curl 验 200 + `node --check` 验语法」代替。

```bash
python3 scripts/validate_links.py docs/CS/Framework/etcd   # 按目录
python3 scripts/validate_links.py docs/CS/Framework        # 按框架
python3 scripts/validate_links.py docs/CS/OS/Linux         # Linux 内核子树
bash scripts/kb-check.sh                                   # 本地全量门禁（范围比 CI 大，见下）
```

**CI 与本地脚本的范围不是一套，别当成等价**（2026-10-06 逐条比对 `.github/workflows/ci.yml` 与 `scripts/kb-check.sh`）：

| 入口 | 覆盖范围 |
| :--- | :--- |
| `.github/workflows/ci.yml`（push / PR，ubuntu-latest） | Framework 链接校验 + Linux 链接校验 + Framework 密度门禁 + Linux 密度门禁，共 4 步 |
| `scripts/kb-check.sh`（本地） | 上述四项 **＋ 消息队列链接校验 ＋ 全库 dot 图可渲染校验**；找不到 node 时自动跳过 dot 校验 |

门禁规则为「无孤立页 + 平均链入 ≥ 3.5」，弱链出页仅告警不阻断。**快照数字不要写进本文件**，需要时现场跑脚本。

> [!WARNING]
>
> `analyze_crosslinks.py --gate` 失败时**退出码为 1**。写 shell 门禁脚本时若只把它放在中间位置，`set -e` 不会捕获（只看最后一条命令的退出码），会出现"打印了不通过却仍然 exit 0"的假通过。`scripts/kb-check.sh` 用 `check()` 包装函数显式检查每一步的退出码——**改这个脚本时务必保留该包装**。

**全库跑 `validate_links.py` 约 1.5 分钟（千余篇）；按目录跑更快。**

站内死链扫描（在仓库根执行，**路径必须 unquote**，否则含 `%20` 的路径全误报）：

```bash
grep -rhoE '/docs/[^)` ]+\.md' docs README.md | sort -u | python3 -c "
import sys, os, urllib.parse as u
for line in sys.stdin:
    p = u.unquote(line.strip())
    if not os.path.isfile('.' + p):
        print('BROKEN:', p)
"
```

代码围栏"不成对"的常见根因是**连续两个开启围栏**；定位法是把围栏按序编号，看奇数位是否出现了纯 ` ``` `。

## 常见任务

**统计各目录篇数**

```bash
for d in docs/CS/*/; do printf "%-24s %s\n" "${d#docs/CS/}" "$(find "$d" -name '*.md' | wc -l)"; done | sort -k2 -rn
```

**新增一篇笔记**

1. 确定归属目录，文件名用术语英文名（同目录内保持风格一致）。
2. 按「笔记写作规范」写正文，结尾补 `## Links` 与 `## References`。
3. 挂进索引：所属目录的 `README.md` 或父级入口页（如 `CS/OS/Linux/Linux.md`）的叙述性章节 / 表格。
4. 在相关笔记的 `## Links` 里补回链。
5. 跑校验（`validate_links.py` + 死链扫描），确认无死链、无坏锚点。工具不在本机时按「校验工具」一节的语义手工核对。

**本地预览**

```bash
python3 -m http.server 8899   # 打开 http://127.0.0.1:8899/index.html
```

## 已知遗留问题

- ✅ **校验脚本入库问题已修**（2026-10-06）：脚本原在 `.workbuddy/tools/`（被 `.gitignore` 忽略），CI 却调用它们 → 新机器与 Actions 上必然缺文件。已迁到 `scripts/`，`.gitignore` 加 `!scripts/*.py` 放行。**遗留的小不对称**：`ci.yml` 仍只跑 Framework + Linux 两项，而 `scripts/kb-check.sh` 多跑 MQ 校验与全库 dot 校验 —— 若想让 CI 与本地完全一致，把 `ci.yml` 的 4 个 step 换成一句 `bash scripts/kb-check.sh` 即可（ubuntu-latest 自带 node，可直接跑 dot 校验）。
- ✅ **`check_dot.js` 的 viz.js 源与站点漂移已修**（2026-10-06）：脚本硬编码 `unpkg.com`（站点本体早已全量挂 jsdelivr），本机连不上 unpkg 时这一步必失败，看起来像"内容写坏了"其实是取不到渲染器。现在**从 `index.html` 现读** viz.js 地址、失败回退 unpkg、下载内容校验首行是否 `<!DOCTYPE html>`、超时压到 connect 8s / 总 30s，离线或被墙的机器用 `VIZ_JS=<本地路径>` 指定手工下载的副本即可跑。
- ✅ **`analyze_crosslinks.py` 漏计带锚点的链接已修**（2026-10-06）：旧正则只匹配 `](/docs/x.md)`，凡是 `?id=` 锚点链接与 `%20` 转义路径**全部不计入图**，导致枢纽页链出被系统性低估、门禁数字偏冷（边只增不减，修完门禁阈值不用动）。同时它的真实接口是 `--root`/`--dirs`，而本节旧版写成位置参数 `[dir...]` —— 已改正文档，并让脚本误用位置参数时打印用法而非只报"未知参数"。
- 部分目录缺同名入口 md（见禁区一节），目录索引只能链接到具体笔记。
- 全库仍有若干主题零覆盖（DAMON、dm-crypt / LUKS、md / RAID、kTLS、Landlock），部分主题偏薄（livepatch、kdump、pidfd、psi、MPTCP）。定时任务主题的缺口（Python / Rust / C++ 定时器、Go 运行时深处、K8s CronJob、crontab / systemd timer）单独记在 `docs/CS/SE/Scheduled_Task.md` 的 Open Gaps 一节，**以那里为准，不在本文件重复列**。
