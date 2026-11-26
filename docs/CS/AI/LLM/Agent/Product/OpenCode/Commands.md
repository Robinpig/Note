> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文基于 `packages/opencode/src/command/`、`config/command.ts` 与 `session/prompt.ts` 的命令模板展开逻辑。v1.19.1 起 session sharing 停用，`--share` 是隐藏的废弃参数。

## Introduction

OpenCode 的斜杠命令分两类：内置命令与自定义命令。内置命令是 TUI 内常用的会话/模型/视图操作；自定义命令是一段可参数化的提示词模板，用来把重复任务固化下来。命令表的真正来源比文档复杂——`Command.Service` 层硬编码的只有 2 个（`init`、`review`），其余来自 config、MCP prompts 与 skills。

几个反直觉点：

- **`argument-hint` 字段在 1.19.5 源码中不存在**（全 `packages/` Grep 零命中）：实际是 `hints()` 函数从模板文本自动反推 `$1/$2…` + `$ARGUMENTS`。
- **`!` 前缀的真实语法是 `` !`command` ``**（感叹号紧跟反引号），且执行用 `nothrow: true`——命令失败静默替换为空，不报错。
- **"内置命令"混了两个来源**：`init`/`review` 在 `Command.Service`；`undo`/`redo`/`compact`/`fork` 是 TUI 路由层命令；`help`/`exit` 在 TUI app 层。`/share` 名存实亡。

## Command Sources

`packages/opencode/src/command/index.ts` 里 `Command.Service` 层硬编码的只有两个：

```typescript
export const Default = { INIT: "init", REVIEW: "review" } as const
// ...
commands[Default.INIT] = {
  name: Default.INIT, description: "guided AGENTS.md setup", source: "command",
  get template() { return PROMPT_INITIALIZE.replace("${path}", ctx.worktree) },
  hints: hints(PROMPT_INITIALIZE),
}
commands[Default.REVIEW] = {
  name: Default.REVIEW, description: "review changes [commit|branch|pr], defaults to uncommitted",
  source: "command", subtask: true,
  get template() { return PROMPT_REVIEW.replace("${path}", ctx.worktree) },
  hints: hints(PROMPT_REVIEW),
}
```

`review` 带 `subtask: true`（强制走子代理），`init` 不带。命令表还会并入三类来源：`cfg.command`（自定义）、`mcp.prompts()`（`source:"mcp"`）、`skill.all()`（`source:"skill"`）——这解释了为什么 MCP prompt 和 skill 也能出现在斜杠命令补全里。

## Custom Commands

扫描 `{command,commands}/**/*.md`（全局 `~/.config/opencode/commands/`、项目 `.opencode/commands/`），文件名（去掉前缀）即命令名，frontmatter 用 `gray-matter` 解析：

```typescript
for (const item of await Glob.scan("{command,commands}/**/*.md", {
  cwd: dir, absolute: true, dot: true, symlink: true,
})) {
  const md = await ConfigMarkdown.parse(item).catch(() => undefined)
  if (!md) continue
  const name = configEntryNameFromPath(path.relative(dir, item), ["command/", "commands/"])
  const config = { name, ...md.data, template: md.content.trim() }
  const parsed = decodeInfo(config, { errors: "all", propertyOrder: "original" })
  if (Exit.isSuccess(parsed)) { result[config.name] = parsed.value; continue }
  throw new InvalidError({ path: item, message: Cause.pretty(parsed.cause) })
}
```

frontmatter 合法字段由 `core/src/v1/config/command.ts` 的 `Info` schema 决定：

```typescript
export const Info = Schema.Struct({
  template: Schema.String,
  description: Schema.optional(Schema.String),
  agent: Schema.optional(Schema.String),
  model: Schema.optional(Schema.String),
  variant: Schema.optional(Schema.String),
  subtask: Schema.optional(Schema.Boolean),
})
```

即实际字段是 **template / description / agent / model / variant / subtask**。hints 由 `hints()` 从模板里的 `$1/$2…` 占位符与 `$ARGUMENTS` 自动反推，没有独立的 `argument-hint` 配置。

## Template Expansion

模板展开在 `session/prompt.ts` 的 `SessionPrompt.command`。`$1…$n` 按位置替换，最大编号位吃掉剩余参数（`args.slice(argIndex).join(" ")`），`$ARGUMENTS` 整体替换；若模板既无编号占位也无 `$ARGUMENTS` 而用户传了参数，就整体追加到末尾：

```typescript
const raw = input.arguments.match(argsRegex) ?? []
const args = raw.map((arg) => arg.replace(quoteTrimRegex, ""))
const templateCommand = yield* Effect.promise(async () => cmd.template)
const placeholders = templateCommand.match(placeholderRegex) ?? []
let last = 0
for (const item of placeholders) {
  const value = Number(item.slice(1))
  if (value > last) last = value
}
const withArgs = templateCommand.replaceAll(placeholderRegex, (_, index) => {
  const position = Number(index)
  const argIndex = position - 1
  if (argIndex >= args.length) return ""
  if (position === last) return args.slice(argIndex).join(" ")
  return args[argIndex]
})
let template = withArgs.replaceAll("$ARGUMENTS", input.arguments)
if (placeholders.length === 0 && !usesArgumentsPlaceholder && input.arguments.trim()) {
  template = template + "\n\n" + input.arguments
}
```

正则常量：

```typescript
const bashRegex = /!`([^`]+)`/g
const argsRegex = /(?:\[Image\s+\d+\]|"[^"]*"|'[^']*'|[^\s"']+)/gi
const placeholderRegex = /\$(\d+)/g
const quoteTrimRegex = /^["']|["']$/g
```

`` !`command` `` 的 shell 替换：匹配到的命令用 `Process.text(..., { shell: sh, nothrow: true })` 并发执行，结果回填模板（失败不报错）：

```typescript
const shellMatches = ConfigMarkdown.shell(template)
if (shellMatches.length > 0) {
  const sh = Shell.preferred(cfg.shell)
  const results = yield* Effect.promise(() =>
    Promise.all(shellMatches.map(async ([, cmd]) => (await Process.text([cmd], { shell: sh, nothrow: true })).text)),
  )
  let index = 0
  template = template.replace(bashRegex, () => results[index++])
}
```

`@file` 引用由 `config/markdown.ts` 的 `FILE_REGEX = /(?<![\w`])@(\.?[^\s`,.]*(?:\.[^\s`,.]+)*)/g` 匹配，`resolvePromptParts` 解析：先按 `~/` 或相对 worktree 解析路径、stat 存在就作为 file part；不存在则尝试按 agent 名解析为 agent part——这就是 `@ 文件` 与 `@子agent` 共用的语法。

## The Deprecated Share

自 v1.19.1 起 session sharing 停用。CLI 的 `--share` 参数仍在但 `hidden: true`、描述 "deprecated: session sharing was discontinued"，实际只打印一行警告：

```typescript
async function share(_sdk: OpencodeClient, _sessionID: string) {
  if (args.share) UI.println(UI.Style.TEXT_DANGER_BOLD + "!  Session sharing has been discontinued")
}
```

## Links

- [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md) / [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) / [TUI](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [opencode/src/command/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/command/index.ts)
2. [opencode/src/config/command.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/config/command.ts)
3. [opencode/src/session/prompt.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/prompt.ts)
4. [core/src/v1/config/command.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/v1/config/command.ts)
5. [OpenCode Commands 文档](https://opencode.ai/docs/commands/)
