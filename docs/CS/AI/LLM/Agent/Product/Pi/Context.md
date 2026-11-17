## Introduction

一次模型请求的上下文由几块拼成：**系统提示**（分 section 的结构化提示 + 发现的上下文文件）、**活跃分支**的会话历史、**工具定义**、**技能描述**。系统提示不整段重写，而是按 section 做差异写进 transcript；历史逼近窗口上限时触发压缩，摘要以 user 角色回注。压缩的插入点由 [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Pi/AgentLoop.md) 的两层循环裁决（轮间 `prepareNextTurn` 与请求前 `prepareRequest`）。本页覆盖上下文文件发现、系统提示的 section 化与差异写入，以及压缩的完整链路。

> 版本基线：核实于 2026-11-16，对应 **v1.5.2**（commit `b4afdddf44e059c67ccf5097e5317d913521b470`，2026-11-10 发布）。所有结论以该 tag 的源码为准。交互侧细节在 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)；会话树与分支摘要在 [Session](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)。

## Context Files

上下文文件是 Pi 的「项目记忆」：从 agent 目录（`~/.pi/agent`）、工作目录及其父目录递归发现，在对应目录或其任何子目录下运行 Pi 时生效。发现逻辑在 `packages/coding-agent/src/core/resource-loader.ts`，单目录候选按优先级取**第一个**存在的文件：

```ts
function loadContextFileFromDir(dir: string): { path: string; content: string } | null {
	const candidates = ["AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD"];
	for (const filename of candidates) {
		const filePath = join(dir, filename);
		if (existsSync(filePath)) {
			try {
				if (!statSync(filePath).isFile()) {
					continue;
				}
				return {
					path: filePath,
					content: stripBom(readFileSync(filePath, "utf-8")),
				};
			} catch (error) {
				console.error(chalk.yellow(`Warning: Could not read ${filePath}: ${error}`));
			}
		}
	}
	return null;
}
```

| 文件 | 作用 |
| :--- | :--- |
| `~/.pi/agent/AGENTS.md` | 全局指令，所有项目生效 |
| 项目/各级目录的 `AGENTS.md` 或 `CLAUDE.md` | 项目级指令，逐级向上查找 |
| `AGENTS.override.md` | **只替代同目录**的那份 AGENTS.md/CLAUDE.md |
| `SYSTEM.md` / `APPEND_SYSTEM.md` | 替换 / 追加系统提示（agent 目录与 `.pi` 两级） |

两个容易踩的点：

- `AGENTS.override.md` 的作用域仅限**同一目录**，它不屏蔽 agent 目录或其他目录的上下文文件。
- 上下文文件的发现**不需要 project trust**——拒绝信任一个项目也不会让它的 `AGENTS.md` 失效，文件夹里的指令一律按不可信输入对待（详见 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)）。想彻底关闭用 `--no-context-files`。

`SYSTEM.md` / `APPEND_SYSTEM.md` 则相反：项目的那份**只在项目受信任时**才被采用，且优先于 agent 目录里的同名文件（同级不合并，各取一份）：

```ts
private discoverSystemPromptFile(): string | undefined {
	const projectPath = join(this.cwd, CONFIG_DIR_NAME, "SYSTEM.md");
	if (this.settingsManager.isProjectTrusted() && existsSync(projectPath)) {
		return projectPath;
	}

	const globalPath = join(this.agentDir, "SYSTEM.md");
	if (existsSync(globalPath)) {
		return globalPath;
	}

	return undefined;
}
```

改完任何上下文文件，`/reload` 立即生效，不用重启。

## Compaction

压缩解决的是「活跃分支越来越长，装不进模型窗口」的问题。Pi 有两套摘要机制，格式同源：

| 机制 | 触发 | 目的 |
| :--- | :--- | :--- |
| Compaction | context 超阈值或 `/compact` | 摘要旧消息，腾出上下文 |
| Branch summarization | `/tree` 切换分支 | 把被放弃分支的工作带进新分支 |

### When It Triggers

自动压缩的判据是一条不等式，且 `reserveTokens` 只在这里决定**触发阈值**：

```ts
/**
 * Check if compaction should trigger based on context usage.
 */
export function shouldCompact(contextTokens: number, contextWindow: number, settings: CompactionSettings): boolean {
	if (!settings.enabled) return false;
	return contextTokens > contextWindow - settings.reserveTokens;
}
```

默认值（`packages/coding-agent/src/core/compaction/compaction.ts`）：

```ts
export interface CompactionSettings {
	enabled: boolean;
	reserveTokens: number;
	keepRecentTokens: number;
}

export const DEFAULT_COMPACTION_SETTINGS: CompactionSettings = {
	enabled: true,
	reserveTokens: 16384,
	keepRecentTokens: 20000,
};
```

`reserveTokens` 默认 **16384**（给响应留的空间），`keepRecentTokens` 默认 **20000**（保留多新的消息不摘要），两者都在 `settings.json` 可配。`AgentSession._checkCompaction` 在 agent_end 之后、提交新 prompt 之前检查；此外 `prepareNextTurn` 内也会检查（批次终止 run 且无排队消息则跳过）。provider 报 context-overflow 或提前出现 `stopReason: "length"` 时走「压缩 + 重试」恢复，且只重试一次：

```ts
 * Automatic cases:
 * 1. Overflow with retry: a context-overflow error or recoverable length stop;
 *    remove the failed assistant message, compact, and retry the turn once.
 * 2. Overflow without retry: a successful response exceeded the configured
 *    context window; compact but preserve the completed response.
 * 3. Threshold without retry: valid or estimated context usage crossed the
 *    configured threshold; compact without retrying the completed response.
```

### How It Works

1. **找切割点**：从投影尾部向前累计 token 估算，够到 `keepRecentTokens` 为止；
2. **抽取消息**：从上一个保留边界（或会话开始）取到切割点；
3. **生成摘要**：调 LLM 按结构化格式总结，有上一次摘要时作为迭代上下文传入；
4. **落条目**：`appendCompaction()` 追加 `CompactionEntry`（`summary` + `firstKeptEntryId` + `tokensBefore` + 生成摘要的 `usage`）；
5. **重建上下文**：投影里用摘要 + `firstKeptEntryId` 之后的消息。

切割点只能落在 user 消息、assistant 消息、BashExecution 与 custom 消息上——**tool result 永不作为切点**，因为它必须跟着自己的 tool call：

```ts
function isCutPointMessage(message: AgentMessage): boolean {
	switch (message.role) {
		case "user":
		case "assistant":
		case "bashExecution":
		case "custom":
		case "branchSummary":
		case "compactionSummary":
			return true;
		case "toolResult":
			return false;
	}
	return false;
}
```

当一个 user-message span 自己就超过 `keepRecentTokens` 时，切割点落进该 span 内部的 assistant 消息处（split user-message span），生成「历史摘要 + span 前缀摘要」两份再合并。重复压缩时，被摘要区间从**上一次压缩的保留边界**起算；`tokensBefore` 按重建后的投影重算，保证计数对应真实被替换的上下文。

关键一点：**压缩不删历史 entry，只追加 checkpoint**。`buildContextEntries()` 遍历当前 leaf 路径，遇到 compaction 就记住最后一条，然后只从 `firstKeptEntryId` 开始收消息——原始条目仍在会话文件里：

```ts
const contextEntries: SessionEntry[] = [compaction];
let foundFirstKept = false;
for (let i = 0; i < compactionIdx; i++) {
	const entry = path[i];
	if (entry.id === compaction.firstKeptEntryId) {
		foundFirstKept = true;
	}
	if (foundFirstKept && !(entry.type === "message" && entry.message.role === "system")) {
		contextEntries.push(entry);
	}
}
contextEntries.push(...path.slice(compactionIdx + 1));
return contextEntries;
```

`appendCompaction()` 则是纯追加，并顺手带上当前 system message 的回放：

```ts
const entry: CompactionEntry<T> = {
	type: "compaction",
	id,
	parentId: this.leafId,
	timestamp,
	summary,
	firstKeptEntryId: firstKeptEntryId ?? id,
	tokensBefore,
	details,
	usage,
	fromHook,
	...(systemMessage ? { systemMessage: { ...systemMessage, timestamp: new Date(timestamp).getTime() } } : {}),
};
```

所以导出、检索、计费看到的都是全量历史，压缩只改变「喂给模型的是哪一段」。

### Summary Injection

摘要不是塞进 system 角色，而是以 **user 角色**回注，外面包一层固定前缀/后缀（`packages/coding-agent/src/core/messages.ts`）：

```ts
export const COMPACTION_SUMMARY_PREFIX = `The conversation history before this point was compacted into the following summary:

<summary>
`;

export const COMPACTION_SUMMARY_SUFFIX = `
</summary>`;
```

投影转换时，`compactionSummary` 被翻成 user 消息：

```ts
case "compactionSummary":
	return {
		role: "user",
		content: [
			{ type: "text" as const, text: COMPACTION_SUMMARY_PREFIX + m.summary + COMPACTION_SUMMARY_SUFFIX },
		],
		timestamp: m.timestamp,
	};
```

默认摘要是结构化 Markdown：Goal → Constraints & Preferences → Progress（Done / In Progress / Blocked）→ Key Decisions → Next Steps → Critical Context，并累积跟踪读/改过的文件（`readFiles` / `modifiedFiles` 进 `details`）。

### Summary Generation

摘要请求是一次性 prompt，不写 prompt-cache，并带**独立路由 ID**——没有继承到 session ID 时现造一个 `uuidv7()`，避免污染正常会话的缓存：

```ts
// Avoid cache writes for one-off summaries. Reuse caller-supplied routing when available;
// callers without a session ID, including branch summaries, receive a fresh routing ID.
const requestOptions: SimpleStreamOptions = {
	...options,
	cacheRetention: "none",
	sessionId: options.sessionId ?? uuidv7(),
};
const produce = async (): Promise<AssistantMessage> =>
	streamFn
		? (await streamFn(model, context, requestOptions)).result()
		: completeSimple(model, context, requestOptions);
return retryAssistantCall(produce, retry, requestOptions.signal, callbacks);
```

再看 `reserveTokens`：它虽被当作参数一路传下来，但**摘要生成本身完全不用它**——长度由模型自身的 output limit 约束（注释直接写明 `#9512`）：

```ts
export async function generateSummary(
	currentMessages: AgentMessage[],
	model: Model<any>,
	// Unused. Kept for existing callers; summaries use the model's output limit (#9512).
	_reserveTokens: number | undefined,
	apiKey: string | undefined,
```

### System Prompt Sections

系统提示不是一整段字符串，而是**有序、可独立替换的 section**（`packages/coding-agent/src/core/system-prompt.ts`）：`preamble`（无标签的裸文本）、`tools`、`rules`、`docs`、`addendum`、`project_context`、`skills`、`cwd`。除 `preamble` 外每个 section 都用同名 XML 标签包起来，方便模型把后续更新对上号：

```ts
if (appendSystemPrompt) promptSections.addendum = appendSystemPrompt;
if (contextFiles.length > 0) promptSections.project_context = renderProjectContext(contextFiles);
// A hidden reader is still reachable through another tool, so skills stay but the hint names no tool.
const readers = ["read", "bash"] as const;
const skillFileReadTool =
	readers.find((tool) => declaredTools.includes(tool)) ??
	(readers.some((tool) => selectedTools.includes(tool)) ? "indirect" : undefined);
if (skillFileReadTool && skills.length > 0) {
	const skillsPrompt = formatSkillsForPrompt(skills, skillFileReadTool).trim();
	if (skillsPrompt) promptSections.skills = skillsPrompt;
}
promptSections.cwd = cwd.replace(/\\/g, "/");
for (const [name, content] of Object.entries(customSections)) {
	if (content) promptSections[name] = content;
}

const sections: SystemPromptSections = { preamble: promptSections.preamble };
for (const [name, content] of Object.entries(promptSections)) {
	if (name !== "preamble") sections[name] = `<${name}>\n${content}\n</${name}>`;
}
return sections;
```

`diffSystemPromptSections` 把「模型当前持有的 section」（从 transcript 回放，永不为 null）与期望值对比，**只返回变化的 section** 作为 patch；没变化返回 `undefined`，被删掉的 section 用 `null` 标记：

```ts
export function diffSystemPromptSections(
	previous: Record<string, string | null>,
	current: SystemPromptSections,
): Record<string, string | null> | undefined {
	const patch: Record<string, string | null> = {};
	for (const [name, text] of Object.entries(current)) {
		if (previous[name] !== text) patch[name] = text;
	}
	for (const name of Object.keys(previous)) {
		if (current[name] === undefined) patch[name] = null;
	}
	return Object.keys(patch).length > 0 ? patch : undefined;
}
```

`AgentSession._preparePromptAndToolLoadout` 拿这个 patch 生成一条 `SystemMessage` 写进 transcript；无变化则不写：

```ts
const sections = diffSystemPromptSections(
	getCurrentSystemMessage(messages)?.sections ?? {},
	buildSystemPromptSections(options),
);
return sections ? { role: "system", content: "", sections, timestamp: Date.now() } : undefined;
```

### Extension Hooks

压缩对扩展开放三个钩子：`session_before_compact`（可提供自定义摘要，或改写序列化文本）、`session_compact_failed`（失败通知）、`session_before_tree`（分支切换前）。恢复顺序有严格契约：先持久化最终响应 → `turn_end` / `agent_end` → 追记 `context_edit` 省略 → 溢出/长度场景跑压缩 → 以全新 run 重试；恢复压缩失败时保留省略编辑、不追加重试，排队工作回到普通 steering/follow-up 规则。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Compaction 理论](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Events：扩展事件 / 钩子总表](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)
- [Durable：持久化 Agent 框架](/docs/CS/AI/LLM/Agent/Product/Pi/Durable.md)

## References

- [Pi Compaction Reference（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/compaction.md)
- [Pi Configuration（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/configuration.md)
- [Pi How Pi Works（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/how-pi-works.md)
- [compaction.ts（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/compaction/compaction.ts)
- [system-prompt.ts（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/system-prompt.ts)
