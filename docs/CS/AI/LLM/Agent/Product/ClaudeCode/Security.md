## Introduction

`sec-default` 是 Claude Code 官方内置的**组织安全基线**插件（id `cc-plugin-sec-default@builtin`）。它有34KB 的设计说明（`mods/sec-default/README.md`），是整个插件平台**安全模型的权威规格**——比任何文档都详细，本文是该规格的中文整理。

它的自我定位极精确：**「不增加任何自己的策略」**。组织今天能管住的东西（classic hooks、managed CLAUDE.md 与 rules、settings、MCP allowlist、机器上生效的 deny 规则）有些**从来不在个人掌控范围内**，这个插件的作用就是把它们挡在 user tier 之外，其余一律原样放行。

事实基线：据官方仓库 [`mods/sec-default/`](https://github.com/anthropics/claude-code/tree/main/mods/sec-default) 与类型契约（同[Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) 一篇，2026-10-18 核实）。

## Three Moves

它只有三个动作，别无他物：

| 动作 | 触发条件 | 含义 |
| :--- | :--- | :--- |
| `next.to(e, "append")` | 该事件的「主体」在受管层 | 越过 user tier 继续往下传 |
| `{ deny }` | `next.origin.tier` 是 `user` | 按名字拒绝该调用者 |
| `{ refuse }` | 某模块钉住的 `e.tier` 命中 | 按名字拒绝该模块 |
| `next(e)` | 其余 | 放行 |

两个判断依据的来源必须分清：

- **主体来源** = 事件的**钉住的** `e.provider`（引擎钉，不是模块自称）。
- **策略来源** = `$.settings.read({ source: "policy" })`，**一次读取服务一批工具调用**，且**两侧都fail closed**——读不到策略就等于策略生效。

## Why Tiers Matter

插件在tier 里排队：`prepend` → `user` → `append` → `builtin` → `core`（见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) 的 `TIERS`）。个人安装的插件一律在 `user` 层。

这个插件被放在 **prepend 层**——所以它比所有个人插件**先**看到事件，个人插件永远在它之后。它被 `prependPlugins` 之外的情况自动落座：机器上有 managed settings 或 managed-mcp.json 时、或 Team/Enterprise 组织；若 managed settings 定义了 `prependPlugins`，则那个列表**就是整个 prepend 层**，组织需在其中点名 `sec-default@builtin` 并自选位置。

一旦落座就**坐到会话结束**：后续 reload 时读到不同的计划不会把它撤掉。仅靠计划落座的席位**跟随下次启动时的登录方式**，真正钉住它的是机器上的 managed settings。唯一的例外在 Cowork cloud session：那里向组织索要 managed settings，默认落座，**`prependPlugins` 漏写它也不能撤掉它**——因为那个列表只可能是容器里的文件，而会话自己也能写那个文件，所以它只能加hold、不能解hold。

⚠️ 一个明确的自限：`next.to` **在受管层之外会被拒绝**。所以用 `--plugin-dir` 加载它，只会得到一个「什么也做不了、只能放行」的插件。

## Deny Rules Hold

这是整份规格里最重要的机制，也是 mod 平台最漂亮的设计。

### 问题

`tool.check` 上任何 hook 都能回答任何裁决。所以一个「用来消掉权限提示」的插件（`() => ({ decision: "allow" })`）**同时也能消掉**deny 规则、ask 规则、`PreToolUse` hook 的 ask——**包括受管的**。

### 解法：双跑

该插件在 `tool.check` 上是这样运作的：

1. **先照原样跑一遍链**。若没有任何「有权hold 住个人插件的环节」改写过递上来的裁决（改写 = 更宽松的裁决，或同样裁决但换了理由 / 规则 / hook 名；**收紧不算改写**），则原样放行。这由 `next.trace` 读出，其tiers 由引擎钉住：一个从未调用 `next` 的环节会被拿来与 deny 对比；由于引擎把共享同一 worker 的相邻插件作为**一批**列出并归到其首个成员的 tier，本插件之下的 `prepend` 项也一并计入。
2. **否则把 user 层整个摘掉再跑一次**（`next.to(e, "append")`）。这个裁决从未经过任何个人插件，所以裁决本身和它点名的规则都不可能被改写或抹掉，而且**不调用 `next` 的插件什么也改变不了**——规则就在这一跑里被求值。两次跑**只差一个 user 层**，所以当两者有差异且链的答案不是更严格的那个时，就是 user 层改写了它。
3. **裁决的处置**：
   - **deny 一律替换掉链的答案**，无论谁决定的。
   - **ask 会被原样返回**，条件是它点名了它背后是什么：`rule`（settings 规则）、`hook`（classic hook）、`setting`（某个设置自身的 check）、`ceiling`（组织对该工具的审批上限），或点名了**谁来答**（`decider`：某个 host，或某个 built-in / 组织 hook 交给人去答）。
   - **个人插件更严格的答案（以 deny 覆盖 ask）成立**。
4. **deny 之所以「不点名」**，是因为它可以站在这种 ask 前面：deny 被消掉的话，这次调用就会在没人被问的情况下执行。**而一个既不点名这些、也不在对话框里由人回答的 ask，不被 hold**。

### 各类「谁来答」的判定

| 主体 | 是否被 hold | 要点 |
| :--- | :--- | :--- |
| 答`ask` + `decider: "person"` 的 hook | **保持** | 该 ask 让调用躲开了 classifier 的放行。由 built-in 或组织 hook 产生的这种 ask 被 hold，个人插件既不能放行、也不能把它退回成普通 ask |
| settings read block（`blockReadsOutsideWorkingDirectories`） | **保持** | 引擎目前点名的设置就是它；两个 ask：工作目录外读文件的 shell 命令、以及开启期间模型想在沙箱外跑的命令 |
| host（SDK 的 `can_use_tool`、permission prompt tool、cloud session 的 host） | **保持** | 在进程每个循环（含 subagent）都声明 `decider: "host"`，且只在 host 真会被问的地方 |
| IDE pane / 桌面 Code tab 这两个卡片式 host | **不被 hold** | 它们就是那个人的对话框。**入口由启动环境断言、不可证明**——设置会话环境者可以冒充 pane |
| 模态本身在对话框的 ask | **不被 hold** | 在对话框处裁决不区分它与模态自身的ask |
| 引擎自身 check 的 ask（危险删除） | **不被 hold** | 没有设置能开启它 |
| 纯 `-p` 无 host 运行的会话 | **不被 hold** | 该处 ask 会被拒绝，模态自身的ask 是个人插件的 |
| 组织插件（prepend/append）或 built-in 的放行 | **参与两次跑** | 它的答案成立——**一个前置的、放宽的裁决正是引发第二次跑的原因**，所以这类调用上它的 hook 会跑两次 |

### 一个关键的划界

被 hold 的 ask **仍然是 ask**——因此凡是替人回答 ask 的东西仍然能回答它，个人安装的 classic `PermissionRequest` hook 也不例外（那由 `allowManagedHooksOnly` 管）。

**而它同样管不到个人安装的 classic `PreToolUse` hook 的放行**：引擎在那时根本不发起 ask，`tool.check` 不会跑，host 也不会被问。这与「没装任何插件」时一模一样。

`tool.check` **钉住问题本身**（`tool` / `input` / `tool_use_id`），所以没有 hook 能让规则对一条命令求值、对另一条重新求值；要改写属于 `tool.call`，而后者跑在这一切之前。

### 告知与计费

每个名字与种类每会话只告知一次（transcript 与debug log 都有）：形如 `<plugin> tried to lift a deny rule in your settings from a <tool> call (<rule>); the deny rule holds over the plugins you install (allowModsToOverrideDenyRules)`，裁决被保留但措辞或规则被改时用 `tried to reword`。种类共六种：`a deny rule`、`an ask rule`、`a <event> hook's ask`、`a <key> setting's ask`、`a host's ask`、`a refusal`（不点名规则的 deny）——**只有前两种带 "in your settings" 与规则名**。纯 `-p` 运行只在 debug log 里有这行，但调用照样被拒或被问。

这行日志**越过 user tier**（`ui.log` 那行）：用户 hook 若听到它，会跑在这个插件**自己的** `tool.check` hook 内部，而引擎会把 hook 从它自己内部引发的事件里排除。

### 成本

挂 `tool.check` 有代价：引擎只在**有插件挂了这个事件**时才发起它，所以在这个插件落座处，**每次工具调用都要跑一遍 `tool.check` 链**，而此前只有装了这类插件的会话才跑。`ui.log`、`env.get`、`env.set` 同理。

## What It Holds

按事件逐条（表格取自官方 README 的 "The rows"）：

| 事件 | 越过 user tier 的含义 |
| :--- | :--- |
| `classic.*` | 组织 settings hook 看到引擎的输入，它们的答案成立 |
| `prompt.section` / `context` / `attachment`、`skill.prompt`、`attribution.text` | managed CLAUDE.md、rules、policy skill 与引擎注入给模型的内容**不是个人插件能改写的**。个人插件仍保留 `prompt.submit` 及其增量上下文 |
| `session.append` | 引擎为模型注入的行、压缩产生的行、Skill 工具移交的 skill 正文、组织插件追加的行——按原样保留，**在 `prompt.attachment` 完整通过的东西不会在进入对话的路上被抹白或改写**。个人插件的 `tool.call` hook 仍可为 Skill 调用作答或换掉 `input.skill` |
| `session.compact` | 整段越过：个人插件顶替压缩作答的对话永远不会被装上 |
| `prompt.compose` | system prompt 的 section 列表由组织层、内置与引擎构成；个人插件不得删除、重排、改写 section，也不得用自己的列表顶替。**引擎只在有插件挂了这个事件时才发起它**，所以在这个插件的席位上每次渲染 system prompt 都跑一遍链 |
| `settings.read` | 没有用户 hook 能改写任何人读到的 settings，本插件自己的策略读取也包括在内 |
| `tool.describe` / `command.describe` / `agent.offer` / `agent.spawn` | 主体 tier 是 `prepend` / `append` 时越过；`user` / `builtin` / `core` 放行 |
| `tool.register` | 详见下节 |
| `tool.list` | 组织 managed MCP server、它自己落座的插件、以及那些插件 manifest 声明的 MCP server 的工具，按组织层原本的清单列出；其余按 user 层留下的原样。**server 文件读不到时，每个 `mcp__` 工具都算组织的** |
| `tool.check` | 见上节双跑机制 |
| `ui.log` | `prepend`/`append` 层插件（含本插件）记的行越过 user tier；无用户 hook 能改写或丢弃它，**也没有 hook 跑在记它的那条 hook 内部** |
| `env.get` / `env.set` | 受管层的读写越过 user tier；见下节 |
| `plugin.register` | `user` 层模块在 `allowManagedModsOnly` 开启时被拒；`prepend`/`append`/`builtin` 的模块从不被问 |
| **其余全部** | 放行：`prompt.submit`、`turn.*`、`tool.call`、`command.*`、`config.*`、`prompt.fill`/`suggest`/`edit`/`read`、`session.*`（除 `append`/`compact`）、`ui.*`（除 `log`）、`fs.*`、`http.fetch`、`process.run`、`store.*`、`clock.*`、`model.*`、`mcp.call`、`audio.*`、`agent.list`、`engine.create` |

注意 `fs.*` 与 `process.run` **在放行之列**——组织管控不覆盖插件的文件写入与子进程启动。

## The tool.register Check

这是最长的一条规则，因为它要区分「组织自己也装的插件」与「用户从远程市场装的同名插件」。

**`prepend` / `append` 层的调用者**直接越过 user tier。

**`user` 层调用者**在 managed settings 持有 `allowedMcpServers`（**设了就算，空列表也算**）时被按名字拒绝。没有 allowlist 时，仍被拒绝的包括：

- 工具名 `mcp__<plugin>__<tool>` 读起来像组织交付的某个 server 的：`managedMcpServers` 项，或企业 `managed-mcp.json` 里的 server。
- 名字读起来像组织自己落座的插件（`prependPlugins`、`appendPlugins`，或 managed `enabledPlugins` 打开的 id——可以是 `true` 或版本列表，按引擎读项的方式）。
- 或像这类插件自己 manifest 声明的 MCP server，引擎在插件 scope 下拼作 `mcp__plugin_<plugin>_<server>__`。

**豁免**：用户层插件**恰好**保留自己的名字，当且仅当引擎为它记的 id（`<name>@<marketplace>`，即 loader 解出的 settings 键，**绝不是 manifest 里的写法**）被 managed `enabledPlugins` 打开，比较方式与引擎一致（NFC，再小写）。这正是组织自己的插件被引擎留在 `user` 层时保住工具的方式：

> 只有**从 managed settings 点名的本地文件夹市场就地读取**的副本才被担保——所以从远程市场（git / GitHub / npm）来的插件**永远无法被担保**，被版本列表打开的也不行。

其他一律不匹配：`--plugin-dir` 加载的永远是 `<name>@inline`；另一个市场的同名插件；名字只是折叠成组织那个的；只在 `prependPlugins`/`appendPlugins` 里出现的 id。而一个人把**自己的市场**注册在组织的市场名下会得到相等的 id，也就得到这份豁免——`strictKnownMarketplaces` 今天就用「不允许任何其他市场来源」堵掉这条路。

另有一条时序约束：mod 在插件「入场」时就听到它的 id，因此一次「让本mod 重新落座而其他插件保持落座」的加载（如会话中途策略变更引起的再次折叠）之后，组织自己的插件在**会话重启前**拿不回它的名字。

## Pinned Variables

`$.env.set` 写的是会话自己的环境。被钉死（`user` 层调用者被拒、内置的写越过）的变量共三类：

**一、managed `env` 里设置的名字**（大小写无关），以及 policy 点名 launcher 时的 `CLAUDE_CODE_PROCESS_WRAPPER`。

**二、九个移动「策略与登录从哪里读」的变量**（每个 build 都钉）：

`CLAUDE_CODE_MANAGED_SETTINGS_PATH`、`CLAUDE_CODE_REMOTE_SETTINGS_PATH`、`CLAUDE_CODE_MOCK_REMOTE_SETTINGS`、`CLAUDE_CODE_DISABLE_ADMIN_ENV_UNION`、`CLAUDE_CONFIG_DIR`、`CLAUDE_SECURESTORAGE_CONFIG_DIR`、`USE_LOCAL_OAUTH`、`USE_STAGING_OAUTH`、`CLAUDE_LOCAL_OAUTH_API_BASE`——写它们会让后续加载或启动**指向另一份策略**。

**三、十个能把代码载入引擎所启动子进程的变量**：

| 类别 | 变量 | 各自能到达哪些子进程 |
| :--- | :--- | :--- |
| 加载器 | `LD_PRELOAD` `LD_LIBRARY_PATH` `LD_AUDIT` `DYLD_INSERT_LIBRARIES` `DYLD_LIBRARY_PATH` `DYLD_FRAMEWORK_PATH` | 各自只到部分子进程；macOS 对受保护二进制丢弃 `DYLD_` 系列 |
| shell 启动文件 | `BASH_ENV` `ENV` `ZDOTDIR` | `BASH_ENV` 到非交互 bash；`ENV` 到 sh 模式的交互 shell |
| 运行时选项 | `NODE_OPTIONS` | Node 子进程 |

⚠️ 原文明确：**「这个钉住是一份清单，不是一道边界」**——个人插件可以用别的路子以那个人身份起进程，`PATH`、home 类变量、凭据文件路径也在影响子进程。这个钉住防的是组织 hook 命令与工具被**意外**或**粗心**的插件改指向，**不是**敌意插件。

**例外是组织定义的 hook**：managed settings 里的、managed 设置安装的插件里的、以及 managed 的status line 与文件建议命令。它们启动自**组织插件任何写入发生之前**的环境，且包在 `CLAUDE_CODE_SHELL_PREFIX` 里；managed HTTP hook 的 header 变量同样读「写入前」的值。

另有一条规则常被忽略：**在一次加载中，从第一次入场直到 set 开始服务，插件做的操作（以及它跨步骤留在运行中的操作）都会经已入场的插件抛出，本插件排第一**——所以被钉变量在个人插件的 `plugin.register` hook 处就被拒，与更晚的时间点一致。

## Two Administrator Options

两项都在 managed settings 的 `pluginConfigs` 下，键名必须是 CLI 构造出的那个 id（`cc-plugin-sec-default@builtin`），**只有这一种拼写被读**。

| 选项 | 默认 | 作用 |
| :--- | :--- | :--- |
| `allowManagedModsOnly` | **开**（除absent 或 `false`） | 只加载组织经managed settings 部署的 mods 与内置 mods。个人安装的 hooks 模块在加载或重载时被拒，报一行 `mods are limited to your organization's by policy (allowManagedModsOnly); <plugin> was not loaded` |
| `allowModsToOverrideDenyRules` | **关**（只认字面量 `true`） | 允许个人插件在 `tool.check` 上覆盖 settings deny 规则，以及所有其他与之一同hold 的东西 |

`allowManagedModsOnly` 的细则值得单列：

- **判断只读 CLI 钉在模块上的 tier**，不看模块自称什么——个人手里一份带组织 mod 名字的副本仍在 `user` 层，仍被拒。
- **拒绝意味着模块没有任何东西被接入**：没有 hook、没有 tool、没有 command。到那一步它的顶层代码已经在每个 hooks 模块都在的封闭上下文里跑过一次，期间 `$` 上没有调用被服务。
- **只读 managed settings**：同名的项出现在个人 / 项目 / `--settings` 文件里**既不能开也不能关**它。
- **fail closed**：managed settings 的读取被拒（下面的 hook 拒绝了它）或本插件的 hook 失败时，其 `.catch` **拒绝该模块**并记下失败——读不到的策略把所有个人 mod 挡在加载之外。未落座处没有这条规则。
- 需要 managed settings 定义了 `prependPlugins` 且其中点名本插件，选项才生效。
- `claude plugin test` **不在覆盖范围**：它在自己的引擎里跑测试，不往会话加载任何东西。
- **settings hook、status line 与 `/goal` 不受它影响。**

对 `allowModsToOverrideDenyRules`，还有一条容易被忽略的限制：**它只从 managed 源读**——所以一个人自己可写的策略文档（Windows 的 `HKCU` hive）、或服务器尚未确认的远程策略，**都不提供这个选项**；那种策略仍hold 它所 hold 的，只是什么也不授予。

## Anthropic's Own Hardening

官方仓库根部的 [`CLAUDE.md`](https://github.com/anthropics/claude-code/blob/main/CLAUDE.md) 是**写给 Claude Code 及其他编码 agent 看的仓库自述**，其中记录了 Anthropic 自己在自家 CI 里跑 Claude Code 的**三重防护**——这是「组织管控」在真实工程里的落地样本，也印证本文描述的机制确实被官方自己用着：

1. **出口防火墙 runner**——调用 Claude 的 job 一律跑在 `ubuntu-24.04-firewall`（过滤出站流量）。「不要把调用 Claude 的 job 移到别的 runner上」是明写的禁令。
2. **网络 allow list**——`.github/egress-firewall.yaml` 列出这些 job 可达的 host，且**必须保持 `mode: enforce`**（这才是让防火墙真正拦截其余流量的关键）。
3. **auto 权限模式**——每个跑 Claude Code action 的 step 都在 `claude_args` 里传 `--permission-mode auto`；allowed tools 覆盖不到的需权限调用**只有 Claude Code 的安全审查通过才执行**。另外要求用 `claude-opus-4-6` 或更新模型——**更老的模型上 Claude Code 会回退到其默认权限模式**。

配套的 CI 校验：`workflow-hardening.yml` 在有 job 破坏防护 1 或 3、或 allow list 缺失/为空/非 enforce/含 `*` host 时**直接失败**；确实无法满足的 job 要在 `.github/scripts/check_workflow_hardening.py` 的豁免表里登记理由，且 `EXEMPT_FROM_AUTO_MODE` 里的 job 必须**完全不设权限模式**。原文有一句很硬的话：**「不要跳过或削弱这个检查」**。

两处细节值得注意：仓库里答 `@claude` 提问的 `claude.yml` 自己设了 `--permission-mode acceptEdits`，而 workflow 里后出现的 `--permission-mode auto` **会覆盖它**（顺序即优先级）；以及仓库也明写「各workflow 的 `permissions:` 块保持最小，不要在日志里打印 token 或环境变量」。

## Reading This Spec

这份文档的信息密度极高，且几乎全部只存在于这里。对写 mod 的人，最实用的三条：

1. **挂 `tool.check` 有全局成本**——会让每次工具调用都跑链（见「成本」）。
2. **你的调用对别人可见**——`fs.write`、`env.set` 这些引擎方法本身是事件，别人可以挂 hook 看到（见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)）。
3. **别指望「内部调用」是私密的**——组织策略明确把「引擎从 hook 内部引发的事件里排除 hook」当作**例外**来写，说明默认情况并不排除。

## Links

- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Observability](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Observability.md)

## References

- [`mods/sec-default/README.md` 官方设计说明](https://github.com/anthropics/claude-code/blob/main/mods/sec-default/README.md)
- [`mods/sec-default/` 实现目录](https://github.com/anthropics/claude-code/tree/main/mods/sec-default)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)