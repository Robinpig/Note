# AGENTS.md

面向 AI Agent 的项目说明。修改本仓库前请先读这一页。

## 项目是什么

`Note` 是**个人计算机知识库**，同一份 Markdown 有两种使用形态：

1. **docsify 站点**：根目录 `index.html` 是站点入口与全部配置，`README.md` 是首页，内容全部在 `docs/`，通过 GitHub Pages 发布（仓库 `Robinpig/Note`，`.nojekyll` 保证下划线目录不被 Jekyll 吞掉）。
2. **Obsidian vault**：根目录存在 `.obsidian/`，日常用 Obsidian 编辑，靠双向链接导航。

因此有两条硬约束：**文件名与目录名就是笔记标识**（重命名/移动会同时打断 Obsidian 双链和 docsify 绝对路径链接）；**笔记必须同时满足 docsify 渲染和 Obsidian 阅读**。

规模：`docs/` 下约千篇 Markdown，六个领域，`CS/` 是绝对主体，其余五个领域合计仅数十篇。

**不要在文档里写任何文件总数或目录篇数**：`README.md`、`docs/CS/CS.md`、本文件一律不标注篇数，新增/删除笔记不需要回头改数字。需要精确值时现场跑脚本（见「统计各目录篇数」）。

## 目录地图

```
Note/
├── index.html          docsify 入口 + 全站配置（插件、主题、首页 CSS）
├── README.md           站点首页（同时也是 GitHub 仓库首页）—— 只做总入口：学习路径 + 六大领域入口
├── AGENTS.md           本文件
├── docs/               全部笔记内容
│   ├── CS/             CS 主体
│   ├── Mathematics/    分支学科枢纽页 + 各分支
│   ├── Psychology/     分支学科枢纽页 + 各分支
│   ├── Philosophy/
│   ├── Economics/
│   └── Sports/         以上五个领域均为少量读书摘录
├── out/                IDE 编译产物副本 —— 只读，不要改
├── src/                忽略，不要改
└── wiki/、knowledge-base/、outputs/   空占位，不要改
```

`docs/CS/` 下共 35 个主题目录 + `img/`。主要子树与入口：

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
| 消息队列     | `CS/MQ/`          | [MQ.md](/docs/CS/MQ/MQ.md)                                                                     |
| Golang   | `CS/Go/`          | [Go.md](/docs/CS/Go/Go.md)                                                                     |

其余较小目录：`CO/`（组成原理）、`C/`、`C++/`、`Python/`、`Rust/`、`Scala/`、`TypeScript/`、`assembly/`、`memory/`、`Compiler/`、`BuildTool/`（入口 `BuildTools.md`）、`Tool/`（**无 Tool.md**，代表文件 `Vim.md`）、`front-end/`（**无 front-end.md**，代表文件 `Nodejs.md`）、`Browser/`、`DesignPatterns/`、`VCS/`、`log/`、`compress/`、`Cloud/`、`BigData/`、`Blockchain/`、`Security/`、`GNU/`。

`docs/CS/Flutter.md` 是**没有同名目录的孤立文件**，不要误以为存在 `CS/Flutter/`。

跨领域索引页：`docs/CS/CS.md`（CS 总纲 + 全部主题目录清单）、`docs/CS/term.md`（术语表）、`docs/CS/Languages.md`（语言横向对比）。各目录下的 `README.md` 会被 docsify 当作该目录首页（如 `CS/OS/Linux/proc/README.md` 是进程知识地图）。

**首页与总纲的分工**：`README.md` 只做**总入口**（学习路径 + 六大领域卡片，每个领域一张独立卡片，不合并），不放任何 CS 主题清单；`docs/CS/CS.md` 是 CS 的**唯一目录来源**（主题卡片 + 主题目录全展开 + 各学科定义）。不要在两处各写一份主题列表。

## Linux 内核笔记的组织（当前主力方向）

`docs/CS/OS/Linux/` 是全库最活跃的子树，组织规则容易踩错：

- **`Linux/Linux.md` 是唯一枢纽**，全库被引最多的文件，**不要改名**（`Linux/` 下没有 `README.md` 是全库常态，127 个目录都缺）。
- **`Linux/` 根目录放横切机制**（不属于单一子系统）：`Interrupt.md`、`Calls.md`、`timer.md`、`workqueue.md`、`LXC.md` / `namespace.md` / `cgroup.md` / `SELinux.md`、`KVM.md`、`Swap.md`、`ZeroCopy.md`、`performance.md`、`Architecture.md`、`Experience.md`、`build.md`。
- **子系统各建子目录**：`proc/`（进程/调度/信号/IPC）、`mm/`、`fs/`、`net/`、`IO/`、`Lock/`、`dev/`、`boot/`（启动链）、`module/`、`struct/`（内核数据结构）、`Tools/`、`Distribution/`。
- **新增子目录后必须回 `Linux.md` 挂入口**（踩过：目录迁移完忘了挂，新目录的 README 引用数一度为 0）。
- ⚠️ **`Linux/0.11.md` 讲的是 Linux 自己 1991 年的早期版本**（`bootsect.s` / `setup.s` / `head.S` / `init/main.c`），是现代内核的直系祖先，**不是教学内核**，不要迁到 `OS/` 根或与 xv6 / rCore / osask 并列。
- ⚠️ **`OS/Boot/` 与 `OS/Linux/boot/` 是两个不同目录**：前者只有旧的 `Grub.md`，启动链主题在后者（`README.md` / `Start.md` / `init.md` / `U-Boot.md` / `arm.md`）。
- ⚠️ `mm/memory.md` 是 **boot 阶段的初始化笔记**，**不是内存子系统总入口**（全站有旧链接把它当 "Linux Memory"，属历史错配）。

**内核源码核实**：以**本机源码树 `/Users/robin/Tools/linux-7.2.7`（v7.2.7）为准**，直接 Read / Grep，快且不限流。需要其它版本时才回退：

```bash
curl -s "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/<path>?h=v6.12"
```

（GitHub raw 会 429；elixir / bootlin 的 raw 返回 HTML，不可用。现代内核头文件拆得很细，io_uring 拆进 `io_uring/`、overlayfs 有 `params.h`，按旧印象找不到宏时先 `ls` 确认文件清单；结构体定义常是换行式 `struct foo`，搜 `^struct foo$`。）

**版本事实陷阱**：sysctl / feature gate **存在 ≠ 它还生效**。判断"当前实际行为"要读**消费方函数读的是哪个变量**以及**默认值代码**，只看 sysctl 表条目或 gate 状态会写出过时结论。

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
   - 算不准就当场跑：

     ```bash
     python3 -c "import sys;sys.path.insert(0,'.workbuddy/tools');from validate_anchors import slug;print(slug('标题'))"
     ```
   - ⚠️ `validate_anchors.py` 已于 2026-10-02 按上游重写：旧版是「整串小写 + 删所有标点」，会把含全角标点的好链接误报成死链。另：全库有 54 个文件存在**同文件内重复标题**，docsify 会给第 2、3 个追加 `-1`／`-2` 后缀（工具已支持）。
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

| 脚本                              | 用途                                                          |
| :------------------------------ | :---------------------------------------------------------- |
| `validate_note.py <file>`       | 单篇：内部 `/docs/...` 链接是否存在 + 代码围栏是否成对                           |
| `validate_anchors.py <file\|dir...>` | `?id=slug` 是否真实存在于目标文件标题（支持文件或目录，也可 `import` 出 `slug()` 复用） |

**全库跑 `validate_anchors.py` 约 1.5 分钟（千余篇）；按目录跑更快。**

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
