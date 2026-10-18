## Introduction

**Mod** 是 Claude Code 插件的一种形态：hook 不写成 JSON 配置，而是写成**在 Claude Code 进程内运行的 JavaScript / TypeScript 函数**。v2.1.287 起官方称之为「Claude Mods: plugins may now modify deeper behavior」——它与 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md) 的 JSON hooks 并存，是同一插件包里两条独立的 hook 通道。

本文的事实基线不是文档，而是官方仓库里的**类型契约** [`mods/types/claude-code.d.ts`](https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts)（517KB / 13440 行，由 `/plugin-types` 命令生成，首行标注写入它的 Claude Code 版本）。它比文档和 CHANGELOG 都精确一个数量级——常量是**字面量**、事件名是**联合类型**、参数是**完整签名**。仓库 `mods/` 下另有五个可读的完整实现（`diff`、`sec-default`、`agents-md`、`telemetry`），本文的实现细节亦据其坐实。

本文只讲**接口面**；这些 mod 的**源码级实现机制**（给 `$` 添加 noun、跨 mod 契约、测试布局、宿主抽象、内置退场机制）见 [ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md)。

⚠️ 一个必须提防的落差：契约由 **2.1.277** 生成，而客户端基线已到 **2.1.302**——**25 个小版本之间的新增接口不在契约里**（`$.telemetry` 就是现成例子）。读 mod 源码比读契约更能反映引擎实际提供了什么。

## The Module Contract

契约开篇即规定了运行环境，这是写 mod 前必须知道的前提：

- 运行环境**自成一界**：无 DOM、无 Node。不是 `require`，一律 ES module。
- 模块及其导入的每个文件的扩展名必须是 `.ts` / `.tsx` / `.jsx` / `.js` / `.mjs` / `.cjs` / `.mts` / `.cts`，**其余名字不加载**。
- 可用全局只有 `h` 与 `Fragment`（JSX 编译目标）、JSX namespace，以及 Web API（`URL`、`TextEncoder`、`AbortController`、`crypto.subtle` 等）。
- **UI 元素不是全局**：`Box` / `Text` / `Button` 等要从 surface 表里取——`const { Box, Text } = $.ui.resolve(e)`。
- 入口签名只有一个：`export const register: Register = (on, options) => ...`，其中 `Register = (on: On, options: PluginOptions) => unknown`。

⚠️ 契约首行注明 **EARLY ACCESS：此表面可能在小版本间无预告变更**。第一行还会写明是哪个 Claude Code 版本生成的——更新后应重新生成而非手改。

## The `$` Host Interface

`CoreEngineInterface` 是宿主对象，共 **18 个命名空间**：

| 命名空间 | 方法 |
| :--- | :--- |
| `ui` | `resolve` / `render` / `open` / `close` / `panes` / `scroll` / `focus` / `notice` / `invalidate` / `toast` / `log` / `status` / `ask` / `blit` |
| `session` | `messages` / `cwd` / `root` / `model` / `turns` / `id` / `repo` / `surfaces` / `surface` / `usage` / `version` / `compact` / `append` / `authorize` / `attach` / `detach` |
| `prompt` | `submit` / `read` / `fill` / `suggest` / `compose` / `attachment` / `context` |
| `tool` | `list` / `call` / `check` / `register` / `describe` |
| `agent` | `spawn` / `list` / `register` / `offer` |
| `model` | `complete` / `fork` / `classify` |
| `command` | `list` / `run` / `register` / `describe` |
| `config` | `list` / `set` / `describe` |
| `fs` | `read` / `write` / `list` / `exists` / `stat` / `ancestors` |
| `store` | `get` / `set` / `delete` / `keys` |
| `clock` | `now` / `sleep` / `after` / `every` |
| `process` | `run` |
| `http` | `fetch` |
| `env` | `get` / `set` |
| `settings` | `read` |
| `mcp` | `call` |
| `audio` | `play` / `speak` |
| `turn` | `abort` |
| `plugin` | `register`（另有 `name` 与 `root` 两个只读字段） |

三点值得单独记：

- **`ui.resolve(e)` 按 surface 取元素**。四个渲染表面的元素集**并不相同**（见下节），所以取元素的代码必须按传入的 surface 解析，不能硬编码。
- **`mcp.call(server, tool, args)` 让 mod 能反向调 MCP 工具**——mod 与 MCP 不是单向的，mod 可以当 client。
- **`session.surfaces()` 与 `session.surface()` 分开**：一个会话可能同时跑在多个表面上（终端 + 桌面 + 移动），`surface()` 只给当前那个。

## Render Surfaces And Their Elements

元素表按**渲染表面**分别声明，这是实现里最容易踩的一处：

| 元素 | terminal | desktop | vscode | mobile |
| :--- | :---: | :---: | :---: | :---: |
| `Box` `Text` `Button` `Link` `Code` `Markdown` `Client` | ✅ | ✅ | ✅ | ✅ |
| `Input` `Select` | ✅ | ✅ | ✅ | ❌ |
| `Svg` | ❌ | ✅ | ✅ | ✅ |
| `Raster` `Image` | ✅ | ❌ | ❌ | ❌ |

移动端没有 `Input` / `Select`——这意味着**一个带输入框的面板在手机上根本画不出来**。栅格与位图只在终端可用，SVG 只在桌面/VS Code/移动可用。设计可移植面板时这是硬约束，不是降级问题。

## Events

契约里事件名是联合类型，可直接枚举出全集——**33 个 classic 事件 + 95 个 dotted 事件 = 128 个**。

**Classic 事件**（`hook_event_name`，即 JSON hooks 那套，mod 亦可挂）：`SessionStart` `SessionEnd` `UserPromptSubmit` `UserPromptExpansion` `PreToolUse` `PostToolUse` `PostToolUseFailure` `PostToolBatch` `PermissionRequest` `PermissionDenied` `Notification` `Stop` `StopFailure` `SubagentStart` `SubagentStop` `PreCompact` `PostCompact` `PreModelSwitch` `PostModelSwitch` `ConfigChange` `CwdChanged` `FileChanged` `DirectoryAdded` `MessageDisplay` `InstructionsLoaded` `Elicitation` `ElicitationResult` `TaskCreated` `TaskCompleted` `TeammateIdle` `Setup` `WorktreeCreate` `WorktreeRemove`。

**Dotted 事件**按命名空间：`ui.*`（`render` `open` `close` `panes` `scroll` `focus` `select` `input` `press` `message` `notice` `invalidate` `log` `resolve` `blit`）、`prompt.*`（`submit` `edit` `section` `fill` `suggest` `compose` `read` `attachment` `context`）、`tool.*`（`call` `check` `describe` `list` `register`）、`session.*`（20 个，含 `compact` `append` `attach` `detach` `receive` `measure` `usage` `authorize` `messages` `repo` `surfaces` `turns` `version` `cwd` `root` `model` `id` `start` `end`）、`turn.*`（`start` `step` `complete` `abort`）、`agent.*`（`spawn` `list` `register` `offer`）、`command.*`、`config.*`、`model.*`、`fs.*`、`store.*`、`clock.*`、`env.*`、`settings.*`、`mcp.*`、`audio.*`、`http.*`、`process.*`、`skill.prompt`、`attribution.text`、`engine.create`。

一个易忽略但重要的点：**引擎自身的方法也是事件**。契约原文——「引擎的事件（`CoreEventOf`）：插件的 `$.fs.write(...)` 是一次 dispatch，它上面的 hooks 看得见」。也就是说 mod 之间存在**可观测的调用链**：A mod 写文件，挂在 `fs.write` 上的 B mod hook 会被触发。这解释了 CHANGELOG 里那批「guard hook 跳过自己 `$` 调用之下的事件」的修复为何必要。

## Time And Failure Budgets

`HookBudget` 在契约里是**字面量常量**，不是可配置值：

```ts
type HookBudget = {
  readonly ms: 10_000;      // hook 本体的执行上限
  readonly catchMs: 1_000;  // .catch handler 自己的上限
  readonly lingerMs: 5_000; // 结束后仍可 linger 的时间
}
type HookFailure = {
  readonly kind: 'throw' | 'timeout';
  readonly message?: string;
  readonly budget: number;
}
```

CHANGELOG 只说「10 秒」，契约给出三个配额。`HookFailure` 只有两种 kind——**hook 失败只有「抛错」与「超时」，没有「被拒绝」**。注册回执类型 `Registration<F>` 只有 `catch` 一个成员，印证了 CHANGELOG 那条语义：`.catch` 只在 hook 自己 throw 或超时时被调用。

## Registration Tiers

`TIERS` 是五级只读元组，决定 hook 的执行顺序：

```ts
const TIERS: readonly ["prepend", "user", "append", "builtin", "core"]
```

即：插到最前 → 用户级 → 追加 → 内置 → 核心。核心层的 hook 最后跑——**组织管控靠 `core` 层实现，所以用户 hook 总在管控之前被看到**，这与后面「managed settings 权力削减」那些修复是一致的。

## Testing Surface

契约还定义了一套独立命名空间 `claude-code/testing`，由 `claude plugin test <dir>` 驱动，供插件的 `*.test.ts` / `*.test.tsx` 导入：

- 入口 `test(name, async ($) => {...})`，配套 `describe` / `expect` / `tier` / `mock`（`mock` 的 clock、store、env 从内存回答这些名词）。
- **`$.ui.mount({ plugin, surface, ... })` 在指定表面上通过插件画出组件**，返回可读可操作的绘制结果：按 key 找元素、按 Button、往 Input 里打字、驱动 `Client` 的 module（按键、指针、post、它的帧时钟）。每次操作由该表面的元素表定型，所以**同一份测试体跑几个表面就覆盖几个表面**。
- 关键设计取舍：它**只测 mod**（hook、各表面规则下返回的树、`Client` module），**不测表面的绘制实现**（不碰 Ink 的、桌面页面的）。

契约给的官方样例就是这个形态：

```ts
test('notes add up on every surface that takes input', async $ => {
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'notes', surface, ...BAND })
    await ui.input({ key: 'new', text: 'milk' })
    expect((await ui.find({ key: 'count' }))?.text).toBe('1 note')
    await ui.unmount()
  }
})
```

`claude plugin validate <dir>` 是另一半：它按引擎的方式读 manifest 与 hooks 模块源码，**在任何会话加载之前**报出模块会挂什么 hook、调了什么、以及引擎会拒绝什么。另有 `claude plugin validate --json` 输出 `gatingHooks`，逐条列出每个注册在 gating 点的 hook 是否带 `.catch`。

## Managed Settings Versus User Mods

组织管控的机器上，用户 mod 的权力被系统性削掉（CHANGELOG 2.1.289–2.1.299 一串修复）：

- 用户 mod **不能**让组织的守卫 hook 跳过检查，**不能**卸载组织插件——触发的后果是该 mod 自己被卸载。
- 用户 mod 的 `env.set` **不能**改动组织 managed settings 启动的命令 hook 所用的环境与 shell 前缀。
- 组织 MCP 工具名、managed 权限规则、managed hooks 对用户 mod 同样优先。
- 受管设置安装的 mod 额外拿到 `session.authorize()`（登录方式、组织、邮箱）与 `prompt.attachment`（读用户附在 prompt 上的图片/文档字节）。
- `/plugin` 与 `claude plugin validate` 会**点名**哪些 mod 的 hook 在组织管控处被跳过——这是排查「mod 不生效」的第一现场。

`TIERS` 给了机制侧的解释：管控 hook 落在 `core` 层（最后执行），用户 hook 在它之前跑但无法阻止它。

## Official Implementations

仓库 `mods/` 下的五个 mod 是可读的完整实现（含测试），是最精确的行为参考：

| mod | 规模 | 说明 |
| :--- | :--- | :--- |
| `diff` | 828 文件 / 503KB | 全库最大的 mod：把 diff 面板做成插件。`/diff` 在transcript 旁开未提交改动面板，每个改动文件一行、其下挂 hunks；面板随 Claude 编辑与跑命令实时刷新，**开着时轮询仓库 HEAD**所以别处的 commit / checkout 也能反映 |
| `telemetry` | 275 文件 / 160KB | 自建遥测上报 |
| `sec-default` | 195 文件 / 205KB | 默认安全策略，README 有 34KB 的规则说明——见 [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md) |
| `agents-md` | 75 文件 / 58KB | AGENTS.md 发现与加载 |
| `types` | 1 文件 / 517KB | 即本文依据的类型契约 |

`diff` 的 README 顺带说明了几个只有实测才知道的渲染语义：**面板的停靠位置由每次绘制的 `viewport` 决定**（全屏布局下靠 transcript 侧）；自动打开有**多重前置条件**——主循环本会话首次成功编辑（subagent 的编辑不触发）、终端够宽（用户没选过时 144 列，保持过则 110 列）、文件 checkpointing 开着；**停靠式面板会先取数再打开**，所以不会闪`Loading diff…`；而「引擎让出等待却没画出来」的打开请求会被撤销（避免日后 resize 又把它摆出来），但 `no-surface` 的打开请求会被保留——没人看见时不刷新，首次绘制时重读仓库。这些都是 `viewport` / `surface` 这两个契约字段的实际用法示范。

`agents-md` 的目录分层本身就是一份 mod 工程范式参考：把 `files`（文件发现）、`frames`（路径判定：`is-below` / `outside-claude-dirs` / `nested-frame`）、`modes`（模式解析，含 `legacy-mode-of`）、`switches`、`telemetry` 拆成独立模块，每个自带 `index.ts` 与 `types/`，并配 `tests/fixtures/`。

## Common Traps

- 元素不在全局里，必须 `$.ui.resolve(e)`；且不同 surface 元素集不同（见上表）。
- 移动端没有 `Input` / `Select`——带输入的面板无法在手机上存在。
- hook 失败只有 throw 与 timeout 两种，`catchMs` 只有 1 秒——`.catch` 里别做重活。
- `TIERS` 里管控在 `core`（最后执行），用户 hook 无法阻止它。
- 引擎方法即事件（`fs.write` 等），你的调用会触发别人挂的 hook——别指望「内部调用」是私密的。
- 别手改 `claude-code.d.ts`：更新后用 `/plugin-types` 重新生成。

## Links

- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)

## References

- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [mod 类型契约 `claude-code.d.ts`](https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts)
- [官方 mod 实现目录 `mods/`](https://github.com/anthropics/claude-code/tree/main/mods)
- [Claude Code on GitHub](https://github.com/anthropics/claude-code)