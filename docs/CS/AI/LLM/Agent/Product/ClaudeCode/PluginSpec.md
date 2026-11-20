## Introduction

写 plugin 有官方规范，过去散落在仓库 `plugins/plugin-dev/` 的各个 skill 里——它本身是一个自带 7 个 skill + 3 个 agent + 1 个命令 + 4 个校验脚本的工具箱，每个 skill 都带 `references/`。**2.1.326 起该目录已从主仓移出**：官方插件改在 `claude-plugins-official` 仓库开发，本仓库只保留 marketplace 清单与安装入口。本文把这些成文规范集中整理：**manifest 全字段、slash command frontmatter 全字段、hook 两种 handler 的取舍、可移植路径写法、marketplace 分发注意事项**。

事实基线：客户端版本 **2.1.326**（2026-11-17 核实），依据官方仓库 [`CHANGELOG.md`](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) 的 2.1.326→2.1.302 区间、`plugins/README.md`、`mods/README.md`、`mods/types/claude-code.d.ts` 与官方 `mods/*/.claude-plugin/plugin.json` 逐项核对。manifest 结构用官方 mod 的真实 `plugin.json` 坐实；mod（进程内 TypeScript 插件）的接口契约不在本文，见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)；JSON hook 的事件语义见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)；组织管控见 [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)。

## The Plugin Skeleton

一个插件就是一个目录，加一个固定位置的 manifest：

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # 必需，位置固定
├── commands/                # 自动发现
├── agents/                  # 自动发现
├── skills/                  # 自动发现
├── hooks/
│   └── hooks.json           # 默认 ./hooks/hooks.json
├── .mcp.json                # 默认 MCP 配置位置
└── scripts/                 # 你自己的脚本
```

manifest **必须**在 `<plugin-root>/.claude-plugin/plugin.json`——放错位置插件不会被识别。最小可用的 manifest 只需要一个字段：

```json
{ "name": "hello-world" }
```

## plugin.json 全字段

### 核心字段

| 字段 | 类型 | 约束 / 默认 |
| :--- | :--- | :--- |
| `name` | string | **必需**，kebab-case，须匹配 `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`；全插件内唯一 |
| `version` | string | 语义化版本，默认 `"0.1.0"` |
| `description` | string | 建议 50–200 字符，marketplace 展示用 |
| `author` | object \| string | 对象形态 `{name, email?, url?}`；也接受 `"Name <email> (url)"` 字符串形态 |
| `engines` | object | `{"claude-code": "<semver 范围>"}`，**2.1.323 起**：超出声明范围的插件不安装、不更新、不加载；安装与更新自动挑范围内最合适的版本（最多回溯五个 `<name>--v<version>` tag）。范围外的 mod **整个不加载**（不是只关 hooks 模块） |

`name` 的正则值得单列——**它同时决定命令命名空间前缀**，所以改名字等于改所有命令的调用名。合法：`api-tester` / `code-review`；非法：`API Tester`（空格）、`code_review`（下划线）、`-git-workflow`（前导连字符）、`test-`（尾随连字符）。

2.1.326 新增了一层**状态可见性**：`author` / `homepage` 这类展示字段写畸形时不再让已启用的插件整个被拒——插件连同它的 hooks 与 MCP server 一起加载（管理员应检查自己部署的插件），但 `/plugin` 与 `claude plugin list` 会**提示该字段被忽略**。也就是说：坏掉的展示字段不再"悄悄吞掉"，也不再连带杀掉功能。

### 元数据字段

| 字段 | 说明 |
| :--- | :--- |
| `homepage` | 文档或主页 URL。**不用于**：源码（用 `repository`）、issue tracker、个人网站（用 `author.url`） |
| `repository` | string 或 object。对象形态含 `type` / `url` / `directory`（monorepo 里定位子目录） |
| `license` | SPDX 标识符，如 `MIT` / `Apache-2.0` / `GPL-3.0` / `UNLICENSED`；支持复合表达式 `"(MIT OR Apache-2.0)"` |
| `keywords` | 字符串数组，建议 5–10 个，分功能类 / 技术类 / 工作流类 / 领域类 |
| `types` | string，指向一份 `.d.ts`。插件向 `$` 新增 noun 时，须由它导出该 noun 的类型并在 `claude-code` 模块上声明；官方 `mods/telemetry` 即 `"./types/index.d.ts"` |
| `dependencies` | string[]，列出本插件依赖的 noun 由哪个 mod 提供；引擎把该 mod 的契约放到插件 `.claude-plugin/types/` 下 `claude-code/` 旁 |
| `userConfig` | object，用户可配置项定义，每项含 `type` / `title` / `description` / `required` / `default` / `options`。`claude plugin install --json` 结果的 `unsetOptionCount` 报告尚未设置的项数（**2.1.323** 加入） |

官方 `mods/*/.claude-plugin/plugin.json` 的两个真实例子坐实结构。最小形态（`mods/diff/.claude-plugin/plugin.json`）：

```json
{
  "name": "diff",
  "version": "0.1.0",
  "description": "The diff pane as a plugin: /diff opens the session's uncommitted changes beside the transcript, file by file with their hunks, refreshed as Claude edits and runs commands; the first edit opens it where the terminal is wide enough, and a file's ask button rides its hunks on the next prompt.",
  "author": {
    "name": "Anthropic"
  }
}
```

带类型契约的形态（`mods/telemetry/.claude-plugin/plugin.json`）：

```json
{
  "name": "telemetry",
  "version": "0.1.0",
  "description": "Plugin analytics: hooks $.telemetry's two events, so a plugin logs an event or marks a feature's use as a first-party row, sent in batches with the session's own credential.",
  "author": {
    "name": "Anthropic"
  },
  "types": "./types/index.d.ts"
}
```

`userConfig` 的真实形态见 `mods/agents-md/.claude-plugin/plugin.json`——它用 `instructionFiles` 一项给出 `type` / `title` / `description` / `required` / `default` / `options` 全套字段。

### 组件路径字段

四个字段的共同点是**都是「补充」默认目录，不是替换**：

| 字段 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `commands` | string \| string[] | `["./commands"]` | 额外命令目录，可多路径 |
| `agents` | string \| string[] | `["./agents"]` | 额外 agent 目录 |
| `hooks` | string \| object | `"./hooks/hooks.json"` | hook JSON 路径，**或直接内联配置对象** |
| `mcpServers` | string \| object | `"./.mcp.json"` | MCP 配置路径，或内联对象 |

**内联 vs 外部文件的判据**（官方给的实用线）：hooks 内联适合 < 50 行、复杂插件用外部 JSON；MCP 内联适合单个 < 20 行的 server，多 server 一律外部文件。

⚠️ **加载时的合并行为是「全部注册、不覆盖、冲突报错」**：先扫默认目录（`./commands/`、`./agents/`、`./skills/`、`./hooks/hooks.json`、`./.mcp.json`），再扫 manifest 里的自定义路径，两边的组件都会注册——**同名冲突直接报错，不是静默覆盖**。

## Path Resolution

四条硬规则，任何组件路径都必须遵守：

1. **必须相对**——不许绝对路径；
2. **必须以 `./` 开头**——`"commands"` 非法，`"./commands"` 合法；
3. **不许 `../`**——不能向上导航；
4. **只用正斜杠**——**即使在 Windows 上**，`".\\commands"` 非法。

合法：`"./commands"`、`"./src/commands"`、`"./configs/hooks.json"`；非法：`"/Users/name/plugin/commands"`、`"commands"`、`"../shared/commands"`。

## Slash Command Frontmatter

自定义命令已合并进 skill 格式（见 [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)），但**插件命令仍以 `.md` + frontmatter 形式定义**。frontmatter 全部字段可选，命令没有 frontmatter 也能工作。

```markdown
---
description: Review code for security issues
allowed-tools: Read, Write
model: sonnet
argument-hint: [pr-number] [optional-note]
---

Command prompt content here...
```

| 字段 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `description` | string | 命令正文首行 | `/help` 里展示；建议 < 60 字符、以动词开头、不写 "This command…" |
| `allowed-tools` | string \| string[] | **继承会话权限** | 三种写法：单工具 `Read`；逗号分隔 `Read, Write, Edit`；数组（含 `Bash(git:*)` 这类命令过滤器） |
| `model` | string | **继承会话** | `sonnet`（默认档）/ `haiku`（简单公式化、求快）/ `opus`（复杂分析、架构决策） |
| `argument-hint` | string | 无 | `[pr-number]` 必填风格、`[file-path]` 可选风格；用于 `/help` 与自动补全 |

`allowed-tools` 的官方取舍建议：**能多restrict 就 restrict**，Bash 一律用命令过滤器（`git:*` 而非 `*`），且只在与会话权限不同时才声明。`"*"` 官方明确标注不推荐。

`model` 的官方建议是**没有明确需求就别写**——`haiku` 用于简单任务与高频调用，`opus` 只留给真正复杂的任务。

## Plugin Command Discovery

命令按目录约定自动发现，**无需手工注册**，在 `/help` 里带 `(plugin:<name>)` 标签：

```
plugin-name/
├── commands/
│   ├── foo.md            → /foo        (plugin:plugin-name)
│   └── bar.md            → /bar        (plugin:plugin-name)
└── plugin.json
```

**子目录成为命名空间**（官方建议命令数 ≥ 5 时用）：

```
plugin-name/commands/
├── review/
│   ├── security.md       → /security   (plugin:plugin-name:review)
│   └── style.md          → /style      (plugin:plugin-name:review)
└── deploy/
    ├── staging.md        → /staging    (plugin:plugin-name:deploy)
    └── prod.md           → /prod       (plugin:plugin-name:deploy)
```

## Hook Authoring

官方 skill 把 hook handler 分成两类，并给出明确取舍：

| handler | 形态 | 官方定位 |
| :--- | :--- | :--- |
| `prompt` | `{"type":"prompt","prompt":"Evaluate …: $TOOL_INPUT","timeout":30}` | **推荐**。LLM 驱动的判定，适合需要上下文理解的判断；维护性好、边界情况处理自然 |
| `command` | `{"type":"command","command":"bash ${CLAUDE_PLUGIN_ROOT}/scripts/validate.sh","timeout":60}` | 确定性检查，适合可用脚本精确判定的规则 |

`prompt` handler 官方标注支持的只有四个事件：`Stop` / `SubagentStop` / `UserPromptSubmit` / `PreToolUse`——**其余事件只能用 `command`**。这是一个容易踩的边界。

### Hook 输出契约

所有 hook 共用：

```json
{ "continue": true, "suppressOutput": false, "systemMessage": "Message for Claude" }
```

`continue` 为 false 即中断处理；`systemMessage` 是给 **Claude** 看的消息（不是给用户看的 UI 文案）。

**退出码语义**：

| 码 | 含义 |
| :--- | :--- |
| `0` | 成功，stdout 进 transcript |
| `2` | **阻断性错误**，stderr 回喂给 Claude |
| 其他 | 非阻断性错误 |

`2` 是「让 Claude 知道并改」的唯一出口，而 `0` 只是「记一笔」——两者语义完全不同。

### Hook 输入契约

所有 hook 经 stdin 收到 JSON，公共字段：`session_id` / `transcript_path` / `cwd` / `permission_mode` / `hook_event_name`。事件特有字段：`PreToolUse`/`PostToolUse` 带 `tool_name`/`tool_input`/`tool_result`，`UserPromptSubmit` 带 `user_prompt`，`Stop`/`SubagentStop` 带 `reason`。在 prompt handler 里用 `$TOOL_INPUT` / `$TOOL_RESULT` / `$USER_PROMPT` 引用。

### 环境变量与可移植性

| 变量 | 用途 |
| :--- | :--- |
| `$CLAUDE_PLUGIN_ROOT` | **插件目录**——所有脚本路径都用它写，才可移植 |
| `$CLAUDE_PROJECT_DIR` | 项目根 |
| `$CLAUDE_ENV_FILE` | **仅 `SessionStart`**：往这里写可持久化环境变量 |
| `$CLAUDE_CODE_REMOTE` | 远程上下文中为真 |
| `MCP_SDK_GENERATION` | `v1` 现以**兼容模式**运行 v2 MCP 客户端（更早的握手、放宽的 OAuth 登录检查），因为 **v1 客户端已移除**；不要再把它当成"切回旧客户端"的开关 |
| `CLAUDE_CODE_PLUGIN_DIR_WATCH` | `0` 关闭 headless 会话对 `.claude/skills` 中 mods 文件变化的热重载 |

官方对可移植性的措辞是强制的：「hook 命令中**永远**用 `${CLAUDE_PLUGIN_ROOT}`」。这条与 manifest 路径不许绝对路径是同一件事的两面——**插件要能被 marketplace 分发，就不能依赖作者本机的路径**。

两个 2.1.326 的反直觉点，写 HTTP hook 时尤其容易踩：

- **managed settings 里 HTTP hook 的许可名单作用方式变了**：`allowedHttpHookUrls` 与 `httpHookAllowedEnvVars`（环境变量白名单）对 managed settings 下发的 hooks 如何适用被调整——升级后若组织统一托管的 HTTP hook 突然不被放行，先核对这两个键的口径，而不是怀疑插件本身。
- **HTTP hooks 忽略 `headers` 中的 `Content-Length` / `Transfer-Encoding`**：请求长度由 body 决定，手写这两个头不会生效。

### 生命周期限制

- **hook 在会话启动时加载**——会话中途改 hook 文件不生效（这是与 mod 热重载最大的行为差异，见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)）。
- hook 在**启动时集中校验**，配置有问题会当场报错而不是运行时才失败。
- 插件的 hook 与用户自己配置的 hook **合并并并行运行**。
- **mod 自身的工具调用不再弹权限提示**（2.1.321）：`$.tool.call` / `$.mcp.call` 即使用户设了 ask 规则、在 `dontAsk` 或 `-p` 运行下也不询问；**deny 规则与组织策略仍然适用**。这是 mod 与「以用户身份跑的 hook 脚本」在权限上的分界。
- **headless 会话会热重载 mods**（2.1.321）：`.claude/skills` 里的 mods 文件一变就重载，`CLAUDE_CODE_PLUGIN_DIR_WATCH=0` 可关；但插件的 hook 配置依旧是启动时加载，两者不要混为一谈。
- **完成 MCP server 登录的工具现在要求确认**（2.1.323）：即使在 bypass / auto 模式也要问；没人可问时（如 `dontAsk` 模式）改用 `/mcp`。

### 官方随附的调试工具

三件套，按用途分：

| 工具 | 干什么 |
| :--- | :--- |
| `claude plugin validate <dir>` | 按引擎的方式读 manifest 与 hooks 模块源码，**在任何会话加载之前**报出会挂什么 hook、调了什么、引擎会拒绝什么。2.1.323 起还**对插件的 TypeScript hooks 模块做类型检查**（每条发现是 warning，`--strict` 才判失败），并列出 mod 的 `engine.create` hook **增加 / 保留 / 替换的 `$` nouns**；报告里的 hooks / calls / nouns 是 `notes`，本身不使校验失败。加 `--json` 输出 `gatingHooks`，逐条列出注册在 gating 点的 hook 是否带 `.catch` |
| `claude plugin list` / `/plugin` | 列出插件；2.1.326 起当 `plugin.json` 的展示字段（如 `author` / `homepage`）畸形被忽略时在此给出提示，并把这类变化纳入状态可见性 |
| `claude plugin test <dir>` | 跑插件的 `*.test.ts` / `*.test.tsx`，环境与真实 hooks 运行环境一致（无 fs / 网络 / 进程），详见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) |
| `claude plugin eval` | 逐 case 评测插件行为。`--disallow-tools` 与 case 的 `disallowed_tools` 字段（2.1.299+）可**禁用指定内置工具** |

另有 `hook-development/scripts/` 下三个可直接用的 shell 脚本：`validate-hook-schema.sh`（schema 校验）、`hook-linter.sh`（风格检查）、`test-hook.sh`（跑测试）。`examples/` 三个样例：`validate-bash.sh` / `validate-write.sh` / `load-context.sh`。**这是官方给的「照着抄」入口**，比读规范更快上手。`claude plugin install --json` 额外返回 `unsetOptionCount`，用来确认用户还有几项 `userConfig` 没设。

## Designing For Distribution

`marketplace-considerations.md` 的核心是**为「你根本不认识的用户」设计**，具体化为四条：

| 原则 | 含义 |
| :--- | :--- |
| **普适兼容** | 不假设用户装了什么东西、不假设环境有某个命令 |
| **最小依赖** | 依赖越少越不会被环境打回来 |
| **优雅降级** | 缺东西时给清楚的提示，而不是报错崩掉 |
| **清晰引导** | 用户第一次装上要能立刻知道怎么用 |

配合的三条分发实践：

- **命名空间意识**——命令名避开常用词，防止与内置命令或其他插件撞名；这是 `plugin.json` 的 `name` 与命令目录结构共同决定的。
- **可配置性**——不要硬编码路径、账号、组织名；需要用户填的东西放进 `userConfig`。
- **版本兼容**——对 Claude Code 版本变化保持宽容：用 `engines["claude-code"]` 声明支持范围，让安装/更新自动选合适版本；超出范围的插件不会被装上或加载，宁可明确拒绝也不要装上即崩。MCP 侧不要再依赖 `MCP_SDK_GENERATION=v1` 切旧客户端——它只是 v2 客户端的兼容模式。

官方还给了一条**发布前清单**：完整 metadata、干净安装测试、校验 manifest、带 README、附 LICENSE 文件。

## Plugin Settings

插件可携带 settings（命令示例 `create-settings-command.md`、frontmatter 解析技巧 `parsing-techniques.md`、真实案例 `real-world-examples.md`）。两条关键安全实践（官方 skill 反复强调）：

- **校验一切输入**——hook 收到的 JSON 来自工具调用，不可信。
- **路径安全**——对输入里的路径做规范化与边界检查。
- **所有 shell 变量加引号**——官方在安全最佳实践里单列一条，因为 hook 脚本最常见的漏洞就是未加引号的变量展开。
- **设合理的 timeout**。
- **用户可配置项走 `userConfig`**——每项声明 `type` / `title` / `description` / `required` / `default` / `options`；安装后用 `claude plugin install --json` 的 `unsetOptionCount` 检查还有几项没设，而不是自己解析 settings 文件。

## Layout And Tools

`plugin-dev` 自身的结构曾是一份组织样板（2.1.326 起该目录已移出主仓，官方插件改在 `claude-plugins-official` 开发），主人若要写自己的插件仍可照抄这套分层：

| 子目录 | 内容 |
| :--- | :--- |
| `agents/` | `agent-creator` / `plugin-validator` / `skill-reviewer` 三个专职 agent |
| `commands/` | `create-plugin` 单一入口命令（14KB） |
| `skills/` | 7 个 skill：`plugin-structure` / `plugin-settings` / `command-development` / `hook-development` / `agent-development` / `skill-development` / `mcp-integration` |
| 每个 skill 内 | `SKILL.md` + `examples/` + `references/` + `scripts/` 四件套 |

每个 skill 都是「**SKILL.md 讲决策、references 存字段级契约、examples 给可抄的样本、scripts 做机械校验**」——这种分层本身比任何单个文件的内容更值得借鉴。`hooks/` 类 skill 还额外带三个校验脚本。

## Common Traps

- manifest 位置错了插件不会被发现——必须是 `.claude-plugin/plugin.json`。
- 路径忘加 `./`、用了绝对路径、用了 `../` 或反斜杠——四种都非法，**Windows 上也是**。
- 自定义 `commands` 目录是**补充**而非替换，写了 `./commands` 不会覆盖默认目录而是两个都扫。
- `allowed-tools: "*"` 官方不推荐；Bash 用 `*` 过滤等于没过滤。
- `model` 不写就继承会话；写错是最省事的踩坑方式。
- **hook 会话启动时才加载**，改配置要重启；这与 mod 的热重载不同。
- hook 命令里不用 `${CLAUDE_PLUGIN_ROOT}` 写绝对路径 → 分发出去即失效。
- `engines["claude-code"]` 范围写窄 → 超出范围的插件不安装/不更新/不加载；把 mod 放范围外是整个不加载，不只是关 hooks。
- `author` / `homepage` 写畸形不会让插件被拒，但会被忽略并在 `/plugin` / `claude plugin list` 提示——别以为字段还在生效。
- HTTP hook 手填 `Content-Length` / `Transfer-Encoding` 头无效（2.1.326 起长度只由 body 决定）。
- 把 `MCP_SDK_GENERATION=v1` 当"切回 v1 客户端"用——v1 客户端已移除，现在只是 v2 的兼容模式。
- 以为 mod 的 `$.tool.call` / `$.mcp.call` 仍会逐次弹确认——2.1.321 起不弹了，但 deny 规则照旧拦得住。

## Links

- [PluginPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginPatterns.md)
- [HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)
- [ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md)
- [Headless](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Headless.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)

## References

- [`plugins/plugin-dev/` 官方插件开发工具箱](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev)
- [manifest 全字段参考](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/references/manifest-reference.md)
- [command frontmatter 全字段参考](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/command-development/references/frontmatter-reference.md)
- [hook 开发 skill](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [plugins/README.md（官方插件迁出说明）](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)
- [claude-plugins-official 官方插件仓库](https://github.com/anthropics/claude-plugins-official)
