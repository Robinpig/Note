# AGENTS.md

面向 AI Agent 的项目说明。修改本仓库前请先读这一页。

## 项目是什么

`Note` 是**个人计算机知识库**，同一份 Markdown 有两种使用形态：

1. **docsify 站点**：根目录 `index.html` 是站点入口与全部配置，`README.md` 是首页，内容全部在 `docs/`，通过 GitHub Pages 发布（仓库 `Robinpig/Note`，`.nojekyll` 保证下划线目录不被 Jekyll 吞掉）。
2. **Obsidian vault**：根目录存在 `.obsidian/`，日常用 Obsidian 编辑，靠双向链接导航。

因此有两条硬约束：**文件名与目录名就是笔记标识**（重命名/移动会同时打断 Obsidian 双链和 docsify 绝对路径链接）；**笔记必须同时满足 docsify 渲染和 Obsidian 阅读**。

规模：`docs/` 下约千篇 Markdown，七个领域，`CS/` 是绝对主体。

**不要在文档里写任何文件总数或目录篇数**：`README.md`、`docs/CS/CS.md`、本文件一律不标注篇数，新增/删除笔记不需要回头改数字。需要精确值时现场跑脚本（见「统计各目录篇数」）。

## 目录地图

```
Note/
├── index.html          docsify 入口 + 全站配置（插件、主题、首页 CSS）
├── README.md           站点首页（同时也是 GitHub 仓库首页）—— 只做总入口：学习路径 + 各大领域入口
├── AGENTS.md           本文件
├── docs/               全部笔记内容
│   ├── CS/             CS 主体
│   ├── Mathematics/    分支学科枢纽页 + 各分支
│   ├── Medicine/       医学与护理学：学科框架为主，见下节
│   ├── Psychology/     分支学科枢纽页 + 各分支
│   ├── Philosophy/
│   ├── Economics/
│   └── Sports/         Philosophy/Economics/Sports 为少量读书摘录
├── out/                IDE 编译产物副本 —— 只读，不要改
├── src/                忽略，不要改
└── wiki/、knowledge-base/、outputs/   空占位，不要改
```

`docs/CS/` 下按主题分目录（另有 `img/` 存放配图，不算笔记）。主要子树与入口：

| 领域       | 目录                | 入口与说明                                                                                          |
| :------- | :---------------- | :--------------------------------------------------------------------------------------------- |
| 操作系统     | `CS/OS/`          | [OS.md](/docs/CS/OS/OS.md)；下辖 `Linux/`、`unix/`、`Windows/`、`mac/`、`Android/`、`xv6/`、`Fuchsia/`、`Book/`、`Boot/`（仅 `Grub.md`） |
| Linux 内核 | `CS/OS/Linux/`    | [Linux.md](/docs/CS/OS/Linux/Linux.md) 是该子树的**唯一枢纽**，见下节                                   |
| 框架与中间件   | `CS/Framework/`   | **无总入口**，直接用具体框架页（Spring、Spring_Boot、Netty、Tomcat、Dubbo、ZooKeeper、etcd、ES、Flink、Hadoop、Spark、Job 等） |
| Java     | `CS/Java/`        | 入口 [JDK/JDK.md](/docs/CS/Java/JDK/JDK.md)（`Java/Java.md` 不存在）                                  |
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

其余较小目录：`CO/`（组成原理）、`C/`、`C++/`、`Python/`、`Rust/`、`Scala/`、`TypeScript/`、`assembly/`、`memory/`、`Compiler/`、`BuildTool/`（入口 `BuildTools.md`）、`Tool/`（**无 Tool.md**，代表文件 `Vim.md`）、`front-end/`（**无 front-end.md**，代表文件 `Nodejs.md`）、`Browser/`、`DesignPatterns/`、`VCS/`、`log/`、`compress/`、`Cloud/`、`BigData/`、`Blockchain/`、`Security/`、`GNU/`。

`docs/CS/Flutter.md` 是**没有同名目录的孤立文件**，不要误以为存在 `CS/Flutter/`。

跨领域索引页：`docs/CS/CS.md`（CS 总纲 + 全部主题目录清单）、`docs/CS/term.md`（术语表）、`docs/CS/Languages.md`（语言横向对比）。各目录下的 `README.md` 会被 docsify 当作该目录首页（如 `CS/OS/Linux/proc/README.md` 是进程知识地图）。

**首页与总纲的分工**：`README.md` 只做**总入口**（学习路径 + 各领域卡片，每个领域一张独立卡片，不合并），不放任何 CS 主题清单；`docs/CS/CS.md` 是 CS 的**唯一目录来源**（主题卡片 + 主题目录全展开 + 各学科定义）。不要在两处各写一份主题列表。

## 医学 / 护理学笔记的组织（`docs/Medicine/`）

2026-10 新增的第七领域，与 `Psychology/` 同为「分支学科枢纽页 + 各分支页」结构：

- `Medicine/Medicine.md` 是该领域**唯一总纲**；分支页为 `Basic_Medicine.md`、`Clinical_Medicine.md`、`Diagnosis.md`、`Public_Health.md`、`Medical_History_Ethics.md`。
- 护理学是**唯一有子目录**的分支：`Medicine/Nursing/` 下 `Nursing.md`（总纲）+ 11 篇分支页，按**基础层 / 场景层 / 延伸层**三层组织——基础层 `Nursing_Fundamentals.md`；场景层 `Clinical_Nursing.md`、`Maternal_Pediatric_Nursing.md`、`Psychiatric_Nursing.md`、`OR_Sterile_Supply.md`、`Emergency_Disaster_Nursing.md`、`Palliative_Care.md`、`Gerontological_Nursing.md`；延伸层 `Community_Home_Nursing.md`、`Nursing_Research_Education.md`、`Nursing_Informatics.md`；`Nursing_Management_Ethics.md` 贯穿全部。新增护理学内容一律放 `Nursing/`，不要在 `Medicine/` 根下平铺。
- ⚠️ **医学 × CS 的固定交叉点**：`Nursing/Nursing_Informatics.md` 是本库医学与计算机科学**最直接**的交叉页（决策支持、远程护理、可穿戴、AI 辅助），链向 `CS/AI/AI.md` 与 `CS/AI/LLM/LLM.md`。写 AI 相关医学内容时**从这篇转链**，不要重复叙述 AI 原理。
- ⚠️ **内容口径：学科框架为主，谨慎写临床细节**。剂量、诊疗路径、指南推荐等级、各类指标阈值、给药方案与器械参数**不收录**——它们随指南更新而变化，写死必然过时且有出错风险。需要时只写「关注点与判断逻辑」，并在页首用 `> [!WARNING]` 块声明「不收录具体规程，以最新指南与机构规范为准」。
- ⚠️ 医学笔记用**中文术语 + 英文原名**（如「循证医学（evidence-based medicine）」首次出现时），这是本库其他领域（CS/哲学/心理学）一致的做法。
- 医学与本库其他领域的固定交叉点：`Sports/Anatomy.md`（解剖）、`Psychology/Biological_Psychology.md`（生理基础）、`Philosophy/Ethics.md`（伦理四原则的哲学源流）、`Mathematics/Probability_Statistics.md`（研究设计与统计推断）、`CS/AI/AI.md`（AI 辅助决策的算法责任）。新增医学页时优先链到这些已有页，不要重复新建。

## Linux 内核笔记的组织（当前主力方向）

`docs/CS/OS/Linux/` 是全库最活跃的子树，组织规则容易踩错：

- **`Linux/Linux.md` 是唯一枢纽**，全库被引最多的文件，**不要改名**（`Linux/` 下没有 `README.md` 是全库常态，127 个目录都缺）。
- **`Linux/` 根目录放横切机制**（不属于单一子系统）：`Interrupt.md`、`Calls.md`、`timer.md`、`workqueue.md`、`LXC.md` / `namespace.md` / `cgroup.md` / `SELinux.md`、`KVM.md`、`Swap.md`、`ZeroCopy.md`、`performance.md`、`Architecture.md`、`Experience.md`、`build.md`。
- **子系统各建子目录**：`proc/`（进程/调度/信号/IPC）、`mm/`、`fs/`、`net/`、`IO/`、`Lock/`、`dev/`、`boot/`（启动链）、`module/`、`struct/`（内核数据结构）、`Tools/`、`Distribution/`。
- **较新的两个子目录**（2026-10 新增，各有独立 README 枢纽）：`cgroup/`（v2 三篇：知识地图 / 控制器接口 / 委派实践；根目录的 `cgroup.md` 保留为 **v1 视角**入口）、`PM/`（电源管理六篇：知识地图 / cpuidle / cpufreq / suspend / runtime PM / devfreq）。
- **新增子目录后必须回 `Linux.md` 挂入口**（踩过：目录迁移完忘了挂，新目录的 README 引用数一度为 0）。
- ⚠️ **`Linux/0.11.md` 讲的是 Linux 自己 1991 年的早期版本**（`bootsect.s` / `setup.s` / `head.S` / `init/main.c`），是现代内核的直系祖先，**不是教学内核**，不要迁到 `OS/` 根或与 xv6 / rCore / osask 并列。
- ⚠️ **`OS/Boot/` 与 `OS/Linux/boot/` 是两个不同目录**：前者只有旧的 `Grub.md`，启动链主题在后者（`README.md` / `Start.md` / `init.md` / `U-Boot.md` / `arm.md` / `crash.md`）。
- ⚠️ `mm/memory.md` 是 **boot 阶段的初始化笔记**，**不是内存子系统总入口**（全站有旧链接把它当 "Linux Memory"，属历史错配）。
- ⚠️ **`struct/struct.md` 只讲 llist**，文件名覆盖面远大于内容，是历史沿用名；`struct/` 的地图以 `struct/README.md` 为准。同理 `Tools/Tools.md`（命令速查表）与 `Tools/README.md`（笔记导航）**不是一回事**。
- ⚠️ **标题避免用全角标点**（如 `## freezer：冻结与终止`）：`validate_links.py` 的 `anchors_of()` 会按全角冒号把标题切成两个锚点，与 docsify 的 `slugify()` 行为不一致，导致 BAD ANCHOR 误报。中英混排标题用**半角空格**分隔（`## freezer 冻结与终止`）。

**内核源码核实**（2026-10-05 实测修订）：**本机已无 Linux 源码树**（旧记的 `/Users/robin/Tools/linux-7.2.7` 路径不存在，`/Users/robin` 这个用户也没有）。改用远程端点，**tag 用 `v7.2`**（真实 tag 是 `v7.2` = 7.2.0，**`v7.2.7` 不存在**，写错会拿到 404 HTML）：

```bash
K="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain"
curl -sL -m 40 "$K/kernel/panic.c?h=v7.2"          # → 纯文本源码
```

**其它端点现状**：`elixir.bootlin.com` 已被 Anubis 反爬**全站拦截**（`/source`、`?raw=1`、`/A/` 简写、`/api/v1/source/` 全返回 4.4KB 的 "Making sure you're not a bot!"，HTTP 200 但无内容）—— 人工浏览可用，**不可自动化**。GitHub API 403 限流、raw 会 429。

**四个必须知道的操作坑**（都实测踩过）：

1. **判断文件是否存在不能只看 `curl -w %{http_code}`** —— 该状态码会因缓存给出过期值（曾把 404 的 2932 字节 HTML 当成正常响应，导致"文件存在"的错误结论，进而引用了不存在的符号）。可靠做法：`wc -l` 看行数 + `head -1` 判断是否 `<!DOCTYPE html>`。
2. **猜路径极易落空，v7.2 大量文件已搬迁/改名**。用 tree 页取真实清单（比 `Makefile` 反推更准，能拿到未被当前配置编译的文件）：
   ```bash
   curl -sL "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/btrfs?h=v7.2" \
     | grep -oE "fs/btrfs/[a-z0-9_-]+\.(h|c)" | sort -u
   ```
   搬迁大户：`kernel/tty.c` → 拆成 `drivers/tty/tty_{io,ioctl,jobctrl,buffer,ldisc}.c`；`kernel/crash.c` → `kernel/crash_core.c` + `crash_reserve.c`；`fs/fuse/fuse.h` → `fuse_i.h` + `dev.h`；`drivers/input/core.c` → `input.c`；`fs/btrfs/*.h` 改**下划线命名**（`block-group.h`/`delayed-ref.h`）。
3. **结构体定义可能不在你以为的头文件里** —— 例如 btrfs 核心定义搬到了 **uapi 头** `include/uapi/linux/btrfs_tree.h`；`struct btrfs_key` 不在 `fs/btrfs/` 下。
4. **大批量 grep 偶发返回空结果**：在单次会话里对确认含目标串的大文件（数千行）执行 `grep` 曾多次返回空，而同样的检索经 Grep 工具或落盘后 `grep` 均正常。**若 grep 结果与预期矛盾，落盘后重试或改用 Grep 工具，不要据此认定"符号不存在"** —— 这类"不存在"的结论往往正是旧资料里 API 已删除的来源。

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
2. **站内链接**一律用 docsify 绝对路径：`/docs/CS/OS/Linux/proc/process.md`；锚点用 `?id=slug`。
3. **slug 规则**（2026-10-02 按 docsify v5.0.0 源码 `src/core/render/slugify.js` 逐条复核；v4.13.1 实现相同。**不要凭标题印象拼**）：
   - `[A-Z]+` → 小写。**对纯 ASCII 标题等价于整串小写**（`MarkWord` → `markword`，`M` 与 `W` 都被小写）；差异只在非 ASCII 大写字母（`École` 保留 `É`）。
   - 删**半角**标点（ASCII 标点 + `\u2000-206F` + `\u2E00-2E7F`）→ **全角标点（：）（，、）与 `→` 一律保留** → 空白转 `-` → 数字开头前缀 `_` → markdown 链接 `[文本](url)` 只留「文本」。
   - 例：`限额接口（cgroup v2）` → **`限额接口（cgroup-v2）`**；`注意（Attention）` → **`注意（attention）`**。
   - 算不准就当场跑（`slugify()` 定义在 `validate_links.py`，可直接 import）：

     ```bash
     python3 -c "import sys;sys.path.insert(0,'.workbuddy/tools');from validate_links import slugify;print(slugify('标题'))"
     ```
   - ⚠️ `slugify()` 已于 2026-10-02 按 docsify 上游重写：旧版是「整串小写 + 删所有标点」，会把含全角标点的好链接误报成死链。另：全库有 54 个文件存在**同文件内重复标题**，docsify 会给第 2、3 个追加 `-1`／`-2` 后缀（`anchors_of()` 已支持）。
   - **改标题会断既有锚点**：动手前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就把旧标题保留为独立小节，不要合并掉。
4. **`## Links`** 放 1~6 条最相关的**站内**笔记，只写 `- [标题](/docs/....md)` 一行，**链接后不加任何后缀说明**；正文里已出现过的内部链接不重复列入；新增笔记后要回填相关笔记的 Links，形成双向链接。
5. **`## References`** 位于全文最后（`## Links` 之后），放外部文章 / 论文 / 官方文档，每条只写一行 `[标题](链接)`，不加后缀说明。**KEP / RFC / issue 编号必须核实再写**（凭印象填编号、或照旧目录 slug 写 URL，都会 404）。
6. **代码片段**：从内核 / 框架源码摘录时保持原样（含原注释），中文解释写在代码块外的段落里。
7. **图片**放同目录或上级 `img/`，用相对路径引用。
8. **标题语言**：中英混排，术语保留英文（`task_struct`、EEVDF、futex、sched_ext 等）；标题尽量英文或短中文，保证锚点稳定。
9. **对比与选型优先用 Markdown 表格**。
10. 目录级索引页用 `README.md`，范式参考 [proc/README.md](/docs/CS/OS/Linux/proc/README.md)（叙述性知识地图 + 分节展开）。
11. **枢纽页导航禁止「`## XX 笔记索引` + `笔记|内容` 两列表格」**，必须写成**有因果递进的叙述性章节**（讲清为什么需要它、解决什么问题、与相邻笔记的关系），链接嵌进句子；不必串联全部笔记。表格只用于内容型对照。同层对比型笔记（如 Coze / Dify）之间不补直接互链，横向跳转交给枢纽页。

## 修改前必读的禁区

- **不要重命名或移动 `docs/` 下已有文件 / 目录**。确需移动时必须按上面「移动笔记的固定流程」执行，并先告知用户外链有 404 风险。
- **不要修改 `out/`**（IDE 产物副本）、`src/`、`wiki/`、`knowledge-base/`、`outputs/`。
- `index.html` 只动配置和样式区块，**不要重排脚本加载顺序**（插件依赖 docsify 主脚本先加载）。
- `.obsidian/`、`.claude/`、`.workbuddy/` 为工具目录，无需维护。**`.workbuddy` 是项目数据（含记忆与校验脚本），不是缓存，不要删**。
- 新增链接前先确认目标文件存在。以下目录**没有同名入口文件**，别写错：
  - `CS/BuildTool/` 入口是 `BuildTools.md`（不是 `BuildTool.md`）
  - `CS/Tool/` 无 `Tool.md`，代表文件 `Vim.md`
  - `CS/front-end/` 无 `front-end.md`，代表文件 `Nodejs.md`
  - `CS/Java/` 入口在 `JDK/JDK.md`
  - `CS/SE/` 入口是 `Engineering.md`
  - `CS/Framework/` 无总入口，用具体框架页
  - `docs/Test.md` 是测试页，可忽略

## 校验工具（`.workbuddy/tools/`，不进站点）

| 脚本 | 用途 |
| :--- | :--- |
| `validate_links.py <file\|dir...>` | **主力校验**：死链 DEAD / 坏锚点 BAD ANCHOR / 相对链接 RELATIVE / 西里尔字母 CYRILLIC（均致命）+ 中英夹杂 GARBLED（告警）。可 `import` 出 `slugify()` 复用 |
| `analyze_crosslinks.py [dir...]` | 量化链入/链出、孤立页、弱链出页；`--gate --min-indegree N` 做密度门禁 |
| `fix_garbled.py [dir...]` | 修 `validate_links.py` 报的 GARBLED（在 CJK 与 Latin 边界补空格） |
| `find_hub_gaps.py [dir...]` | 定位 hub 页 `## Links` 中未链到的子笔记 |
| `fix_framework_hublinks.py` | 阶段①：框架内 hub 页 Links 补齐，消除孤立页 |
| `fix_framework_crosslinks.py` | 阶段②：跨框架双向链接矩阵 |

`validate_links.py` 的选项：`--verbose` 逐行打印 GARBLED 告警（默认只汇总计数）、`--strict` 把 GARBLED 也当致命。退出码 0 = 通过。

```bash
python3 .workbuddy/tools/validate_links.py docs/CS/Framework/etcd   # 按目录
python3 .workbuddy/tools/validate_links.py docs/CS/Framework        # 按框架
python3 .workbuddy/tools/validate_links.py docs/CS/OS/Linux         # Linux 内核子树
bash scripts/kb-check.sh                                          # CI 同款：两个子树全校验 + 密度门禁
```

**CI 门禁范围**（`.github/workflows/ci.yml` + `scripts/kb-check.sh`）：覆盖 **Framework 与 Linux 内核两个子树**，push/PR 时跑。门禁规则为「无孤立页 + 平均链入 ≥ 3.5」，弱链出页仅告警不阻断。Linux 子树当前 153 篇、平均链入 6.86、孤立页 0。

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
5. 跑校验（`validate_note.py` + 死链扫描），确认无死链、无坏锚点。

**本地预览**

```bash
python3 -m http.server 8899   # 打开 http://127.0.0.1:8899/index.html
```

## 已知遗留问题

- 部分目录缺同名入口 md（见禁区一节），目录索引只能链接到具体笔记。
- 全库仍有若干主题零覆盖（DAMON、dm-crypt / LUKS、md / RAID、kTLS、Landlock），部分主题偏薄（livepatch、kdump、pidfd、psi、MPTCP）。
