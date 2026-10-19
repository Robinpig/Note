## Introduction

前一篇 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) 讲的是 mod 的**接口面**（`$` 的命名空间、128 个事件、渲染表面、tier）。这一篇讲**实现机制**——从官方四个内置 mod 的真实源码（`diff` 828 文件 / `sec-default` 195 / `telemetry` 275 / `agents-md` 75，共约 13 万行 TypeScript）读出来的、文档与类型契约都不给的东西。

四个 mod 随 Claude Code 二进制一同构建发布，源码即仓库里的 `mods/`。官方给了一条读源码运行的命令：`claude --plugin-dir mods/diff`；测试用 `claude plugin test mods/diff`；类型检查用 `tsc -p mods/tsconfig.json`。

事实基线：官方仓库 [`anthropics/claude-code`](https://github.com/anthropics/claude-code) 的 `main`（2026-10-18 本地取全仓核对；`mods/types/claude-code.d.ts` 首行标注由 Claude Code **2.1.277** 生成，而当前客户端基线已是 **2.1.302**）。

## Mods Can Add Nouns To `$`

这是最反直觉也最 powerful 的机制：**插件可以给宿主对象添加自己的命名空间**，通过 `engine.create` 事件。

`EngineInterface` 在类型契约里是一个**空的 interface**：

```ts
export interface EngineInterface extends CoreEngineInterface {}
```

契约注释直接给了类比——**「像 jQuery 插件给 `$.fn` 加类型那样，用声明合并为自己提供的 noun 声明类型」**。所以 `$` 的完整类型 = `CoreEngineInterface`（18 个核心 noun）+ 每个插件通过 `engine.create` 加上的 noun。

`engine.create` 是**每次加载只跑一次**的折叠（fold），从最内层向外构建 `$`。一个 step 的权限边界写得极死：

| 可以 | 不可以 |
| :--- | :--- |
| **ADD** 自己的 noun | **替换**另一 step 已加的 noun——**该 step 失败，且同时点名两个插件** |
| **WITHHOLD** 一个 noun（留下它、或返回时不调 `next`） | — |

失败的 step 会导致**它的插件被卸载、`$` 重建**。

`$` 因此是**冻结**的（frozen，且「每一层深度都冻结」），调用时传入；声明合并的类型让插件代码能拿到自己加的 noun 的完整类型。

### A Worked Example: `$.telemetry`

`telemetry` mod 是这个机制的唯一实例，它做的事很具体：**让内置插件能记录一方 analytics 行**（`tengu_plugin_<event>`），批量发送。

它加的 noun 契约在 `mods/telemetry/types/index.d.ts`（131 行、无任何 import、自成一体）：

```ts
export type Telemetry = {
  log: (entry: TelemetryLogEntry) => Promise<void>
  mark: (entry: TelemetryMarkEntry) => Promise<void>
}
// ...
declare module "claude-code" {
  interface EngineInterface {
    telemetry: Telemetry
  }
}
```

它的策略边界值得单独记：**只服务编进 CLI 的插件，installed plugin 的调用一律 reject**；mod 未落座或缺席时不排队任何东西；**Claude Code 自己的 analytics 关掉的地方它也不发**。所以 `diff` 这个内置 mod 可以安全地调用 `$.telemetry.log(...)`——它和 `telemetry` mod 一样是内置的，而用户装的插件不能借此把自己混进一方分析数据里。

两个方法的语义也不同：`log` 发 `tengu_plugin_<event>`（调用方在 `event` 里自报家门）；`mark` 发 `tengu_feature_<kind>`，**不加插件前缀**，因为它要汇入全产品的 feature 事件面。值只接受**有限数字、布尔或 `TelemetryChoice`**，自由文本被拒。

## Noun Contracts: How Mods Depend On Each Other

这是整个 mod 体系里最实用的工程约定（官方 `mods/README.md` 有一整节）：

> 在 `engine.create` 折叠里给 `$` 加了某个 noun 的 mod，**拥有**那个 noun 的类型，并把它们放在一处：`types/index.d.ts`——一个无 import 的声明文件，导出该 noun 由之组成的类型，并在 `claude-code` 的 `EngineInterface` 上声明它。

三条规则：

1. **契约是该 noun 的唯一声明**。mod 自己的 hooks 从那个文件夹 import 类型（`import type { Telemetry } from '../types'`），而 `engine.create` hook 返回的值会被按 `EngineInterface['telemetry']` 检查——**所以实现无法与调用方读到的类型漂移**。
2. **调用别人 noun 的 mod 读同一个文件，绝不复制**。`mods/tsconfig.json` 包含 `*/types/**/*.d.ts`，所以 `diff` 里的 `$.telemetry.log(…)` 直接按 `telemetry` 的契约做类型检查——**别人改了契约，你这边立刻编译不过**。
3. **调用别人 noun 的 mod 的测试要「坐一个 provider」**——一个内联插件，其 `engine.create` hook 加上该 noun，行为与引擎自己的相同。**没有 provider 加载时，`$` 的构建会拒绝那个 hook，并点名无人提供的 noun。**

⚠️ 一条现存的限制：仓库外的插件若要依赖某个 mod 的 noun，目前得把 tsconfig 的 `include` 指向那个 mod 的 `types/` 目录；等引擎开始为会话已安装的插件写契约后，`/plugin-types` 会把它们放到 `claude-code.d.ts` 旁边，这个 include 就消失了。

## Test Layout Is A Convention Worth Stealing

官方测试的组织方式本身就值得抄：

- 测试文件**以它覆盖的模块命名、并放在旁边**——`register.test.ts` 紧邻 `hooks/register.ts`，`git.test.ts` 紧邻 `hooks/git/`。
- 一个测试文件持有自己的 import、**该 mod 加载所在的 tier**（`tier('builtin')`）、以及一个以该名字命名的 `describe`。
- 多个测试共享的东西放 `tests/fixtures/`，**一个文件一个导出**。
- `mock` 逐 noun 从内存回答 mod 下方的世界：`mock.env(on, vars)`、`mock.store(on, entries)`、`mock.clock(on)`。`clock.advance(ms)` 会把 mod 等待过的每一个等待（`$.clock.sleep` / `after` / `every`）在时钟跨过时结算。
- 想看某个 dispatch 在应答前做了什么：**不 await 地启动它，`await clock.settle()`，然后去看**——时钟会停在原处。
- 测试注册的 hook **位于 mod 之下**（世界所在处），其下**什么都没有**：它们未应答的调用会抛错并点名是哪个事件。

一个真实测试的开头长这样（官方例子）：

```ts
import { describe, expect, mock, test, tier } from 'claude-code/testing'

tier('builtin')

describe('register', () => {
  test('outside a git repository /diff says so, opens nothing', async ($, on) => {
    mock.clock(on)
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('process.run', () => ({ value: { exitCode: 128, stdout: '', stderr: 'fatal: not a git repository' } }))
    // ...
    expect(text).toContain("isn't in a git repository")
    expect(opened).toEqual([])
  })
})
```

注意 `on(...)` 的返回值形态：`{ cwd: e.cwd }`（`session.start` 的事件结果）、`{ value: {...} }`（noun 方法的结果）。**所有事件的答案是 `{value}` / `{deny}` / core 自己的 `{ref, result}` 三选一**——这是 mod 层最基础的结果协议。

## The Plugin Owns Its Own `$` Access

`diff` 里有一个值得学的模式：**把宿主包成一个窄接口，而不是到处用 `$.`**。`hooks/host/host.ts`（130 行）定义了 `Host` 类型——**只暴露该 mod 真正要用的成员**，每个成员注明它对应哪个 `$.` 调用：

```ts
export type Host = {
  now: () => Promise<number>          // $.clock.now
  after: TimerCall                     // $.clock.after
  run: (argv, init) => Promise<...>    // $.process.run
  stat: (path) => Promise<FsStat>     // $.fs.stat
  readFile: (path) => Promise<string>  // $.fs.read
  storeGet: (key) => Promise<unknown>  // $.store.get
  isCheckpointing: () => Promise<boolean>
  messages: () => Promise<SessionMessage[]>   // $.session.messages
  invalidate: () => void               // $.ui.invalidate("ui.render")
  openPane: (pane) => Promise<unknown> // $.ui.open
  mark: EngineInterface['telemetry']['mark']  // $.telemetry.mark
  log: EngineInterface['telemetry']['log']     // $.telemetry.log
}
```

好处有三个：换宿主不用改业务代码、**测试只需提供这个窄面**、以及「用了什么」一目了然。它还顺带证明了 `$.telemetry` 是真实存在的——而**这个成员在 517KB 的 `claude-code.d.ts` 里搜不到**，因为它由 `telemetry` mod 声明合并进去。

`isCheckpointing()` 那条注释还记了一个行为事实：**内置 diff 面板只在会话做 checkpoint 时才在编辑后自动打开**——这个 mod 精确复刻了内置的判定。

## Built-ins Stand Down, Mods Take Over

`diff` 的 `register.ts` 顶部注释描述了一个我没有在其他地方见过的模式：**内置功能「退场」后由插件接手**。

```
Registers the diff pane: /diff once the built-in stands down, the pane's
drawing and refresh, its opening on Claude's first edit, the ask.

Git runs when the built-in's would: none at the start; /diff or the main
loop's first checkpointed edit with room pins the backend, until /clear,
which reads afresh under a pane it leaves open.
```

代码里对应 `currentOf(engine) = () => host ?? engine`——**`Host` 是可替换的**：拿不到就退回引擎自己的 `$`。这是为了热重载：mod 重载后旧的 Host 失效，必须能退回引擎原始实现。

自动打开的判定（README 描述 + `record/shown-triggers` 实现）是一串**合取条件**：

| 条件 | 说明 |
| :--- | :--- |
| 主循环本会话首次成功编辑 | subagent 的编辑**不触发** |
| 终端够宽 | 用户从未选过时 **144 列**；保持过则 110 列；**用户关过就不再打扰** |
| 文件 checkpointing 开着 | 对应 `isCheckpointing()` |
| 表面支持停靠 | 停靠位置由每次绘制的 `viewport` 决定 |

三条易忽略的细节：**停靠式面板会先取数再打开**（所以永远不闪 `Loading diff…`）；「引擎让出等待却没画出来」的打开请求**被撤销**（免得日后 resize 又把它摆出来），但 `no-surface` 的请求**被保留**——没人看见时不轮询，首次绘制时重读仓库并记为已展示。

`mods/diff/hooks/` 的模块划分也值得看：`register`（编排）· `host`（宿主抽象）· `backend`（git 交互）· `pane-state` / `pane-toggle`（面板状态）· `views`（绘制）· `tools`（面板内的自定义工具）· `classify` · `limits` · `todos` · `git` · `ask`（打开前的询问）· `record`（宽度分桶、tab、recorder、已展示触发）。每个都是独立子目录、自带 `index.ts`——**一个目录一个概念**的极细分层，是 828 文件仍可读的原因。

## The Double-Run, As Coded

[Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md) 描述的 deny-hold 双跑机制，在源码里就是这个形状（`sec-default/hooks/register.ts`，全mod 208 行主体 + 1352 行 policy 子模块）：

```ts
on('tool.check', async ($, e, next) => {
  const answer = await next(e)                       // 第一跑：原样
  const mods = HeldVerdict.rewrittenByUsers(next.trace)   // 谁改写了？
  const shouldRecheck = mods.length > 0 && (await Policy.decidedByPolicy(..., Policy.denyRulesHold))
  if (!shouldRecheck) return answer

  const held = await next.to(e, 'append')            // 第二跑：摘掉 user 层
  if (!HeldVerdict.holdsOver(held, answer)) return answer
  // 逐个告知被拦下的插件，每会话每「名字+种类」只说一次
  for (const mod of mods.filter(name => !told.has(`${name} ${kind}`))) {
    told.add(`${mod} ${kind}`)
    $.ui.log(HeldVerdict.heldNotice(mod, e.tool, held,
      HeldVerdict.isLooser(answer, held) ? 'lift' : 'reword'))
  }
  return held
}).catch(async ($, e, next) => {
  const last = await next(e).catch(() => undefined)
  const shouldVouch = await Policy.decidedByPolicy(..., Policy.denyRulesHold)
  return shouldVouch ? HeldVerdict.caughtAnswer(last, next.trace) : last
})
```

比README 多出的两点：

- **`shouldRecheck` 要求 `mods.length > 0`** —— 没有插件改写过就**完全不加跑**，所以「只监听」或「只收紧」的插件不产生任何额外开销。
- **hook 自身失败时走 `.catch` 分支**：只能读第一跑的结果，用 `caughtAnswer` 判定——**裁决被改写过、或那一跑被拒绝，就用本插件自己的话拒绝**（因为规则与 hooks 从未被咨询过）。这正是 `HookFailure` 只有 `throw` / `timeout` 两种 kind 的实际落点。

policy 层同样印证了文档：`deny-rules-hold.ts` 只有 19 行，判定式就是 `isPersonWritable(policy) || ownOption(policy, 'allowModsToOverrideDenyRules') !== true`——**只有字面量 `true` 才松绑**，且个人可写的策略源（Windows `HKCU` 那种）不算数。

## What The Contract Does Not Know

一个必须提防的落差：类型契约标注 **EARLY ACCESS（可能在小版本间无预告变更）**，且它由 **2.1.277** 生成，而客户端已到 **2.1.302**——**25 个小版本之间的新增接口不会出现在契约里**（`$.telemetry` 就是现成例子）。所以读 mod 源码时，**`Host` 这类窄接口比类型契约更能反映引擎实际提供了什么**。

官方自己也在 `mods/README.md` 末尾声明了同一边界：hooks 模块只在函数 hook 开启处加载，**这些 mod 所依赖的 API 可能在小版本间无预告变更**；它们不在本仓库的 marketplace 里，**真正起作用的是已经在你 Claude Code 里的那些副本**。

## Git Interaction Without Stepping On The User

`diff` 要不停跑 git 读未提交改动，同时用户可能正在同一个仓库敲 git 命令。17 个 `git/` 子模块里两个常量把这件事处理得很干净：

```ts
// 每个探测都带这个 flag，好让一次读永远不抢用户 git 的 index 锁
export const NO_OPTIONAL_LOCKS = '--no-optional-locks'

// 覆盖每个 git 子进程的环境：C locale，让 --shortstat 与 git 消息在任何
// locale 下解析一致。其余一概不固定——与内置面板自己的 diff 子进程相同：
// partial clone 该lazy-fetch 就 lazy-fetch。
export const GIT_CHILD_ENV = { LC_ALL: 'C', LANGUAGE: '' } as const
```

这两条注释本身就是两条经验：

- **`--no-optional-locks`** —— 只读的 `git status` / `git diff` 默认也会去抢 `.git/index.lock`，用户此刻正在 `git add` 就会冲突失败。凡是后台轮询 git 的工具都该带这个 flag。
- **`LC_ALL=C`** —— 人类可读的 git 输出**不是稳定的接口**：commit graph 的相对时间（"2 days ago"）、shortstat 的数字分组（`1,234`）与措辞都随 locale 变。要解析就必须钉死 locale。但**其余环境刻意不固定**——钉死了会破坏 partial clone 的 lazy-fetch 行为（代理或稀疏检出时该拉的 blob 得让它拉）。

## Rendering Degrades By Terminal Width

面板在四个宽度档位间切换行为，档位边界是**内置面板自己的**，写成了具名常量：

```ts
export const WIDTH_BUCKETS = ['under_110', '110_to_143', '144_to_199', '200_plus'] as const
```

这解释了 README 里那两个魔数——**144 列是 `144_to_199` 的下界，110 是 `110_to_143` 的下界**，即「用户从未选过时用 `144_to_199` 档（宽屏才自动开），保持过（说明用户接受过较宽布局）则降到 `110_to_143`」。宽度不够时列表优先丢掉 agent 数与 token 数。

同类的具名常量还有触发来源：

```ts
export const SHOWN_TRIGGERS = ['auto_open', 'manual'] as const
```

**把「宽到什么程度」「什么触发的」写成枚举而不是散落的数字/布尔**，是这份源码的一致风格——遥测要按维度分组上报时，枚举比原始值有用得多。类似的还有 `git/` 下的 `git-base-modes`、`mark-outcome`、`base-outcomes`。

## AGENTS.md 的发现算法与它的 8 条边界

`agents-md`（75 文件）是一个受 `instructionFiles` 选项控制的 mod，四个取值：`claude-md`（只读 `CLAUDE.md`）、`claude-md-or-agents-md`（默认，项目自己没有指令文件时才用 `AGENTS.md`）、`claude-md-and-agents-md`（两者并用）、`managed-only`（丢掉项目与个人的，只留组织的）。

判定「项目自己的」是**读引擎实际加载了什么**，而不是猜：根到工作目录任一层有 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md`，整个项目就让给引擎。**组织的 managed 文件、`~/.claude/CLAUDE.md`、`.claude/rules` 不算**——因为嵌套遍历也看不见它们。

路径判定用**拼写而非解析**，源码里写得很直白：

```ts
export const isBelow = (path: string, dir: string): boolean =>
  normalSpellingOf(path).startsWith(`${normalSpellingOf(dir)}/`)
```

不跟随符号链接，与引擎给嵌套 `CLAUDE.md` 划界的方式一致。`outsideClaudeDirs` 则简单直接——**某目录有自己的 `CLAUDE.md`，该目录的 `AGENTS.md` 就让出去，而不是合并**。

### 它诚实列出的 8 条能力边界

这份 README 有一节专列「与 `CLAUDE.md` 仍有差异」，每条都点明是「一个插件通过现有事件够不到的事实」。这份清单本身就是插件能力边界的教科书：

1. **嵌套文件只随文本 `Read` 附加** —— 引擎还会在 `@` 提及的文件、IDE 打开的文件或选区、`Read` 的 notebook/图片/PDF 结果上附加。
2. **附加的嵌套文件不进入循环的已读文件状态** —— 所以压缩后引擎不会把它恢复进「最近读过」，而插件会在下次该目录下的 `Read` 再附一次；会话中途的修改也不会重新通告。
3. **`/cd` 的提示里带的是新树的 `CLAUDE.md`** —— 插件的文件走引擎的指令通告在下一个请求里一起到。
4. **路径按拼写比较** —— 引擎会先解析工作目录的符号链接别名再判断文件是否在内。
5. **`--add-dir` 目录不提供 `AGENTS.md`**，而引擎能加载那里的 `CLAUDE.md`。
6. **`/memory` 与 `#` 快捷键不认识 `AGENTS.md`**。
7. **`AGENTS.md` 内部的工作目录外 `@` 导入**，只在引擎为 `CLAUDE.md` 外部导入弹过审批之后才生效（且审批框只为 `CLAUDE.md` 的导入弹）。
8. **非 fork 的 subagent 会在自己首次 `Read` 某目录时拿到嵌套 `AGENTS.md`**，即使父循环已经拿到过；引擎不会这样重复给 subagent `CLAUDE.md`。

值得学的是**列边界的方式**：不是笼统说「还不完全」，而是逐条说明「这是哪个引擎行为插件够不到」。这种写法让使用者能自己判断在哪些场景下受影响。

还有一个**兼容策略**值得一提：该选项最初叫 `projectInstructions`、取值是 `claude` / `agents-fallback` / `both` / `none`。新键 `instructionFiles` 一旦被设成非默认值，**旧键就不再读**，且 transcript 会提示去删掉它；未设新键时旧值仍被解释，并在每次加载的首次 `session.start` 于 transcript 里说明它是怎么被理解的。

## Traps

- 想在 `$` 上加 noun：`engine.create` + `types/index.d.ts` 声明合并，**且不能替换别人的 noun**（会失败并卸载你的插件）。
- 调用别人的 noun：**读它的 `types/`，不要复制**；测试里要给它坐一个 provider，否则 `$` 的构建直接拒绝你的 hook。
- 事件结果只有三种形态：`{value}` / `{deny}` / core 的 `{ref, result}`。
- 别把宿主 `$.` 直接传得到处都是——包一层窄接口（`Host` 那种），顺带拿到可测性。
- 别信类型契约是全集——它可能落后客户端若干版本，以 mod 源码里的实际调用为准。

## Links

- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)
- [PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)
- [HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)

## References

- [`mods/README.md` mod 体系与 noun 契约](https://github.com/anthropics/claude-code/blob/main/mods/README.md)
- [`mods/telemetry/types/index.d.ts` `$.telemetry` 的 noun 契约](https://github.com/anthropics/claude-code/blob/main/mods/telemetry/types/index.d.ts)
- [`mods/sec-default/hooks/register.ts` 双跑实现](https://github.com/anthropics/claude-code/blob/main/mods/sec-default/hooks/register.ts)
- [`mods/diff/hooks/host/host.ts` 窄宿主接口](https://github.com/anthropics/claude-code/blob/main/mods/diff/hooks/host/host.ts)
- [mod 类型契约 `claude-code.d.ts`](https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts)