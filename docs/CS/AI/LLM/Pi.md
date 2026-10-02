## Pi

## Introduction

Pi 是一个跑在终端里的 AI 编程 agent。它的特点是把能力藏在**基础操作**里，而不是堆在界面上——真正用好 Pi，靠的是会话树、`@` 引用、Shell 集成这些日常动作，而不是记一堆冷门命令。

会话即数据：每次对话自动保存为一棵树，存在 `~/.pi/agent/sessions/`，每个会话是一个纯文本文件；会话记录与模型选择相互独立，同一会话里随时换模型，之前的内容不会丢。

## 会话管理：Pi 的"时光机"

每次对话会形成一棵**会话树**，可以随时回到任一节点，从那里重新分支开始。

按 `Ctrl+Shift+P` 或输入 `/sessions` 查看会话树：

```
main (当前会话)
├── 我说"帮我写个 API"
│   ├── Pi 生成的代码 (节点 1)
│   │   └── 我继续追问"加个错误处理" (节点 2)
│   └── 我改了主意"用 Express 写" (节点 3)
└── 我说"检查一下项目结构"
    └── Pi 的分析结果 (节点 4)
```

选中某个节点，Pi 回到那个时刻的状态，后续操作从那里重新分支。典型场景：让 Pi 改了模块、聊过几轮才发现改错了——直接回到"改之前"的节点重来，不用手工撤销。

其他会话操作：

- **自动命名**：Pi 根据第一次对话内容给会话起名；也可手动改：`/title 我的 API 重构会话`
- 支持查看对话记录、查看对话文件、导出对话文件

## @ 引用文件

在输入框输入 `@`，弹出模糊搜索框，检索项目里的文件：

```text
@README.md 解释一下这个项目做什么的
```

一条消息可以引用多个文件：

```text
@src/app.ts @src/app.test.ts 帮我 review 这两个文件
```

启动时也能直接引用：

```shell
pi @README.md "帮我总结"
```

**粘贴图片**：在支持的终端（iTerm2、Kitty）用 `Ctrl+V` 粘贴图片（Windows 用 `Alt+V`），图片自动进入 Pi 的上下文；也可以把图片拖进终端。

## Shell 命令集成

三种前缀对应三种语义：

| 写法 | 行为 |
| --- | --- |
| `!npm run lint` | 执行命令，**并把输出发给模型**，模型基于输出继续操作 |
| `!!npm run lint` | **静默执行**——命令执行但不把输出发给模型，适合"确认没问题"的操作 |

**持久化 Shell**：Pi 的 bash 工具是持久化的——导出的环境变量、切换的目录、定义的 shell 函数都会在后续命令中保留：

```shell
!cd backend
!npm install
!npm run test
```

三条命令在同一个 shell 里执行，第一条 `cd backend` 之后，后面的命令自动在 `backend` 目录下运行。

## 快捷键

| 快捷键 | 作用 |
| --- | --- |
| `Ctrl+L` | 打开模型选择器 |
| `Ctrl+S` | 保存当前模型为默认 |
| `Ctrl+P` / `Shift+Ctrl+P` | 正/反向循环切换模型 |
| `Shift+Tab` | 循环切换思考级别 |
| `Ctrl+V` | 粘贴图片（Windows 用 `Alt+V`） |
| `Ctrl+K` | 打开搜索文档 |
| `Ctrl+D` | 关闭会话 |

## 模型切换与思考级别

- `Ctrl+L` 打开模型选择器，输入名称搜索（如 `claude`、`gpt`），Enter 切换；再按 `Ctrl+S` 把当前模型设为**启动默认**
- `Shift+Tab` 循环切换**思考级别**：从"不思考直接回答"（快速任务）到"深度推理"（复杂任务）

## 上下文工程

Pi 启动时自动加载项目里的上下文文件，按层级叠加：

| 文件 | 作用 |
| --- | --- |
| `~/.pi/agent/AGENTS.md` | 全局指令（所有项目生效） |
| 项目目录下的 `AGENTS.md` 或 `CLAUDE.md` | 项目级指令 |
| 父目录的 `AGENTS.md` 或 `CLAUDE.md` | 递归向上查找 |
| `AGENTS.override.md` | 覆盖当前目录的 AGENTS.md |

改完上下文文件后输入 `/reload` **立即生效**，不用重启 Pi。

## 非交互模式

Pi 也能当一次性工具用，执行完输出结果后自动退出，适合脚本化调用：

```shell
pi "Add a Dockerfile for this project"

# 指定模型
pi --model claude-sonnet-4 "帮我写一个 .gitignore"
```

## 常见问题

| 问题 | 回答 |
| --- | --- |
| 会话太多会不会卡？ | 不会。会话是 `~/.pi/agent/sessions/` 下的纯文本文件；卡顿主要来自模型响应速度，与会话数量无关 |
| 换模型后会话还在吗？ | 在。会话记录与模型相互独立，同一会话内随时切换模型不丢内容 |
| 能用 Pi 联网搜索吗？ | Pi 不内置联网搜索，但可以通过 bash 执行 `curl` 获取网页内容，再在会话里继续 |

## Extension

Pi 核心只有 4 个工具，能力主要来自扩展，共四种由浅入深的方式：

| 方式 | 形态 | 适用 |
| --- | --- | --- |
| **Skills** | 一份 markdown「程序性记忆」，教 Pi 某类任务怎么做 | 重复任务、固定流程、专属规则 |
| **Prompt Templates** | 预设提示词模板 | 常用提示词（如 code review） |
| **Pi Packages** | 插件式扩展包，可打包多个 Skill/Template/配置/Extension | 复用与社区分享，`pi install` 安装 |
| **Extensions** | TypeScript 写的深度扩展 | 注册新工具/命令、拦截工具调用、自定义 UI、跨回合状态 |

### Skills

Skill 是放在 `~/.pi/agent/skills/` 下的 markdown，Pi 启动时扫描，对话涉及相关任务时自动加载，也可 `/load-skill <name>` 手动加载。

```markdown
# Deploy Skill

## Steps
1. Run `npm run build`
2. Run `npm run test`
3. If tests pass, run `npm run deploy:staging`
4. Wait 30s, then `curl https://staging.example.com/health`
5. Health check passes 后 `npm run deploy:prod`

## Rollback
出问题时执行 `npm run rollback:prod`
```

Skill 是「知识」不是「代码」——它教 Pi 怎么做，但不赋予新能力；需要真正的新工具时才上 Extension。与通用的 Agent [Skill](/docs/CS/AI/LLM/Skill.md) 概念一致。Prompt Template 类似，放在 `~/.pi/agent/templates/`，用 `/template <name>` 引用。

### Packages

Package 通过 `pi install` 安装，支持 npm 与 Git 两种来源，装完 `/reload` 热加载：

```shell
pi install npm:pi-agent-extensions        # npm 包
pi install git:github.com/tomsej/pi-ext   # Git 仓库
pi install -l npm:statusline-pi           # -l 项目局部，写进 .pi/settings.json
pi -e npm:@jmcombs/pi-tavily-search       # 单次试用，不持久化
pi list / pi update --extensions / pi remove npm:<pkg>
```

> 注意：必须用 `pi install` 而不是 `npm install`，否则 Pi 不会注册该包；第三方包能执行代码并影响 agent 行为，安装前最好过一遍源码。

社区包按用途大致分层：

- **状态栏**：`statusline-pi`、powerline-footer，显示目录/Git 分支/剩余上下文 token/tok·s/模型。
- **代码审查**：`review`（支持审 PR、未提交改动、指定 commit，遵循项目 `REVIEW_GUIDELINES.md`）。
- **会话管理**：`sessions`、`session-breakdown`（token/消息/模型分布看板）、`cwd-history`。
- **文件浏览/复用**：`files`、`/readfiles`、`/code`（从消息里选代码块复制/插入/运行）。
- **任务拆解**：`todos`、`loop`、`ask_user/answer`、`pi-delegator`（把子任务委派给独立 Pi 子进程）。
- **上下文压缩**：`headroom`（本地代理压缩，断连自动直通）、`pi-vcc`（纯算法压缩，不调 LLM）。
- **工作流**：`workflow`（模型路由）、`handoff`（迁移上下文到新会话）、`wf`（契约驱动管线：讨论→contract→worktree 执行→gate→review→PR，阶段转移由 `wf-gate.mjs` 退出码决定而非 agent 自判）。
- **模型接入 provider**：`claude-code-pi`（走本地 `claude -p`）、`grok-pi`、`opencode-pi`（免费模型）、`apple-fm-pi`、`9router-pi` 等，把本地 CLI 暴露的模型注册给 Pi。
- **独立能力包**：Tavily/Grok 联网搜索、Context7 版本化文档、`pi-notify` 完成通知、`pi-1password`（凭证注入且不经 LLM）、`pi-steward`（本地模型面板）、`pi-relay`（子 agent 跑在外部 headless agent 上）。

### Extensions（TypeScript）

Extension 是最高级的扩展方式，可给 Pi 增加工具、命令、事件处理与 TUI 组件。放在 `~/.pi/agent/extensions/*.ts`（全局）或 `.pi/extensions/*.ts`（项目级），`/reload` 生效。

```ts
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  // 拦截危险命令：rm -rf 需用户确认
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName === "bash" && event.input.command?.includes("rm -rf")) {
      const ok = await ctx.ui.confirm("Dangerous!", "Allow rm -rf?");
      if (!ok) return { block: true, reason: "Blocked by user" };
    }
  });

  // 注册一个自定义工具
  pi.registerTool({
    name: "greet",
    description: "向用户打招呼",
    parameters: Type.Object({ name: Type.String() }),
    execute: async ({ name }) => `你好，${name}！`,
  });
}
```

**何时该写 Extension 而非 Skill**：需要真正的新工具/新命令、需要拦截或改写工具调用（权限门、路径保护）、自定义 UI/事件响应、保存跨回合状态。新手路线是先用 Skill 和现成 Package，确有新能力再写 Extension——实践中很多人直接让 Pi 替自己写扩展。

## Containerization

Pi **不内置权限系统**：运行在哪个目录就能访问该目录全部文件，agent 收到删文件指令就会执行，不弹确认框。需要更硬的安全边界时：

| 方式 | 说明 |
| --- | --- |
| **Gondolin** | Earendil Works 自家项目，把工具命令路由到轻量 Linux 虚拟机执行 |
| **Docker** | 整个 Pi 进程跑在容器里，适合简单隔离 |
| **OpenShell** | 策略控制的沙箱，适合企业级安全需求 |

最低限度的自保也包括：只在项目目录内运行、自己写 Extension 给危险操作加确认（如上例）。

## Trade-offs

结合社区实测，Pi 的取舍很鲜明：

- **上手快但需自己配置**：安装一条命令，但不像 [Claude](/docs/CS/AI/LLM/Claude.md)/[Codex](/docs/CS/AI/LLM/Codex.md) 那样开箱自动生成 Plan、spawn 子 agent、弹权限框，这些都要自己装包或写扩展。
- **透明度高**：每次读了哪个文件、跑了什么命令、改了哪几行都可见，没有子 agent 黑盒，契合 plan-act-verify 工作法。
- **会话是树**：从任意消息分叉试不同方案，搞乱一个分支不影响主干，实验成本低。
- **轻量提示词、上下文干净**：系统提示和工具定义精简，部分评测中同任务比重型 harness 更省 token，但这依赖模型与任务，并非任何 workload 都更省。
- **长会话强**：单会话可承载数百轮，compaction 策略还能用 Extension 替换。
- **短板**：不是 Telegram/微信/Discord bot，无跨会话持久记忆，深度定制要写 TypeScript，第三方生态规模不及 [MCP](/docs/CS/AI/LLM/MCP.md) 成熟阵营，四个核心工具是刻意的极简设计而非缺失。

适合想自己掌控 harness 形态、需要在同一会话切换多家模型、重视上下文干净与 token 效率、愿意锻造工作流的用户；不适合追求一站式开箱、依赖消息平台网关、或要求内置审批流的企业场景。

## Links

- [DSH](/docs/CS/AI/LLM/DSH.md) — DSH 的 OR 聚合与 Pi 的 AND 聚合是 Agent Loop 结束判断的两种解法
- [Codex](/docs/CS/AI/LLM/Codex.md) / [Claude](/docs/CS/AI/LLM/Claude.md) / [OpenCode](/docs/CS/AI/LLM/OpenCode.md) / [OpenClaw](/docs/CS/AI/LLM/OpenClaw.md)
- [Agent](/docs/CS/AI/LLM/Agent.md) / [Harness](/docs/CS/AI/LLM/Harness.md) / [Skill](/docs/CS/AI/LLM/Skill.md)
- [MCP](/docs/CS/AI/LLM/MCP.md) — 对照：MCP 的成熟扩展生态 vs Pi 的 Package/Extension 体系

## References

- [PI 系列（三）：扩展能力与选型指南](https://mp.weixin.qq.com/s/Rv0a2_7dzSSWJeTOXKQiLA)
- [PI 系列（二）：日常使用技巧](https://mp.weixin.qq.com/s/1MSVysazeK_uyaY46XG7Cw)
- [Pi 使用指南](https://pi.dev/docs/latest/using-pi)
- [Pi 会话管理](https://pi.dev/docs/latest/sessions)
- [Pi 快捷键](https://pi.dev/docs/latest/keybindings)
- [Pi 上下文压缩](https://pi.dev/docs/latest/compaction)
- [Pi Extensions 文档](https://pi.dev/docs/latest/extensions)
- [Pi Skills 文档](https://pi.dev/docs/latest/skills)
- [Pi Packages 文档](https://pi.dev/docs/latest/pi-packages)
- [Pi 容器化](https://pi.dev/docs/latest/containerization)
- [Pi Packages 画廊](https://pi.dev/packages)
- [Pi 中文文档](https://pi-doc.com)
- [接入火山引擎 Coding Plan 国内版模型支持](https://github.com/buwalle/pi-provider-volcengine-codingplan)
