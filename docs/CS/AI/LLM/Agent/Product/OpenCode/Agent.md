> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。v1.19.5 并存**两套权限实现**：主运行链路（`session/processor.ts`、`tool/`、`agent/agent.ts`）用 **V1**（三元组 `permission / pattern / action`）；`packages/core/src/permission.ts` 是 **V2**（三元组 `action / resource / effect`）。本文以 V1 为主，V2 作为对照；`permission/evaluate.ts` 实为 V1 的一行 re-export。

## Introduction

OpenCode 的 Agent 体系是它和"Tab 补全自动接受一切"类工具的分野：**两个主 Agent（build / plan）默认共存、Tab 循环**，子 Agent 由主 Agent 经 task 工具调度。驱动整套体系的是权限模型——每条规则是三态 `allow`/`ask`/`deny`，求值用 `findLast` 实现"最后匹配者胜"。

几个反直觉点（均以源码纠正旧文档口径）：

- **"13 个权限键"只在文档层成立**：配置 schema `ConfigPermissionV1.InputObject` 显式声明 **15 个**，末尾还开任意字符串键兜底；`plan_enter`/`plan_exit` 被实际使用却不在显式表内。`task` 确实是权限键（pattern = 子 agent 类型）。
- **`.env` 默认值源码与文档直接冲突**：源码 `defaults.read` 为 `*.env: "ask"`、`*.env.*: "ask"`、`*.env.example: "allow"`；文档写 `"deny"`。按 last-match-wins，`.env.example` 放行、`.env`/`.env.production` 是"弹确认"而非硬拒绝。
- **"最后匹配者胜"被证实，但"默认态"有两个不同来源**：evaluate 的 `?? {action:"ask"}` 只在零规则命中时生效；日常"默认全放行"来自默认策略里的 `"*": "allow"`。
- **内置子 agent 是 `general`/`explore`，没有 `scout`**；父 agent 的限制不会整体继承，只有 `deny` 与 `external_directory` 规则下传。

## Built-in Agents

`packages/opencode/src/agent/agent.ts` 里两个主 Agent 都是 `native: true, mode: "primary"`。plan 通过权限规则禁用所有编辑、只允许写计划目录：

```typescript
build: {
  name: "build", mode: "primary", native: true,
  permission: Permission.merge(defaults, Permission.fromConfig({
    question: "allow", plan_enter: "allow",
  }), user),
},
plan: {
  name: "plan", mode: "primary", native: true,
  permission: Permission.merge(defaults, Permission.fromConfig({
    question: "allow", plan_exit: "allow",
    task: { general: "deny" },
    external_directory: { [path.join(Global.Path.data, "plans", "*")]: "allow" },
    edit: {
      "*": "deny",
      [path.join(".opencode", "plans", "*.md")]: "allow",
      [path.relative(ctx.worktree, path.join(Global.Path.data, "plans", "*.md"))]: "allow",
    },
  }), user),
},
```

子 Agent：`general`、`explore`（`native: true, mode: "subagent"`），外加隐藏的 `compaction`/`title`/`summary`（`mode: "primary", hidden: true`）。`general` 仅追加 `todowrite: deny`；`explore` 先用 `"*": "deny"` 全封再逐个 allow（`grep`/`glob`/`list`/`bash`/`webfetch`/`websearch`/`read`）。**没有 `scout`**。

Tab 循环绑定在 `config/keybind.ts`（`tab` → `agent.cycle`），`move()` 只在非 subagent 且非 hidden 的 agent 间循环：

```typescript
const agents = createMemo(() => sync.data.agent.filter((agent) => agent.mode !== "subagent" && !agent.hidden))
move(direction: 1 | -1) {
  const current = this.current()
  if (!current) return
  let next = agents().findIndex((x) => x.name === current.name) + direction
  if (next < 0) next = agents().length - 1
  if (next >= agents().length) next = 0
  setAgentStore("current", agents()[next].name)
}
```

另有 plan 模式切换的第二条路径：`session/index.tsx` 里 plan_enter/plan_exit 工具命中时直接 `local.agent.set("plan"/"build")`。

## Permission Keys and Evaluation

权威定义在 `packages/core/src/v1/config/permission.ts`，显式 15 个键：

```typescript
const InputObject = Schema.StructWithRest(
  Schema.Struct({
    read: Schema.optional(Rule), edit: Schema.optional(Rule), glob: Schema.optional(Rule),
    grep: Schema.optional(Rule), list: Schema.optional(Rule), bash: Schema.optional(Rule),
    task: Schema.optional(Rule), external_directory: Schema.optional(Rule),
    todowrite: Schema.optional(Action), question: Schema.optional(Action),
    webfetch: Schema.optional(Action), websearch: Schema.optional(Action),
    lsp: Schema.optional(Rule), doom_loop: Schema.optional(Action), skill: Schema.optional(Rule),
  }),
  [Schema.Record(Schema.String, Rule)],
)
```

`task` 是可细分的 `Rule`（对象语法），pattern 匹配子 agent 类型名（如 `general`）；plan agent 的 `task: { general: "deny" }` 即一例。三态 `allow | deny | ask`（V2 叫 Effect，字面相同）。

**"最后匹配者胜"**在 V1/V2 两代都用 `Array.prototype.findLast`：

```typescript
export function evaluate(permission: string, pattern: string, ...rulesets: PermissionV1.Ruleset[]): PermissionV1.Rule {
  return rulesets.flat().findLast((rule) =>
    Wildcard.match(permission, rule.permission) && Wildcard.match(pattern, rule.pattern),
  ) ?? { action: "ask", permission, pattern: "*" }
}
```

两层 glob 匹配：权限键本身是 pattern，资源/命令也是 pattern，两者都要命中。glob 实现（`core/src/util/wildcard.ts`）是简单通配符而非 minimatch：把 `\` 归一为 `/`、转义正则元字符、`*` → `.*`、`?` → `.`，Windows 下不区分大小写。`fromConfig` 依赖对象键的**插入顺序**（`propertyOrder: "original"` 保留用户键序），所以"catch-all `*` 放前、具体规则放后"是有效写法。

## The Ask Channel

`ask` 让工具调用阻塞在一个 `Deferred` 上，同时经 `EventV2Bridge` 发布 `permission.asked` 事件（SSE 推给客户端），客户端通过 `POST .../permission/:requestID/reply` 回写完成 Deferred：

```typescript
const ask = Effect.fn("Permission.ask")(function* (input: PermissionV1.AskInput) {
  const { approved, pending } = yield* InstanceState.get(state)
  const { ruleset, ...request } = input
  let needsAsk = false
  for (const pattern of request.patterns) {
    const rule = evaluate(request.permission, pattern, ruleset, approved)
    if (rule.action === "deny") return yield* new PermissionV1.DeniedError({ /* ... */ })
    if (rule.action === "allow") continue
    needsAsk = true
  }
  if (!needsAsk) return
  const id = request.id ?? PermissionV1.ID.ascending()
  const deferred = yield* Deferred.make<void, PermissionV1.RejectedError | PermissionV1.CorrectedError>()
  pending.set(id, { info, deferred })
  yield* events.publish(Event.Asked, info)
  return yield* Effect.ensuring(Deferred.await(deferred), Effect.sync(() => { pending.delete(id) }))
})
```

- 任一 pattern `deny` → 立即抛 `DeniedError`（直接拒绝、不询问）；全部 `allow` → 放行；否则 `ask`。
- 回复三态 `once | always | reject`：`reject` 走 `Deferred.fail` 并连带拒绝同 session 其他 pending；`always` 把 `always` 里的 pattern 写入**内存** `approved` 并连带放行同 session 中已满足的请求。
- **V1 的 `always` 只在内存**（服务重启失效）；V2 通过 `PermissionSaved` **落库**——两代重要差异。

`arity.ts` 是一张"命令前缀 → token 数"的字典（`cat/cd/rm: 1`、`git: 2`、`git config: 3`、`npm run: 3` 等约 130 条），用于把 shell 命令规约成人类可理解的前缀 pattern（`git status --porcelain` → `git status *`）。它**不参与 evaluate**，只在 approve always 时生成白名单 pattern。

## Default Policy

默认规则集中在 `agent/agent.ts` 的 `defaults`，用 `Permission.fromConfig` 展开成 ruleset，再用 `merge(defaults, ..., user)` 拼接（user 最后覆盖）：

```typescript
const defaults = Permission.fromConfig({
  "*": "allow",
  doom_loop: "ask",
  external_directory: {
    "*": "ask",
    ...Object.fromEntries(whitelistedDirs.map((dir) => [dir, "allow"])),
  },
  question: "deny", plan_enter: "deny", plan_exit: "deny",
  // mirrors github.com/github/gitignore Node.gitignore pattern for .env files
  read: {
    "*": "allow", "*.env": "ask", "*.env.*": "ask", "*.env.example": "allow",
  },
})
```

`"*": "allow"` 是兜底通配；`doom_loop`/`external_directory["*"]="ask"` 是显式收紧。按 last-match-wins，`*.env.example: allow` 排在 `*.env.*: ask` 之后故放行。`Permission.merge = (...rulesets) => rulesets.flat()`，因此**数组顺序即优先级**：defaults < agent 内置 < 全局 user < 该 agent 的 user config。

## Subagent Permission Inheritance

`subagent-permissions.ts` 的关键点：子 agent 的能力主要来自它自己的 `permission`，父 agent 的限制**只有 deny 规则与 external_directory** 下传；若子 agent 未显式声明 `task`/`todowrite` 权限，默认 deny 防止再派生或写 todo：

```typescript
export function deriveSubagentSessionPermission(input: {
  parentSessionPermission: PermissionV1.Ruleset
  subagent: Agent.Info
}): PermissionV1.Ruleset {
  const canTask = input.subagent.permission.some((rule) => rule.permission === "task")
  const canTodo = input.subagent.permission.some((rule) => rule.permission === "todowrite")
  return [
    ...input.parentSessionPermission.filter(
      (rule) => rule.permission === "external_directory" || rule.action === "deny",
    ),
    ...(canTodo ? [] : [{ permission: "todowrite", pattern: "*", action: "deny" }]),
    ...(canTask ? [] : [{ permission: "task", pattern: "*", action: "deny" }]),
  ]
}
```

该 helper 由 `tool/task.ts` 派生子会话时调用；仓库自带回归测试 `test/agent/plan-mode-subagent-bypass.test.ts` 验证"子 agent 自身权限优先于父 agent 限制"。

## Custom Agents

全局放 `~/.config/opencode/agents/`、项目放 `.opencode/agents/`，Markdown 声明的文件名（去 `.md`）即 Agent 名；也可在 `opencode.json` 的 `agent` 键用 JSON 声明。字段（由 `core/src/v1/config/agent.ts` 的 normalize 处理）：`mode`（primary/subagent/all）、`model`、`prompt`（支持 `{file:./prompts/x.txt}`）、`temperature`、`top_p`、`steps`（最大迭代轮数，替代废弃的 maxSteps）、`permission`、`hidden`、`color`，其他键透传给 provider 作为模型参数。

旧的 `tools` 布尔字段被转换成 permission（`true` → allow、`false` → deny），write/edit/patch 统一映射到 edit：

```typescript
const permission: ConfigPermissionV1.Info = {}
for (const [tool, enabled] of Object.entries(agent.tools ?? {})) {
  const action = enabled ? "allow" : "deny"
  if (tool === "write" || tool === "edit" || tool === "patch") { permission.edit = action; continue }
  permission[tool] = action
}
globalThis.Object.assign(permission, agent.permission)
```

## Links

- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) / [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md)
- [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md) / [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [opencode/src/agent/agent.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/agent/agent.ts)
2. [opencode/src/permission/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/permission/index.ts)
3. [opencode/src/permission/arity.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/permission/arity.ts)
4. [agent/subagent-permissions.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/agent/subagent-permissions.ts)
5. [core/src/permission.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/permission.ts)
