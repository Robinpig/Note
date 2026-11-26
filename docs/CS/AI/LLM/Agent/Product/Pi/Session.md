## Introduction

Pi 的会话不是一段线性聊天记录，而是一棵由**不可变 append-only entry 日志 + `leafId` 指针**构成的树：每条 entry 用 `id` / `parentId` 连成父子关系，`leafId` 指向当前所在节点；模型看到的上下文并不是被存下来的状态，而是**读取时现算的投影**——`buildSessionPath` → `buildContextEntries` → `buildSessionProjection`。「回到过去」因此不是撤销，而是把 `leafId` 移回旧节点再从那里追加；被放弃的分支原样留在文件里，随时可以走回去。

本页覆盖树的三种操作、持久化与存储位置、导出分享，以及 v1.5.2 的实现纠偏。谁驱动活跃分支的读取与续跑见 [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Pi/AgentLoop.md)；压缩（context 超限时的摘要机制）在 [Context](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)，交互细节在 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)。

> 版本基线：v1.5.2（2026-11-10 发布，commit `b4afdddf`），本地 `E:/Projects/pi-1.5.2` 已 checkout 到该 tag。此前笔记沿用的旧版本口径整体作废；v1.0.0 之前社区文章里的「会话树 + `/sessions`」同样过期——查看会话树是 `/tree`，挑选历史会话是 `/resume`。

## Entry Log and Tree

一条 session entry 的最小形态只有四个字段，`id` 是 8 位十六进制短 ID（碰撞时才回退到完整 UUID），`parentId: null` 表示根；会话 ID 本身则是 uuidv7。`SessionHeader` 是文件首行，只存元信息、不带 `id`/`parentId`，因此不属于树。

packages/coding-agent/src/core/session-manager.ts：

```typescript
export interface SessionEntryBase {
	type: string;
	id: string;
	parentId: string | null;
	timestamp: string;
}

export interface SessionMessageEntry extends SessionEntryBase {
	type: "message";
	message: AgentMessage;
}

export interface ThinkingLevelChangeEntry extends SessionEntryBase {
	type: "thinking_level_change";
	thinkingLevel: string;
}

export interface ModelChangeEntry extends SessionEntryBase {
	type: "model_change";
	provider: string;
	modelId: string;
}
```

label 和 session_info 同样是树节点——它们继承 `SessionEntryBase`，有自己的 `id` 和 `parentId`：

```typescript
/** Label entry for user-defined bookmarks/markers on entries. */
export interface LabelEntry extends SessionEntryBase {
	type: "label";
	targetId: string;
	label: string | undefined;
}

/** Session metadata entry (e.g., user-defined display name). */
export interface SessionInfoEntry extends SessionEntryBase {
	type: "session_info";
	name?: string;
}
```

`context_edit` 是 append-only 的「未来上下文改写」，只带目标 id 与替换内容：

```typescript
/** Content that an append-only context edit may replace without changing message metadata. */
export type ContextEditableContent =
	| UserMessage["content"]
	| AssistantMessage["content"]
	| ToolResultMessage["content"]
	| CustomMessage["content"];

/** Append-only change to one earlier entry's contribution to model context. */
export interface ContextEditEntry extends SessionEntryBase {
	type: "context_edit";
	targetId: string;
	/** Null omits the target from model context. A value replaces only its content. */
	replacement: { content: ContextEditableContent } | null;
}
```

全部 11 种 entry type 由 `SessionEntry` 联合类型收口：

```typescript
/** Session entry - has id/parentId for tree structure (returned by "read" methods in SessionManager) */
export type SessionEntry =
	| SessionMessageEntry
	| ThinkingLevelChangeEntry
	| ModelChangeEntry
	| UsageEntry
	| CompactionEntry
	| BranchSummaryEntry
	| CustomEntry
	| CustomMessageEntry
	| ContextEditEntry
	| LabelEntry
	| SessionInfoEntry;
```

| `type` | 语义 | 是否进入模型上下文 |
| :--- | :--- | :--- |
| `message` | user / assistant / toolResult / system 消息 | 是 |
| `thinking_level_change` | 思考级别切换 | 否（只被投影读取为设置） |
| `model_change` | 会话中途切换模型 | 否（只被投影读取为设置） |
| `usage` | 不挂在 assistant 消息上的模型用量（如 `cache_warm`） | 否 |
| `compaction` | 压缩摘要 + 完整 system checkpoint | 是 |
| `branch_summary` | 离开分支时生成的被放弃路径摘要 | 是 |
| `custom` | 扩展持久化状态 | 否 |
| `custom_message` | 扩展注入的消息 | 是 |
| `context_edit` | 对某条旧 entry 的 append-only 上下文改写 | 自身不产生消息 |
| `label` | 树节点上的书签 | 否 |
| `session_info` | 会话元信息（如 `/name`） | 否 |

短 ID 的生成方式：

```typescript
function createSessionId(): string {
	return uuidv7();
}

export function assertValidSessionId(id: string): void {
	if (!/^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/.test(id)) {
		throw new Error(
			"Session id must be non-empty, contain only alphanumeric characters, '-', '_', and '.', and start and end with an alphanumeric character",
		);
	}
}

/** Generate a unique short ID (8 hex chars, collision-checked) */
function generateId(byId: { has(id: string): boolean }): string {
	for (let i = 0; i < 100; i++) {
		const id = randomUUID().slice(0, 8);
		if (!byId.has(id)) return id;
	}
	// Fallback to full UUID if somehow we have collisions
	return randomUUID();
}
```

树的形态由「从 leaf 沿 `parentId` 回溯到根」定义。默认 leaf 就是文件里的最后一条 entry——`buildSessionPath` 在未显式给出 `leafId` 时直接取 `entries[entries.length - 1]`，也就是**物理顺序**：

```typescript
function buildSessionPath(
	entries: SessionEntry[],
	leafId?: string | null,
	byId?: Map<string, SessionEntry>,
): SessionEntry[] {
	const index = buildEntryIndex(entries, byId);
	let leaf: SessionEntry | undefined;
	if (leafId === null) {
		return [];
	}
	if (leafId) {
		leaf = index.get(leafId);
	}
	leaf ??= entries[entries.length - 1];
	if (!leaf) {
		return [];
	}

	const path: SessionEntry[] = [];
	let current: SessionEntry | undefined = leaf;
	while (current) {
		path.push(current);
		current = current.parentId ? index.get(current.parentId) : undefined;
	}
	path.reverse();
	return path;
}
```

## Context Projection

`buildContextEntries` 在路径上做压缩感知的筛选：取最新一条 `compaction`，只保留它和从 `firstKeptEntryId` 起算的后续 entry，被摘要掉的旧消息从**投影**里消失，但原始 entry 没被删除。下面是该函数的核心片段：

```typescript
	const path = buildSessionPath(entries, leafId, byId);
	let compaction: CompactionEntry | null = null;

	for (const entry of path) {
		if (entry.type === "compaction") {
			compaction = entry;
		}
	}

	if (!compaction) {
		return path;
	}

	const compactionIdx = path.findIndex((entry) => entry.id === compaction.id);
	if (compactionIdx < 0) {
		return path;
	}

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
```

`buildSessionProjection` 再把每条选中的 entry 投成模型可见消息，并把同一目标上最新的 `context_edit` 应用上去。`replacement: null` 表示**省略**该目标；非 null 只替换 content，保留原消息的 role 与元数据。assistant / toolResult 的字符串替换会被规范化成单个 text block。

```typescript
export function projectContextEntry(entry: SessionEntry, edit: ContextEditEntry | undefined): AgentMessage[] {
	const messages = sessionEntryToContextMessages(entry);
	if (!edit) return messages;
	const replacement = edit.replacement;
	if (replacement === null) return [];

	return messages.map((message) => {
		if (
			message.role !== "user" &&
			message.role !== "assistant" &&
			message.role !== "toolResult" &&
			message.role !== "custom"
		) {
			return message;
		}
		const content =
			(message.role === "assistant" || message.role === "toolResult") && typeof replacement.content === "string"
				? [{ type: "text" as const, text: replacement.content }]
				: replacement.content;
		return { ...message, content } as AgentMessage;
	});
}
```

```typescript
	const path = buildSessionPath(entries, leafId, byId);
	const { thinkingLevel, model } = getSessionContextSettings(path);
	const contextEntries = buildContextEntries(entries, leafId, byId);
	const edits = new Map<string, ContextEditEntry>();
	for (const entry of contextEntries) {
		if (entry.type === "context_edit") edits.set(entry.targetId, entry);
	}
	const projectedEntries = contextEntries.map(
		(sourceEntry, index): ProjectedSessionEntry => ({
			sourceEntry,
			// buildContextEntries() may retain an older compaction entry because its
			// raw ID lies inside the newest retained range. Only the newest compaction
			// at index zero contributes a checkpoint and summary.
			messages:
				sourceEntry.type === "compaction" && index > 0
					? []
					: projectContextEntry(sourceEntry, edits.get(sourceEntry.id)),
		}),
	);
	return {
		entries: projectedEntries,
		messages: projectedEntries.flatMap((entry) => entry.messages),
		thinkingLevel,
		model,
	};
```

两个关键语义：

- **context_edit 只改未来模型上下文，不改原 entry**：目标 entry 的原始内容在 raw 历史、UI、导出和 token 统计里保持不变。
- **分支相对**：因为 `edits` 只从当前 active 分支的 `contextEntries` 收集，切到 edit 之前的节点时该 edit 不在路径上，目标的原始贡献会重新出现；同一目标有多条 edit 时，活动分支上最新的一条生效。

`buildSessionContext()` 只是在 projection 之上再取一次扁平化的 `messages`，不引入新的改写。

## Persistence

正常写入是 `appendFileSync` 追加一行；只有**首次落盘**用 `openSync(..., "wx")` 一次性写全内存里的 entry，而触发条件是会话里出现了第一条 user 或 assistant message——只开 Pi 不聊天不会留下文件。注释还特意说明从 user message（而非首个 assistant 回复）开始落盘，是为了首个 turn 未完成时 prompt 仍能留在磁盘上。

```typescript
	/**
	 * A new session file is created only once the session contains a user or assistant message.
	 * Setup entries alone (model, thinking level, system prompt) stay in memory so opening and
	 * closing pi without chatting leaves no file behind. Starting at the user message (not the
	 * first assistant reply) keeps the prompt on disk if the first turn never completes (#10000).
	 */
	private _hasConversation(): boolean {
		return this.fileEntries.some(
			(e) => e.type === "message" && (e.message.role === "user" || e.message.role === "assistant"),
		);
	}
```

```typescript
	_persist(entry: SessionEntry): void {
		if (!this.persist || !this.sessionFile) return;

		if (!this.flushed) {
			if (!this._hasConversation()) return;
			const fd = openSync(this.sessionFile, "wx");
			try {
				for (const e of this.fileEntries) {
					writeFileSync(fd, `${JSON.stringify(e)}\n`);
				}
			} finally {
				closeSync(fd);
			}
			this.flushed = true;
		} else {
			appendFileSync(this.sessionFile, `${JSON.stringify(entry)}\n`);
		}
	}
```

**全量重写只发生在两处**：版本迁移（`migrateToCurrentVersion` 为真时 `_rewriteFile()`）和分支抽取 / clone-fork（`createBranchedSession` 决定是否立即 `_rewriteFile()`）。append 失败时内存会回滚到追加前的状态，避免文件里出现指向缺失父节点的 entry。

默认 leaf 的来源在 `_buildIndex`：它按文件物理顺序遍历，逐条把 `leafId` 设成当前 `entry.id`，所以最后一条 entry 自然成为 leaf；label 同时被解析进 `labelsById` / `labelTimestampsById`，清除 label 就是把对应项删掉。

```typescript
	private _buildIndex(): void {
		this.byId.clear();
		this.labelsById.clear();
		this.labelTimestampsById.clear();
		this.leafId = null;
		for (const entry of this.fileEntries) {
			if (entry.type === "session") continue;
			this.byId.set(entry.id, entry);
			this.leafId = entry.id;
			if (entry.type === "label") {
				if (entry.label) {
					this.labelsById.set(entry.targetId, entry.label);
					this.labelTimestampsById.set(entry.targetId, entry.timestamp);
				} else {
					this.labelsById.delete(entry.targetId);
					this.labelTimestampsById.delete(entry.targetId);
				}
			}
		}
	}
```

会话默认写在 `~/.pi/agent/sessions/--<编码后的 cwd>--/` 下，文件名是 `<timestamp>_<session-id>.jsonl`；除非用 `--no-session` 显式关掉持久化（关掉后是不可恢复的内存会话）。存储位置的三级优先级：

```text
--session-dir <dir>            # CLI 参数，最高
PI_CODING_AGENT_SESSION_DIR    # 环境变量
sessionDir 设置                # settings.json，最低
```

其他会话入口：

| 入口 | 行为 |
| :--- | :--- |
| `pi --continue`（`-c`） | 打开当前工作目录最近的会话 |
| `pi --resume`（`-r`） | 打开会话挑选器（交互内同名 `/resume`） |
| `pi --session <path\|id>` | 按路径、精确 ID 或部分 ID 打开；跨项目命中会提议 fork |
| `pi --session-id <id>` | 打开指定项目会话 ID，不存在则创建 |
| `pi --fork <path\|id>` | 把已有会话 fork 成当前项目的新会话 |
| `pi --name <name>`（`-n`） | 设置会话显示名（交互内 `/name`） |

会话挑选器支持搜索、改名、删除，也能显示路径、切换排序、过滤「仅有名字」的会话（`ctrl+p` / `ctrl+s` / `ctrl+n` / `ctrl+r` / `ctrl+d`）。`/session` 随时查看当前会话的文件、ID、消息数、token 用量与成本。约束：`--fork` 不能与 `--session` / `--continue` / `--resume` / `--no-session` 组合；会话 ID 首尾必须是字母或数字。

## Branches, Fork and Clone

三种分支操作的分工：

| 操作 | 作用范围 | 适用场景 |
| :--- | :--- | :--- |
| `/tree` | 在**当前会话文件内**移动 | 相关备选方案想留在同一棵树里 |
| `/fork` | 从某条早期 user message **新建会话** | 备选方案应成为独立的工作 |
| `/clone` | 把活跃分支**复制**成新会话 | 想要当前状态的一份独立副本 |

`branch()` 的实现只有一件事：把 `leafId` 移到目标 entry。它不修改、不删除任何历史 entry；下一次 `appendXXX()` 才会以该 entry 为父节点，形成新分支。

```typescript
	/**
	 * Start a new branch from an earlier entry.
	 * Moves the leaf pointer to the specified entry. The next appendXXX() call
	 * will create a child of that entry, forming a new branch. Existing entries
	 * are not modified or deleted.
	 */
	branch(branchFromId: string): void {
		if (!this.byId.has(branchFromId)) {
			throw new Error(`Entry ${branchFromId} not found`);
		}
		this.leafId = branchFromId;
	}
```

离开一个分支时，Pi 会提议给被放弃的分支生成摘要：`branchWithSummary()` 先把 `leafId` 移到导航目标，再追加一条 `branch_summary`（`fromId` 记下被放弃路径的原 leaf），相关工作的上下文因此进入新分支，而不必把每条消息都搬过去。

`fork` 与 `clone` 共用 `runtimeHost.fork(entryId, { position })`，**区别只在 `position`**：

```typescript
	async fork(
		entryId: string,
		options?: { position?: "before" | "at"; withSession?: (ctx: ReplacedSessionContext) => Promise<void> },
	): Promise<{ cancelled: boolean; selectedText?: string }> {
		const position = options?.position ?? "before";
		const beforeResult = await this.emitBeforeFork(entryId, { position });
		if (beforeResult.cancelled) {
			return { cancelled: true };
		}
		let targetLeafId: string | null;
		let selectedText: string | undefined;

		const selectedEntry = this.session.sessionManager.getEntry(entryId);
		if (!selectedEntry) {
			throw new Error("Invalid entry ID for forking");
		}

		if (position === "at") {
			targetLeafId = selectedEntry.id;
		} else {
			if (selectedEntry.type !== "message" || selectedEntry.message.role !== "user") {
				throw new Error("Invalid entry ID for forking");
			}
			targetLeafId = selectedEntry.parentId;
			selectedText = extractUserMessageText(selectedEntry.message.content);
		}
```

- **fork**（`position: "before"`，默认）：必须选中一条 user message，从它的 `parentId` 派生新会话，并把该 user message 的文本抽出来**回编辑器**（`selectedText`），改完再提交即从该点分叉。
- **clone**（`position: "at"`）：以选中的当前 leaf 为起点复制，没有回编辑器的文本；交互模式与 RPC 模式调用时都显式传 `"at"`。

两者最终都落到 `createBranchedSession(targetLeafId)`：只取 root→目标 leaf 的一条路径写入新文件，header 的 `parentSession` 指向原文件。在 `/tree` 里选中 user message 会把文本带回编辑器，选中 assistant 回复或其他条目则从该条目之后以空编辑器续写。

## Labels and Context Edits

label 不是旁挂的索引，而是**真正的树节点**：`LabelEntry` 继承 `SessionEntryBase`，后续 entry 可以把它当父节点。清除 label 不是删条目，而是**追加一条 `label: undefined` 的 label entry**，由 `_buildIndex` / `getLabel()` 在读取时解析为「已清除」。

```typescript
	/**
	 * Set or clear a label on an entry.
	 * Labels are user-defined markers for bookmarking/navigation.
	 * Pass undefined or empty string to clear the label.
	 */
	appendLabelChange(targetId: string, label: string | undefined): string {
		if (!this.byId.has(targetId)) {
			throw new Error(`Entry ${targetId} not found`);
		}
		const entry: LabelEntry = {
			type: "label",
			id: generateId(this.byId),
			parentId: this.leafId,
			timestamp: new Date().toISOString(),
			targetId,
			label,
		};
		this._appendEntry(entry);
		if (label) {
			this.labelsById.set(targetId, label);
			this.labelTimestampsById.set(targetId, entry.timestamp);
		} else {
			this.labelsById.delete(targetId);
```

`appendContextEdit()` 只允许编辑当前活动分支上的 user / assistant / toolResult / custom_message，校验通过后同样以 append 方式落盘，绝不回改目标 entry：

```typescript
		if (!editable) throw new Error(`Entry ${targetId} does not contribute editable model content`);
		const targetRole = target.type === "message" ? target.message.role : "custom";
		const normalizedReplacement =
			replacement !== null &&
			(targetRole === "assistant" || targetRole === "toolResult") &&
			typeof replacement.content === "string"
				? { content: [{ type: "text" as const, text: replacement.content }] }
				: replacement;
		const entry: ContextEditEntry = {
			type: "context_edit",
			id: generateId(this.byId),
			parentId: this.leafId,
			timestamp: new Date().toISOString(),
			targetId,
			replacement: normalizedReplacement,
		};
		this._appendEntry(entry);
		return entry.id;
	}
```

## Compaction and Export

压缩不会删除历史：`compaction` entry 只是给投影提供摘要和 checkpoint，原始消息仍留在树里，检索与导出看到的都是完整历史（导出只受「当前分支」限制）。JSONL 导出的关键动作是遍历 `getBranch()`，逐条把 `parentId` 重链成新文件里的前一条 id，使导出的单分支成为一条干净的链：

```typescript
/** Serialize the current branch and optional export-only entries as JSONL. */
export function serializeSessionBranch(
	sessionManager: SessionManager,
	createTrailingEntries?: TrailingEntries,
): string {
	const timestamp = new Date().toISOString();
	const header: SessionHeader = {
		type: "session",
		version: CURRENT_SESSION_VERSION,
		id: sessionManager.getSessionId(),
		timestamp,
		cwd: sessionManager.getCwd(),
	};
	const entries: object[] = [header];
	let parentId: string | null = null;
	for (const entry of sessionManager.getBranch()) {
		entries.push({ ...entry, parentId });
		parentId = entry.id;
	}
	entries.push(...(createTrailingEntries?.(parentId, timestamp) ?? []));
	return `${entries.map((entry) => JSON.stringify(entry)).join("\n")}\n`;
}
```

- `/export`：把当前会话存为 HTML 或 JSONL；CLI 侧对应 `pi --export <input> [output]`。
- `/share`：上传会话并拿一个查看链接。默认走 Radius 制品（配了 Radius 登录时）；否则经 GitHub CLI 建**私有 gist**。`sessionShareDestination` 设置可强制 `gist` 或 `radius`。

导出/分享前先过一遍内容——会话里可能有提示词、工具参数、命令输出、文件内容和对话中暴露的凭证。同理，`/bug [description]` 生成的诊断报告默认可以不带 transcript，带上之前也要 review。

## Two Independent Stores

Pi 的会话存储与 `pi-durable` 是**两套独立存储、无代码依赖**：`packages/coding-agent/package.json` 不依赖 `packages/durable`，反向也没有；源码里只有一条「保持同步」的注释提到对方，没有 import。前者是 app 层的会话 JSONL 树，后者是面向应用的通用 durable state/store；不要把它们当成同一份状态的两层封装。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Durable：持久状态](/docs/CS/AI/LLM/Agent/Product/Pi/Durable.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)

## References

- [Pi Sessions and Context](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/sessions.md)
- [Pi Session Format](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/session-format.md)
- [Pi Command Line](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/cli.md)
- [session-manager.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/session-manager.ts)
- [session-export.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/session-export.ts)
- [agent-session-runtime.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/agent-session-runtime.ts)
