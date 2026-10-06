## Introduction

> **版本基线：2026-10-05 核实。** 规范字段与校验数字来自 [Agent Skills 规范](https://agentskills.io/specification) 与官方校验器源码 [`agentskills/agentskills`](https://github.com/agentskills/agentskills) 的 `skills-ref`（v0.1.0，Apache-2.0）；Claude Code 侧字段来自 `code.claude.com/docs/en/skills`；Codex 侧来自 `openai/codex` 仓库源码。规范只有 6 个字段、Claude Code 本地接受 20 个——**这两个数字必须分清**，写错会直接导致 skill 被拒或静默失效。

Agent Skill（技能包）是**把一套可复用的做事方法打包成文件夹，让模型按需加载**的机制。它解决的问题很具体：同一段流程说明你在三个项目里各贴了一遍给 AI，每次都要重新解释一遍，还贴不全。Skill 让这段说明变成一个目录，模型在**决定用它的那个时刻**才把正文读进上下文。

它和另两个概念的区别是这一节最需要先讲清的：

- **Skill 是知识与方法**，形态是 Markdown 指令 + 附带资源
- **MCP 是能力与工具**，形态是 server 暴露的可调用接口
- **Subagent 是隔离的执行上下文**，形态是一个有自己 system prompt 与工具权限的独立 agent

判断用哪个的官方判据很干脆：**要「隔离执行、不污染主对话」用 subagent；要「在当前上下文复用一份方法」用 Skill**。而当流程需要连到外部系统（issue tracker、设计工具、文档服务器）时，官方建议 **skill 与 MCP 配对使用**——这个组合恰好说明了分工：skill 教「怎么做」，MCP 提供「拿什么做」。

> ⚠️ 常见误解澄清：**「Skill 是知识、MCP 是工具」是本库的概括，不是官方原话**。官方页面上的实际表述是：skill「gives the subagent **domain knowledge** without requiring it to discover and load skills」，而 MCP 是让 subagent 拿到主对话里没有的 server。功能上这个区分准确，但引用时不能当引文。

## 目录结构

规范约定的结构非常朴素：

```text
skill-name/
├── SKILL.md      # 必需：元数据 + 指令正文
├── scripts/      # 可选：可执行代码
├── references/   # 可选：按需加载的参考文档
├── assets/       # 可选：模板、图片、数据文件
└── ...           # 任意其他文件或目录
```

规范还额外要求了一条容易被忽略的约定：**文件引用必须用相对于 skill 根目录的相对路径**，且**保持一层深度**——原文是「Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.」这条限制的实际效果是：把 `references/api/full.md` 这种两层嵌套拆成 `references/api-full.md`，模型读它时才不用先解开一层路径谜题。

三个可选目录的官方用途：

| 目录 | 官方定义 | 实践要点 |
| :--- | :--- | :--- |
| `scripts/` | 存放 agent 可运行的代码 | 自包含或明确文档化依赖、错误信息有用、优雅处理边界。语言取决于 agent 实现，常见 Python / Bash / JS |
| `references/` | 存放需要时才读的额外文档 | **按需加载，所以单文件越小越好**——这是渐进式披露的落点 |
| `assets/` | 静态资源 | 模板、图片（图表、示例）、数据文件（查找表、schema） |

⚠️ `SKILL.md` 的文件名**必须全大写**。Linux 区分大小写，写成 `skill.md` 或 `Skill.md` 不会被识别——这是排障时的第一条。

## SKILL.md 的字段

### 规范字段 只有 6 个

| 字段 | 必填 | 约束 |
| :--- | :---: | :--- |
| `name` | **是** | 最长 64 字符；小写字母（含 Unicode 字母）+ 数字 + 单连字符；不以连字符开头或结尾；无连续连字符；**必须与父目录名一致** |
| `description` | **是** | 最长 1024 字符；非空；应同时说明「做什么」与「何时用」 |
| `license` | 否 | 许可证名，或指向随包许可证文件 |
| `compatibility` | 否 | 最长 500 字符；环境要求 |
| `metadata` | 否 | string → string 的 map |
| `allowed-tools` | 否 | **空格分隔**的预批准工具字符串。**标注为 Experimental**，各实现支持程度不同 |

校验器（`skills-ref/src/skills_ref/validator.py`）里的常量是实数不是约数：`MAX_SKILL_NAME_LENGTH = 64`、`MAX_DESCRIPTION_LENGTH = 1024`、`MAX_COMPATIBILITY_LENGTH = 500`。**出现白名单外的任何字段直接报错**——这一条和 Claude Code 的行为正好相反，见下面的坑。

> 📌 **一个规范内部的矛盾**：规范正文写 `name` 只允许「unicode lowercase alphanumeric characters (`a-z`, `0-9`)」，但校验器代码用的是 Python 的 `c.isalnum()`，**实际接受 Unicode 字母**（i18n 名字可用），且源码注释明确写了「Skill names support i18n characters (Unicode letters) plus hyphens」。文档与实现不一致，官方未澄清——写 i18n 名的 skill 目前能用，但别指望它一直能用。

### Claude Code 的 20 个本地字段

Claude Code 本地接受 20 个字段，远多于规范。官方原话是「**All fields are optional. Only `description` is recommended**」——这与规范里 `name`／`description` 必填**直接矛盾**。Claude Code 侧 `name` 可省略（回退到目录名），`description` 省略时回退到 Markdown 第一条非空行。

规范字段之外的 14 个：`when_to_use`、`argument-hint`、`arguments`、`disable-model-invocation`、`user-invocable`、`disallowed-tools`、`model`、`effort`、`context`、`agent`、`background`、`hooks`、`paths`、`shell`。

**命名规则里有一个例外必须记住**：官方原文是「Field names use lowercase words separated by hyphens, **except `when_to_use`**」——`when_to_use` 是**唯一**用下划线的字段。其余全部连字符。

⚠️ **分寸界线**：走 claude.ai 上传 / Skills API / `package_skill.py` 打包时，**只允许 6 个规范字段**，多写会 hard error：

```text
Unexpected key(s) in SKILL.md frontmatter: argument-hint. Allowed properties are:
allowed-tools, compatibility, description, license, metadata, name
```

所以自定义字段可以放心在本地用，但要打包分发就得删干净。

## 最大的坑 拼错不报错

**`allowed-tools` 用连字符，不是 `allowed_tools`。** 而写错之后**不会报错**。

官方原文：「Claude Code **ignores a field it doesn't recognize without reporting an error**.」

这是最危险的一类 bug：写成 `allowed_tools`，skill 照常加载、照常被触发，只是工具预批准悄悄失效——你不会看到任何提示，只会觉得「为什么这个 skill 没走审批流程」。

为什么会踩：官方校验器 `skills-ref` 的 Python 代码里，属性名是 `allowed_tools`（snake_case，因为是 Python 标识符），只在 `to_dict()` 序列化时才输出 `"allowed-tools"`。Python 内部用下划线、YAML 键必须用连字符，这个不对称就是混淆的来源。

同理走连字符的还有 `disable-model-invocation`、`disallowed-tools`、`argument-hint`、`user-invocable`。

**抓这个错的手段**：`claude plugin validate .claude/skills`（需 v2.1.233+），或 `skills-ref validate ./my-skill`。

## 渐进式披露 三级加载

这是 skill 能塞很多内容却不炸上下文的原因。规范给的三级与预算：

| 级别 | 内容 | 加载时机 | Token 预算 |
| :--- | :--- | :--- | :--- |
| 1. Metadata | `name` + `description` | **启动时对所有 skill 加载** | **约 100 tokens** |
| 2. Instructions | 完整 `SKILL.md` 正文 | **skill 被激活时** | **建议 < 5000 tokens** |
| 3. Resources | `scripts/`、`references/`、`assets/` 里的文件 | 仅在需要时 | 按需，无固定预算 |

规范给的操作建议很直接：**「Keep your main `SKILL.md` under 500 lines. Move detailed reference material to separate files.」**

三级预算数字（100 / 5000）全部来自规范本身，不是推测。

> ⚠️ **一个反直觉的例外**：一旦 skill 被加载，**它的正文会留在上下文里跨越后续所有轮次**——官方原文是「Once a skill loads, its content stays in context across later turns. Claude Code **does not re-read the skill file on later turns**」。所以 skill 正文不是「一次性步骤」，而是**整个任务期间持续生效的指令**。每写一行都是持续成本。

另外第一级的隐含代价值得单独说：**「Every skill in the skill listing adds to your context on every turn, whether or not Claude ever uses it.」** 装 50 个 skill 就意味着每轮都在为 50 条 description 付费，哪怕一个都没用上。

## 存放位置与作用域

Claude Code 的加载位置（这套最全，其他实现都是它的子集或变体）：

| 作用域 | 路径 | 说明 |
| :--- | :--- | :--- |
| Enterprise | 托管设置目录下的 `.claude/skills/<name>/SKILL.md` | 组织部署该设置的所有机器 |
| Personal | `~/.claude/skills/<name>/SKILL.md` | 本机所有项目，**但不含 Cowork / cloud session** |
| Project | `.claude/skills/<name>/SKILL.md` | 该仓库会话；提交后团队共享 |
| Nested | `<subdir>/.claude/skills/<name>/SKILL.md` | 从该目录或其下启动时加载 |
| Additional | `--add-dir` / `/add-dir` 目录中的 `.claude/skills/` | 该会话 |
| Plugin | `<plugin>/skills/<name>/SKILL.md` | 命令为 `/plugin-name:skill-name` |
| Plugin root | `<plugin>/SKILL.md` | 同上 |
| claude.ai 同步 | `~/.claude/skills/synced/` | 登录 claude.ai 账户的终端会话 |
| 旧格式 | `.claude/commands/<name>.md` | 仍兼容 |

两条容易踩的加载规则：

- **Monorepo**：向上搜索到 repository root。**但启动目录以下的 skill 启动时加载不了**，需要 Claude 首次读或改该子目录文件后才加载。
- **`permissions.additionalDirectories` 只授予文件访问权，不加载任何 skill**——官方明确「grants file access only and loads none of these」。这个字段很容易被误解成「加目录就能用那边的 skill」。

保留名：`synced`（claude.ai 同步目录）、`anthropic-skills`（plugin 外不加载）。

## 改了 Skill 要重载吗

这是每个使用者都会踩的问题，而**答案按产品分叉**，不能一概而论。

### Claude Code 有热加载，但有例外

官方原文：Claude Code 会监听 skill 目录的文件变化（**裸模式除外**），在 `~/.claude/skills/`、项目 `.claude/skills/`、`--add-dir` 目录的 `.claude/skills/` 下增删改 skill，**会话内自动生效，不需重启**。

例外清单：

| 情形 | 需要额外操作 |
| :--- | :--- |
| 修改**已存在**目录下的 SKILL.md | 会话内自动生效，**不需重启** |
| **新建顶层 skills 目录**（会话启动时不存在） | 需 `/reload-skills`，此后每次改动都要再跑 |
| skill 目录同时是 plugin，改 `hooks/`、`.mcp.json`、`agents/`、`output-styles/` | 需 `/reload-plugins` |
| `--add-dir` 目录中的 `.claude/commands/`、`agents/` | **不被监听，需重启** |
| frontmatter YAML 解析失败 | skill **仍加载但字段全空**——`/name` 能用，模型匹配不到 description |

最后一行是最阴的：YAML 写坏了不会报「加载失败」，而是变成一个没有 description 的 skill，**能手动调用但模型永远不会自动选它**。

### 其他产品

- **Codex**：官方说会自动检测 skill 变更，但「If an update doesn't appear, **restart Codex**」
- **Pi**：编辑后需 `/reload`
- **DSH**：`ctx.skills.get()` **不缓存完整定义**，每次调用重读正文，所以改正文无需清缓存

> ⚠️ 因此不要写「改了 description 必须重启」这种一刀切的说法。准确表述是：**Claude Code 对已存在的 skill 目录有文件监听、会话内自动生效；新建顶层目录需 `/reload-skills`，plugin 附属文件需 `/reload-plugins`；Codex 与 Pi 各自有重启或 reload 要求。**

## 同名冲突的优先级

Claude Code 官方给的完整规则表，其中第一条**非常反直觉**：

| 同名情况 | 谁赢 |
| :--- | :--- |
| enterprise / personal / project 之间 | **Enterprise > Personal > Project**（个人 skill 会覆盖项目 skill！） |
| 你的 skill vs bundled skill | 你的替换 bundled 命令，**但不影响其别名**（项目 `code-review` 替换 `/code-review`，别名 `/review` 仍跑 bundled） |
| 你的 skill vs 内置命令 | 本地终端会话中你的 skill 替换内置命令，**同样不影响别名** |
| skill vs `.claude/commands/` 文件 | **skill 赢** |
| 项目根 skill vs 嵌套 skill | **两者都加载**；`/deploy` 跑根 skill，`/apps/web:deploy` 跑嵌套 skill |
| plugin skill vs 上述任一 | **两者都加载**（plugin skill 有命名空间） |
| 上述任一 vs claude.ai 同步 skill 的短名 | 其他 skill/命令赢；同步 skill 只在**全名**下列出和运行 |

**「个人 skill 覆盖项目 skill」是绝大多数人第一次遇到都会以为是 bug 的行为**——直觉上项目配置应该更权威，实际相反，因为组织级才是最高的。而「替换不影响别名」意味着你以为覆盖了 `/code-review`，结果 `/review` 还在跑旧实现。

另外：**自定义命令已并入 skill**（官方原话「Custom commands have been merged into skills」）。`.claude/commands/deploy.md` 与 `.claude/skills/deploy/SKILL.md` 都会创建 `/deploy` 且行为一致，但旧 command 文件**不含 `name` 和 `paths`**。

## 各家实现差异

跨实现的最大兼容性地雷是 **`name` 是否必须与父目录一致**，各家宽严不一：

| 实现 | 技能路径 | 识别的字段 | name 必须等于目录名 | 调用方式 |
| :--- | :--- | :--- | :---: | :--- |
| **Claude Code** | `.claude/skills/`、`~/.claude/skills/`、`<plugin>/skills/` | 20 个本地字段 | 否（name 可省） | `/name`、模型自动、`Skill` 工具 |
| **OpenAI Codex** | `.agents/skills/`（逐级向上）、`$HOME/.agents/skills`、`/etc/codex/skills` | 仅 `name`、`description`、`metadata.short-description` | 否（`MAX_NAME_LEN=64`） | `$skill-name` 提及、`/skills` 列表 |
| **Pi** | 用户/项目 skills 目录、`~/.agents/skills/` | 规范 6 个 + `disable-model-invocation` | 否（但明说建议一致） | `/skill:name` |
| **DSH** | 6 级 rank：项目 `.dsh/skills` → `.agents/skills` → 自定义 → dsh home → agents home → bundled | 仅两个调用控制键 + 任意 `metadata` | 名字须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$` | `skill({name})` 工具 + TUI 斜杠 |
| **OpenCode** | `.opencode/skills/`、`~/.config/opencode/skills/`、`.claude/skills/`、`.agents/skills/` | 仅规范 6 个 | **是**（不匹配则 skill 不可用） | `skill({name})` 工具 |

几个值得单独记的点：

- **Codex 的识别面最窄**：源码 `SkillFrontmatter` 结构体只反序列化 `name`、`description`、`metadata.short-description` 三项，其余字段进不去。
- **DSH 的 6 级 rank 明确规定「最近层的条目直接赢得重名 skill」**，rank 顺序只在单层内裁决——和 Claude Code 的 Enterprise > Personal > Project 是相反的方向。
- **Codex 同名不合并**，两个都出现在选择器里；**Pi 保留先发现的**并给 warning，不报错。
- **OpenCode 未知字段静默忽略**（和 Claude Code 同一个毛病）。
- **递归发现**：Codex 逐级向上非递归、Claude Code 非递归、OpenCode 非递归、DSH 明确不支持 `**/SKILL.md` 递归；**只有 Pi 是递归发现**。

框架侧：**LangChain / LangGraph / Deep Agents 有 skill 概念且遵循同一规范**（Deep Agents 文档的原话是「智能体启动时，会读取每个 SKILL.md 文件的前置元数据」——同一套渐进式披露）。LangChain 还发布了 11 个 skill 组成的 `langchain-skills` 仓库，用 `npx skills add langchain-ai/langchain-skills --agent claude-code` 安装。**OpenAI Agents SDK 只查到 AGENTS.md，未查到内建 skill 机制。**

## 数量上限 与目录预算

**没有统一的「skill 数量上限」**，但多家有**目录预算**，这才是真正的卡点：

| 实现 | 预算 | 触顶后果 |
| :--- | :--- | :--- |
| Codex | ≤ 上下文窗口 **2%**（未知时 8,000 字符），显式设置时上限 10,000 tokens | **先缩短 description**；装得实在太多则**从初始列表里省略部分 skill 并给 warning** |
| Claude Code | `description`+`when_to_use` 合并 **1,536 字符**（仅展示截断，非验证失败）；压缩后重附 5,000/skill、合计 25,000 tokens | description 被截断影响匹配；压缩后老 skill 可能**被完全丢弃** |
| DSH | `catalogDescriptionMaxLength` 默认 **500**（最小 3） | 目录项被截断 |
| Pi / OpenCode | 未查到目录预算 | — |

Codex 那条特别值得注意：**skill 装太多时会「突然不触发」**——不是触发得慢，是被静默省略了并只给一行 warning。所以遇到「某个 skill 明明装了却不生效」，先怀疑描述预算超了。

## Skill 与 CLAUDE.md 的分工

官方给了明确的判据，值得原样记住：

> 「Create a skill when you keep pasting the same instructions, checklist, or multi-step procedure into chat, or when a section of CLAUDE.md has **grown into a procedure rather than a fact**.」

所以分工是：

- **事实与常驻规则** → `CLAUDE.md`（始终在上下文里）
- **程序与流程** → Skill（用时才加载，长参考材料在需要前几乎不花钱）

补一个成本侧的判据：skill 正文的精简标准应该和 `CLAUDE.md` 一样严格——因为一旦加载就跨轮持续占用，每行都是长期成本。

⚠️ **与 hooks 的优先级未查到官方规则**。skill 有 `hooks` 字段（调用时注册，持续到会话结束），但官方 skills / plugins / hooks / sub-agents 四页都没给出「skill 与 CLAUDE.md、hooks 谁覆盖谁」的优先级表。这两个不是同一维度（hooks 是执行机制、CLAUDE.md 是上下文内容），推测不如等官方澄清。

## 与 Subagent 怎么组合

官方对 Subagent 的定义是「runs in its own context window with a custom system prompt, specific tool access, and independent permissions」，判断何时该用它：

> 「Use one when a side task would flood your main conversation with search results, logs, or file contents you won't reference again: the subagent does that work in its own context and returns only the summary.」
> 「**Consider Skills instead** when you want reusable prompts or workflows that run in the main conversation context rather than isolated subagent context.」

两者可以组合，而且**两个方向都支持**：

- subagent 定义里写 `skills: [...]` → 启动时预注入
- Skill 里写 `context: fork` → 把 skill 内容注入指定 subagent

⚠️ 一个容易写错的点：`skills` 字段**只控制预加载，不控制可用性**。官方原文：「This field controls which skills are preloaded, not which skills the subagent can access: without it, the subagent can still discover and invoke project, user, and plugin skills through the Skill tool during execution.」

**要彻底禁止，把 `Skill` 从 `tools` 去掉或加进 `disallowedTools`。**

Pi 的分工表述值得引用，因为它是少见的把边界写清楚的实现：

> 「Use a skill when a workflow needs more context than a prompt template but **does not need a new executable integration point**.」

即：**Skill 教「怎么做」，Extension 提供「新的可执行集成点」**——需要新工具能力时才上 Extension。这也解释了为什么 Pi 把 Skill 设计成纯 Markdown 而把执行能力全放在 Extension。

## 官方 skill 清单

`anthropics/skills` 仓库当前有 19 个 skill，按用途分几类：

| 类别 | skill |
| :--- | :--- |
| 元技能 | `skill-creator`（创建/改进 skill，跑 eval 与 benchmark，性能分析与 description 优化）、`discernment-nudge` |
| API 与协议 | `claude-api`（模型 id、pricing、params、streaming、tool use、MCP、agents、caching、token counting，带 TRIGGER/SKIP 规则）、`mcp-builder` |
| 文档处理 | `pdf`、`docx`、`xlsx`、`pptx`（⚠️ **source-available，非开源**） |
| 前端与视觉 | `webapp-testing`（Playwright）、`frontend-design`、`canvas-design`、`algorithmic-art`（p5.js + seeded randomness）、`theme-factory`、`brand-guidelines`、`web-artifacts-builder` |
| 协作 | `doc-coauthoring`、`slack-gif-creator`、`internal-comms`、`academy-guide` |

⚠️ **`agent-browser` 不在这个仓库里**——它是 Vercel 的 `vercel-labs/agent-browser`，一个 npm 浏览器自动化工具 + 附带的 skill。把它说成「Anthropic 官方」是错的。

Claude Code 自带的 bundled skills（文档点名的）：`/doctor`（别名 `/checkup`）、`/code-review`（别名 `/review`）、`/batch`、`/debug`、`/loop`、`/claude-api`、`/verify`、`/simplify`、`/run`、`/run-skill-generator`、`/workflow-authoring`。

## 陷阱清单

汇总一遍最值得记住的：

1. **`allowed-tools` 是连字符**。写成 `allowed_tools` **静默失效、不报错**，工具预批准悄悄消失。
2. **`when_to_use` 是唯一用下划线的字段**，其余全连字符。
3. **`SKILL.md` 必须全大写**，Linux 区分大小写。
4. **`name` 是否必须等于父目录，各家不一致**：OpenCode 强制（不一致则不可用）、规范与校验器强制、Claude Code 与 Pi 不强制。做跨工具分发的 skill 请务必对齐目录名。
5. **YAML 解析失败的后果不是「加载失败」而是「加载了但没有 description」**——能手动调用，模型永不自动选。
6. **新建顶层 skill 目录需 `/reload-skills`**，不是自动生效。
7. **skill 正文跨轮持续占用上下文**，不要当一次性步骤写。
8. **每个 skill 的 description 都进每轮上下文**，装多了是持续成本。
9. **Codex 超过上下文窗口 2% 会静默省略部分 skill**，表现为「装了却不触发」。
10. **规范 6 字段 vs Claude Code 20 字段 vs 打包只允许 6 字段**——自定义字段本地可用、打包必删。
11. **个人 skill 会覆盖项目 skill**（Enterprise > Personal > Project）。
12. **替换 skill 不会覆盖其别名**（`/code-review` 被替换后 `/review` 仍跑 bundled）。
13. **规范与校验器对 `name` 是否接受 Unicode 字母不一致**（文档说仅 `a-z 0-9`，代码用 `isalnum()` 支持 i18n），官方未澄清。

## Links

- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)
- [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md)
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [Agent Skills 规范](https://agentskills.io/specification)
2. [agentskills/agentskills（skills-ref 校验器源码）](https://github.com/agentskills/agentskills)
3. [Claude Code: Skills](https://code.claude.com/docs/en/skills)
4. [Claude Code: Subagents](https://code.claude.com/docs/en/sub-agents)
5. [anthropics/skills 仓库](https://github.com/anthropics/skills)
6. [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser)
7. [Deep Agents: Skills](https://docs.langchain.com/oss/python/deepagents/skills)