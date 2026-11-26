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

Theme（终端配色）是第五种资源形态，与四者并列但不改变行为。本页按 v1.5.2（commit `b4afdddf`，2026-11-10 发布）源码核验重写；这一版 workspace 共 **12 个包**，较 v1.3.0 新增 `pi-schema`（无 eval 的 JSON Schema 校验，供工具参数与结构化输出复用）。本页按「Skills → Prompt Templates → Packages → Extensions」展开；信任与加载门槛在 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)。

## Skills

Skill 是「教 Pi 做某类任务」的程序性记忆：一份指令加可选的支撑文件（脚本、参考资料、素材）。Pi 实现了 [Agent Skills 规范](https://agentskills.io/specification)，可移植形式是**含 `SKILL.md` 的目录**：

```text
pdf-tools/
├── SKILL.md            # frontmatter（name/description/...）+ 指令正文
├── scripts/extract.sh
├── references/formats.md
└── assets/template.json
```

加载是**两阶段**的：启动时只读 frontmatter，把 `name` / `description` / `location` 注入系统提示的 `<available_skills>`，全文不进上下文；任务匹配时模型才用 `read` 工具按需读全文。`formatSkillsForPrompt()` 的源码把这场裁剪写得很直白（`src/core/skills.ts`）：

```typescript
	for (const skill of visibleSkills) {
		lines.push("  <skill>");
		lines.push(`    <name>${escapeXml(skill.name)}</name>`);
		lines.push(`    <description>${escapeXml(skill.description)}</description>`);
		lines.push(`    <location>${escapeXml(skill.filePath)}</location>`);
		lines.push("  </skill>");
	}

	lines.push("</available_skills>");

	return lines.join("\n");
}
```

模型可能漏载相关 skill，用 `/skill:name`（参数追加在指令后当 user 请求）强制加载；frontmatter 里 `disable-model-invocation: true` 的 skill 被 `visibleSkills` 过滤掉，**不进提示、只能显式调用**：

```typescript
export function formatSkillsForPrompt(skills: Skill[], fileReadTool: "read" | "bash" | "indirect" = "read"): string {
	const visibleSkills = skills.filter((s) => !s.disableModelInvocation);

	if (visibleSkills.length === 0) {
		return "";
	}
```

frontmatter 字段：`name`（命令与显示名）、`description`（路由描述，**决定模型何时考虑加载**——要同时写清做什么和何时用）、`license`、`compatibility`、`metadata`、`allowed-tools`（实验性预批准工具表）、`disable-model-invocation`。命名限小写字母/数字/连字符，`MAX_NAME_LENGTH = 64`、`MAX_DESCRIPTION_LENGTH = 1024`；畸形 `SKILL.md` 与缺 description 的不加载，撞名保留首个并告警。

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

`PackageManager.parseSource()` 把安装源解析成三路——`npm:` 规范、本地路径、git URL，其余字符串按本地路径兜底（`src/core/package-manager.ts`）：

```typescript
	private parseSource(source: string): ParsedSource {
		if (source.startsWith("npm:")) {
			const spec = source.slice("npm:".length).trim();
			const { name, version } = this.parseNpmSpec(spec);
			return {
				type: "npm",
				spec,
				name,
				version,
				range: getNpmVersionRange(version),
				pinned: isExactNpmVersion(version),
			};
		}

		if (isLocalPath(source)) {
			return { type: "local", path: source };
		}

		// Try parsing as git URL
		const gitParsed = parseGitUrl(source);
		if (gitParsed) {
			return gitParsed;
		}

		return { type: "local", path: source };
	}
```

要点：

- **版本固定**：npm 版本号、git tag/commit 都会钉死；`pi update` 对账 checkout 但不移动已配置的 ref。
- **安装即写设置**：个人安装进 `~/.pi/agent/settings.json`，`--local`（`-l`）写项目 `.pi/settings.json`——项目声明**只在 project trust 授予后**才被读取。
- **资源过滤**：设置的 `packages` 可用对象形式按 glob 收窄（`[]` 全不加载、`!pattern` 排除、`+path`/`-path` 精确增删）；过滤只收窄包自己声明的资源。
- **身份识别**：npm 包按名、git 包按仓库 URL（不含 ref）、本地包按绝对路径——等价声明不会加载两份。同一包可同时出现在个人与项目设置里，项目项默认**整体替换**个人项；`autoload: false` 时项目项改为在个人包之上做增量过滤。
- **依赖纪律**：`pi-ai` / `pi-agent-core` / `pi-coding-agent` / `pi-tui` / `typebox` 由宿主提供，要写进 `peerDependencies`（`"*"`）而**不是** `dependencies`——物理拷贝会在编译后的 ESM 里造成重复类与重复注册表。安装的包各自独立 module root，别假设两个包共享同一依赖实例。
- 包 `package.json` 带 `pi-package` keyword 即可进 [Pi package gallery](https://pi.dev/packages)（可选 `pi.image`/`pi.video` 预览图）。

## Extensions (TypeScript)

Extension 是最高形态：跑在 Pi 进程内、与 Pi 同权限的 TS 模块，能注册工具、命令、快捷键、provider、MCP server、虚拟模型、事件处理器、渲染器与终端 UI。用 jiti 运行时加载，本地 TS 免编译——loader 直接 `createJiti(...)` 再 `jiti.import`：

```typescript
	const jiti = createJitiImpl(import.meta.url, {
		moduleCache: false,
		...resolutionOptions,
	});

	const module = await jiti.import(canonicalizePath(extensionPath), { default: true });
	const factory = module as ExtensionFactory;
	if (typeof factory !== "function") {
		return undefined;
	}
```

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

事件名是 `tool_call` / `tool_result`（**不是**旧文里常见的 `beforeToolCall` / `afterToolCall`），二者在 `ExtensionAPI.on()` 上的签名真实定义如下（`src/core/extensions/types.ts`）：

```typescript
	on(event: "tool_call", handler: ExtensionHandler<ToolCallEvent, ToolCallEventResult>): () => void;
	on(event: "tool_result", handler: ExtensionHandler<ToolResultEvent, ToolResultEventResult>): () => void;
```

处理器按扩展加载顺序跑，`pi.on()` 返回退订函数。关键语义：`tool_call` 可改写输入或阻断（**处理器失败 = 阻断**，fail-safe）；`tool_result` 多个处理器串联，后者看到前者的修改；`before_agent_start` 按 `event.messageType` 区分 user/custom 启动，可改提示分区或整体替换（`forceSystemPrompt`）；`turn_end` 与 `agent_before_settle` 是可行动边界，能挂 `custom`/`context_edit`/`compaction` 条目并请求**一次**续跑（要防无条件续跑死循环）；`agent_settled` 只读通知；`user_bash` 处理器返回 `undefined` 放行、返回 `operations`/`result` 截断、失败即阻断。

### Tool Contract

自定义工具 = name + 面向模型的 description + TypeBox 参数 schema + `execute()`。结果必须带面向模型的 `content` 和用于渲染/状态重建的 `details`；`terminate: true` 只有在**整批所有工具都同意**时才跳过自动跟进。声明 `outputSchema` 并返回 `structuredContent` 时，codemode 脚本拿到的是结构化数据而非文本；要「带数据的失败」就返回 `isError: true` 而不是抛异常。文件类工具的读-改-写全程用 `withFileMutationQueue()` 包住；大结果要截断并告诉模型去哪读全文。

嵌套调用走 `ctx.executeTool(name, args, { signal, onUpdate })`，和模型发起的调用一样过参数校验与 `tool_call`/`tool_result` 钩子；嵌套 id 形如 `<parent id>/n`，不进转录，只在调用方结果的 `nestedCalls` 里留有界记录（每调用参数 >8KiB、每结果 >32KiB 省略，最多 256 条，`complete: false` 标记有丢失），各层 `usage` 汇总进调用方结果。

### Tool Exposure

`exposure` 控制模型如何 reaching 一个工具。v1.5.2 的**五态真实定义**在 `src/core/extensions/types.ts`，连同注释原文：

```typescript
 * - `direct`: declared to the model while active, and callable while active.
 * - `model-only`: declared to the model while active, never callable. Use it for orchestrating or
 *   interactive tools.
 * - `codemode`: callable whenever registered. Not declared to the model unless explicitly
 *   activated. Codemode tools list it in their description.
 * - `deferred`: like `codemode`, but codemode tools do not list it; tool search can find it.
 * - `hidden`: registered but unreachable. Activating it has no effect.
 *
 * `direct` and `model-only` tools are activated when they are registered; the others are not.
 * The active tool set (`getActiveTools`/`setActiveTools`) is the set declared to the model.
 */
export type ToolExposure = "direct" | "model-only" | "codemode" | "deferred" | "hidden";
```

| 值 | 语义 |
| :--- | :--- |
| `direct`（默认） | 活跃时声明给模型，也可被别的工具调 |
| `model-only` | 只声明给模型，永不可被调（编排型/问用户型工具） |
| `codemode` | 注册即可调、被 codemode 列出，但不声明给模型 |
| `deferred` | 同 codemode 但不被列出——只有 `tool search` 能找到 |
| `hidden` | 注册但不可达（工具不能注销，重新注册为 hidden 即撤回） |

`direct` 和 `model-only` **注册即激活**，其余三态注册不激活。配套机制：`namespace` 给一组工具分组（MCP server 风格，脚本用 `describeNamespace(name)` 读长说明）；`annotations` 带 MCP 式四个 hint（`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`，缺省按「非只读、可能破坏、开放世界」），权限扩展可据此决定弹不弹确认；`reachesTools(input)` 声明一次调用可能 reaching 哪些工具；`prepareLoadout` 让编排型工具改写活跃工具集的声明与隐藏。`pi.setActiveTools()` 做动态激活——工具集变化会记入转录，不能表达这种变迁的 provider 会拿到完整检查点（可能击穿缓存前缀）。

### Discovery and Loading

扩展发现按**项目 → 全局 → 显式路径**三级优先级，先到先得、去重（`discoverAndLoadExtensions()`，`src/core/extensions/loader.ts`）：

```typescript
	// 1. Project-local extensions: cwd/${CONFIG_DIR_NAME}/extensions/
	const localExtDir = path.join(resolvedCwd, CONFIG_DIR_NAME, "extensions");
	addPaths(discoverExtensionsInDir(localExtDir));

	// 2. Global extensions: agentDir/extensions/
	const globalExtDir = path.join(resolvedAgentDir, "extensions");
	addPaths(discoverExtensionsInDir(globalExtDir));

	// 3. Explicitly configured paths
	for (const p of configuredPaths) {
		const resolved = resolvePath(p, resolvedCwd, { normalizeUnicodeSpaces: true });
		if (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory()) {
			const entries = resolveExtensionEntries(resolved);
			if (entries) {
				addPaths(entries);
				continue;
			}
			addPaths(discoverExtensionsInDir(resolved));
			continue;
		}
		addPaths([resolved]);
	}
```

`addPaths` 用 `seen` 集合按绝对路径去重，因此项目级同名扩展会压过全局级。加载走 jiti 即时编译，工厂函数缓存进 `extensionCache`，`/reload` 通过失效缓存 token 换掉整个运行时。

### State and UI

状态放哪取决于它如何参与对话：跟随活跃分支的工具状态放工具结果 `details`；不进上下文的持久数据用 `pi.appendEntry()`；要发给模型的自定义内容用 `pi.sendMessage()`；单会话之外的数据进外部存储。分支敏感状态从 `ctx.sessionManager.getBranch()` 重建，**别从所有 file entry 重建**——被放弃的分支是另一部历史。

扩展在 interactive / RPC / JSON / print 四种模式下都会加载；交互模式有完整 TUI，RPC 能转发受支持的对话框与通知（自定义终端组件不行），JSON/print 没有 UI。终端专属行为用 `ctx.mode === "tui"` 守门，交互类用 `ctx.hasUI`。

### Community Packages

社区包生态（持续变动，装前过源码）：状态栏（`statusline-pi`）、代码审查（`review`）、会话管理（`sessions`/`session-breakdown`）、文件浏览（`files`/`/readfiles`/`/code`）、任务拆解（`todos`/`loop`/`pi-delegator`）、上下文压缩（`headroom`/`pi-vcc`）、工作流（`workflow`/`handoff`/`wf`）、provider 接入（`claude-code-pi`/`grok-pi`/`opencode-pi`/`apple-fm-pi`）与独立能力包（Tavily 搜索、Context7、`pi-notify`、`pi-1password`、`pi-steward`、`pi-relay`）。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Skill 理论](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)
- [CodeMode：codemode 实现机制](/docs/CS/AI/LLM/Agent/Product/Pi/CodeMode.md)
- [Events：扩展事件 / 钩子总表](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)

## References

- [Pi Extensions 源码（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/extensions.md)
- [ToolExposure / ExtensionAPI 类型定义（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/extensions/types.ts)
- [Skill 两阶段加载（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/skills.ts)
- [扩展发现与 jiti 加载（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/extensions/loader.ts)
- [Pi Package parseSource（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/package-manager.ts)
- [Agent Skills Specification](https://agentskills.io/specification)
