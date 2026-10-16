## Introduction

Pi 核心刻意保持极小——默认只启用四个工具（`read` / `bash` / `edit` / `write`），其余能力一律靠扩展叠加。扩展分四个由浅入深的层次，官方选型建议是**从满足需要的最弱机制开始**：

| 需要 | 用什么 |
| :--- | :--- |
| 给 Pi 持久的项目指令 | `AGENTS.md` 上下文文件（见 [Context](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)） |
| 复用一条提示词 | Prompt template |
| 任务专用指令 + 支撑文件 | Skill |
| 可执行工具 / 命令 / 事件处理 | Extension |
| 自定义终端组件 | Terminal UI 扩展 |
| 接不支持的模型服务 | Custom provider |
| 把上述资源一起分发 | Pi package |

Theme（终端配色）是第五种资源形态，与四者并列但不改变行为。本页按「Skills → Prompt Templates → Packages → Extensions」展开；信任与加载门槛在 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)。

## Skills

Skill 是「教 Pi 做某类任务」的程序性记忆：一份指令加可选的支撑文件（脚本、参考资料、素材）。Pi 实现了 [Agent Skills 规范](https://agentskills.io/specification)，可移植形式是**含 `SKILL.md` 的目录**：

```text
pdf-tools/
├── SKILL.md            # frontmatter（name/description/...）+ 指令正文
├── scripts/extract.sh
├── references/formats.md
└── assets/template.json
```

加载机制是两阶段：启动时只把每个 skill 的 `name`、`description`、路径注入系统提示；任务匹配时模型才去读 `SKILL.md` 全文——详细指令不进上下文，直到需要为止。模型可能漏载相关 skill，用 `/skill:name`（参数追加在指令后当 user 请求）强制加载；frontmatter 里 `disable-model-invocation: true` 则只许显式命令触发。

frontmatter 字段：`name`（命令与显示名）、`description`（路由描述，**决定模型何时考虑加载**——要同时写清做什么和何时用）、`license`、`compatibility`、`metadata`、`allowed-tools`（实验性预批准工具表）、`disable-model-invocation`。命名限小写字母/数字/连字符（≤64 字符），description ≤1024；畸形 `SKILL.md` 与缺 description 的不加载，撞名保留首个并告警。

发现位置：agent 目录 `skills/`、项目 `.pi/skills/`（递归）、以及规范位置 `~/.agents/skills/` 与 `.agents/skills/`（项目侧从工作目录向上直到仓库根）。

## Prompt Templates

模板把 Markdown 文件变成 `/` 命令，放在 `~/.pi/agent/prompts/` 或 `.pi/prompts/`（**文件名即命令名**）：

```markdown
---
description: Review staged git changes
argument-hint: "[focus]"
---
Review the staged changes. Focus on ${1:-correctness, security, and error handling}.
```

替换语法：`$1`/`$2`（位置参数）、`$@` 或 `$ARGUMENTS`（全部参数）、`${1:-default}`（带默认值）、`${@:N}` / `${@:N:L}`（切片）。参数按 shell 风格引号切分，`/review "API compatibility"` 是一个含空格的参数。模板在进入 agent 前展开；扩展先经 `input` 事件看到原始输入（除非同名扩展命令接管）。

## Pi Packages

Package 把 extensions / skills / prompts / themes 打成一个单元，经 npm 或 git 分发：

```bash
pi install npm:@example/pi-tools@1.0.0   # npm：装在 Pi 的 npm 目录
pi install git:github.com/example/pi-tools@v1
pi install ./local-package               # 本地路径：不复制，直接加载
pi list / pi remove <source> / pi update --extensions
pi config                                # 交互式挑加载哪些资源
```

要点：

- **版本固定**：npm 版本号、git tag/commit 都会钉死；`pi update` 对账 checkout 但不移动已配置的 ref。
- **安装即写设置**：个人安装进 `~/.pi/agent/settings.json`，`--local`（`-l`）写项目 `.pi/settings.json`——项目声明**只在 project trust 授予后**才被读取。
- **资源过滤**：设置的 `packages` 可用对象形式按 glob 收窄（`[]` 全不加载、`!pattern` 排除、`+path`/`-path` 精确增删）；过滤只收窄包自己声明的资源。
- **身份识别**：npm 包按名、git 包按仓库 URL（不含 ref）、本地包按绝对路径——等价声明不会加载两份。同一包可同时出现在个人与项目设置里，项目项默认**整体替换**个人项；`autoload: false` 时项目项改为在个人包之上做增量过滤。
- **依赖纪律**：`pi-ai` / `pi-agent-core` / `pi-coding-agent` / `pi-tui` / `typebox` 由宿主提供，要写进 `peerDependencies`（`"*"`）而**不是** `dependencies`——物理拷贝会在编译后的 ESM 里造成重复类与重复注册表。安装的包各自独立 module root，别假设两个包共享同一依赖实例。
- 包 `package.json` 带 `pi-package` keyword 即可进 [Pi package gallery](https://pi.dev/packages)（可选 `pi.image`/`pi.video` 预览图）。

## Extensions (TypeScript)

Extension 是最高形态：跑在 Pi 进程内、与 Pi 同权限的 TS 模块，能注册工具、命令、快捷键、provider、MCP server、虚拟模型、事件处理器、渲染器与终端 UI。用 jiti 运行时加载，本地 TS 免编译。

### Lifecycle

默认导出工厂收 `ExtensionAPI`，可同步可异步（异步工厂会阻塞启动，便于拉配置/注册 provider）。纪律：**工厂里不启动进程、socket、watcher、timer**（某些加载路径不起会话）；长生命周期资源从 `session_start` 或具体命令/工具里启，`session_shutdown` 里幂等关闭。`/reload` 会整体替换扩展运行时，`await ctx.reload()` 之后的代码不能再用旧运行时的状态。

### Integration Surface

| 能力 | 主要 API |
| :--- | :--- |
| 观察/改写生命周期 | `pi.on()` |
| 加模型可调用的工具 | `pi.registerTool()` |
| 加 `/` 命令 | `pi.registerCommand()` |
| 加快捷键 / CLI flag | `pi.registerShortcut()` / `pi.registerFlag()` |
| 发消息 | `pi.sendUserMessage()` / `pi.sendMessage()` |
| 存不进上下文的会话数据 | `pi.appendEntry()` |
| 加模型 provider / MCP server | `pi.registerProvider()` / `pi.registerMcpServer()` |
| 按请求路由模型 | `pi.registerVirtualModel()` |
| 终端渲染 | 渲染器注册 + `ctx.ui` |

处理器按扩展加载顺序跑，`pi.on()` 返回退订函数。关键语义：`tool_call` 可改写输入或阻断（**处理器失败 = 阻断**，fail-safe）；`tool_result` 多个处理器串联，后者看到前者的修改；`before_agent_start` 按 `event.messageType` 区分 user/custom 启动，可改提示分区或整体替换（`forceSystemPrompt`）；`turn_end` 与 `agent_before_settle` 是可行动边界，能挂 `custom`/`context_edit`/`compaction` 条目并请求**一次**续跑（要防无条件续跑死循环）；`agent_settled` 只读通知；`user_bash` 处理器返回 `undefined` 放行、返回 `operations`/`result` 截断、失败即阻断。

### Tool Contract

自定义工具 = name + 面向模型的 description + TypeBox 参数 schema + `execute()`。结果必须带面向模型的 `content` 和用于渲染/状态重建的 `details`；`terminate: true` 只有在**整批所有工具都同意**时才跳过自动跟进。声明 `outputSchema` 并返回 `structuredContent` 时，codemode 脚本拿到的是结构化数据而非文本；要「带数据的失败」就返回 `isError: true` 而不是抛异常。文件类工具的读-改-写全程用 `withFileMutationQueue()` 包住；大结果要截断并告诉模型去哪读全文。

嵌套调用走 `ctx.executeTool(name, args, { signal, onUpdate })`，和模型发起的调用一样过参数校验与 `tool_call`/`tool_result` 钩子；嵌套 id 形如 `<parent id>/n`，不进转录，只在调用方结果的 `nestedCalls` 里留有界记录（每调用参数 >8KiB、每结果 >32KiB 省略，最多 256 条，`complete: false` 标记有丢失），各层 `usage` 汇总进调用方结果。

### Tool Exposure

`exposure` 控制模型如何 reaching 一个工具：

| 值 | 语义 |
| :--- | :--- |
| `direct`（默认） | 活跃时声明给模型，也可被别的工具调 |
| `model-only` | 只声明给模型，永不可被调（编排型/问用户型工具） |
| `codemode` | 一注册即可被调、被 codemode 列出，但不声明给模型 |
| `deferred` | 同 codemode，但 codemode 也不列——只有 `tool_search` 能找到 |
| `hidden` | 注册但不可达（工具不能注销，重新注册为 hidden 即撤回） |

配套机制：`namespace` 给一组工具分组（MCP server 风格，脚本用 `describeNamespace(name)` 读长说明）；`annotations` 带 MCP 式四个 hint（`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`，缺省按「非只读、可能破坏、开放世界」），权限扩展可据此决定弹不弹确认；`reachesTools(input)` 声明一次调用可能 reaching 哪些工具；`prepareLoadout` 让编排型工具改写活跃工具集的声明与隐藏。`pi.setActiveTools()` 做动态激活——工具集变化会记入转录，不能表达这种变迁的 provider 会拿到完整检查点（可能击穿缓存前缀）。

### State and UI

状态放哪取决于它如何参与对话：跟随活跃分支的工具状态放工具结果 `details`；不进上下文的持久数据用 `pi.appendEntry()`；要发给模型的自定义内容用 `pi.sendMessage()`；单会话之外的数据进外部存储。分支敏感状态从 `ctx.sessionManager.getBranch()` 重建，**别从所有 file entry 重建**——被放弃的分支是另一部历史。

扩展在 interactive / RPC / JSON / print 四种模式下都会加载；交互模式有完整 TUI，RPC 能转发受支持的对话框与通知（自定义终端组件不行），JSON/print 没有 UI。终端专属行为用 `ctx.mode === "tui"` 守门，交互类用 `ctx.hasUI`。

### Community Packages

社区包生态（2026-08/09 文章快照，持续变动，装前过源码）：状态栏（`statusline-pi`）、代码审查（`review`）、会话管理（`sessions`/`session-breakdown`）、文件浏览（`files`/`/readfiles`/`/code`）、任务拆解（`todos`/`loop`/`pi-delegator`）、上下文压缩（`headroom`/`pi-vcc`）、工作流（`workflow`/`handoff`/`wf`）、provider 接入（`claude-code-pi`/`grok-pi`/`opencode-pi`/`apple-fm-pi`）与独立能力包（Tavily 搜索、Context7、`pi-notify`、`pi-1password`、`pi-steward`、`pi-relay`）。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md) — Skill 指令如何进入系统提示
- [Security：信任与隔离](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md) — 扩展与包的信任门槛
- [Skill 理论](/docs/CS/AI/LLM/Agent/Theory/Skill.md) — Agent Skills 概念的通用机制
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) — Pi 内置 MCP 客户端与 tool exposure 的配合

## References

- [Pi Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
- [Pi Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)
- [Pi Packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)
- [Pi Prompt Templates](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/prompt-templates.md)
- [Agent Skills Specification](https://agentskills.io/specification)
