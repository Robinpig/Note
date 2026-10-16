> 版本基线：核实于 2026-10-06，来源 `docs/subsystems/tools.md` / `filesystem.md` / `shell.md`。base bundle 一次挂入 14 个 `dsh-tool-*` 插件 + 3 个执行后端（fs / shell / mcp）。

## Introduction

DSH 面向模型的工具由独立插件提供。工具不是硬编码在 Agent Loop 里的函数集合，而是注册在 `ctx.tools` 上、通过 `ToolSchema` 暴露给模型的**可替换能力单元**。每个工具都经过 `tools/pre-execute`（审批/权限）→ `tools/execute`（实际执行）→ `tools/post-execute`（结果后处理）三层 waterfall。

## Tool List

### File System Tools

| 工具插件 | 能力 | 后端 | 使用场景 |
| --- | --- | --- | --- |
| `dsh-tool-fs` | read / write / edit（字面替换） | `dsh-fs` + `dsh-fs-local` | 读写源代码、配置文件；edit 是 str_replace 语义，给模型 `old_str` / `new_str`，比 write 更安全（原子替换 + 版本守卫） |
| `dsh-tool-fs-search` | glob / grep 文件检索 | 进程内搜索 | 批量找文件（glob）或文本模式（grep）；带 `timeoutMs`，由 `dsh-tool-call-timeout-policy` 强制 |
| `dsh-tool-str-replace-editor` | 行窗口精确编辑 | `dsh-fs` | minimal preset 的专用编辑器，只保留 read + str_replace 两种操作，比 dsh-tool-fs 更收敛 |

### Shell Execution Tools

| 工具插件 | 能力 | 后端 | 使用场景 |
| --- | --- | --- | --- |
| `dsh-tool-bash` | Bash 执行器消费方 | `dsh-shell` + `ctx.sandbox` | 执行 npm/maven/git 等命令，自动消费 sandbox 边界（参见 [Subprocess 子进程管理](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)） |
| `dsh-tool-pwsh` | PowerShell 执行器消费方 | `dsh-shell` | Windows 平台的 shell 执行，与 bash 共享同一 subprocess 后端 |

### Information Retrieval Tools

| 工具插件 | 能力 | 后端 | 使用场景 |
| --- | --- | --- | --- |
| `dsh-tool-web` | Web 检索 / fetch | `dsh-web` | 联网搜索最新信息、抓取网页内容；provider 严格指定，网络策略在模型之外执行 |
| `dsh-tool-lsp` | LSP 定义/引用/诊断 | LSP client | 已知符号的跳转（goto definition）、编译错误诊断；比 grep 更精确的代码语义检索 |

### Agent Orchestration Tools

| 工具插件 | 能力 | 使用场景 |
| --- | --- | --- |
| `dsh-tool-skill` | 加载并执行 YAML/Markdown 定义的 Skill | 调用预封装的多步骤流程（参见 [Skill 理论](/docs/CS/AI/LLM/Agent/Theory/Skill.md)） |
| `dsh-tool-todo` | 任务清单 | 长任务分解、进度跟踪；与 agent 状态分离，可被持久化恢复 |
| `dsh-tool-goal` | 持久 Goal | 驱动 Goal 外循环（参见 [Agent Loop Goal Outer Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md?id=goal-outer-loop)） |
| `dsh-tool-jobs` | 后台任务管理 | 把耗时命令脱离主 turn，后台跑 + 结果回调 |
| `dsh-tool-workflow` | 工作流编排 | 多步骤 DAG，节点间有数据传递和条件分支 |
| `dsh-tool-subagent` | 派生子 agent | Fork（继承历史上下文）/ Spawn（新建上下文）两种派生；参见 Agent Loop 章节 |
| `dsh-tool-subagent-control` | 子 agent 控制 | 暂停/恢复/终止子 agent；跨 agent 通信和状态查询 |
| `dsh-tool-ralph` | ralph 工作流工具 | Ralph 框架的专用工作流编排接口 |

### Infrastructure Tools

| 工具插件 | 能力 | 后端 | 使用场景 |
| --- | --- | --- | --- |
| `dsh-tool-call-timeout-policy` | `tools/execute` 包裹器，强制 `timeoutMs` | 永不发给模型 | 所有工具调用的协作式超时预算；fs 的 read/write/edit **不设超时**（见下文） |
| MCP 工具集 | MCP server 注册为模型可见工具 | `dsh-mcp-*` | 通过 MCP 协议外部接入（参见 [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)） |

工具后端由 `dsh-fs`（抽象的 `ctx.fs` + 原子文本操作）、`dsh-fs-local`（本地磁盘后端）、`dsh-shell`（抽象的 `ctx.shell` + Bash / PowerShell 提供方）支撑；MCP（`dsh-mcp-*`）与 LSP 经各自的 capability seam 接入，不混进工具内核。

## ToolDefinition Pipeline

一个已注册工具 = `ToolSchema`（面向模型的字段）+ 必需规范输出声明 `output` + `execute` 函数 + 宿主专用的调度元数据（`timeoutMs` / `isConcurrencySafe` / 展示回调）。注册表 `schemas()` 用显式允许列表构建面向模型的 `ToolSchema[]`，`output` / `execute` / 展示字段**绝不泄漏到模型请求**。

### canonical output contract

`output.schema` 用 JSON Schema 校验每个成功值，`render()` 把校验后的参数与值投影成 Native / model content——内容与展示分离，replay 安全。

```ts
// 简化伪代码，非 DSH 实际源码
const myTool = {
  name: 'my_tool',
  description: 'Does something useful',
  parameters: { ... },           // ToolSchema（发给模型）
  output: {
    schema: { type: 'object', properties: { result: { type: 'string' } } },
    render: (value) => ({ type: 'text', text: value.result })
  },
  execute: async (args) => { ... },  // 不发给模型
  timeoutMs: 30000,                   // 不发给模型
  isConcurrencySafe: (args) => true, // 不发给模型
}
```

### Parallel Tool Calls

`isConcurrencySafe(args)` 返回 `true` 才允许加入并行组；opt-in 的执行不得改动父拥有状态，共享状态必须容忍并发或 fail closed。并行执行、顺序提交（参见 [Agent Loop Tool Consolidation](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md?id=tool-consolidation-and-ordered-commit)）。

### Timeout: A Collaborative Budget

`timeoutMs` 是协作式预算，由 `dsh-tool-call-timeout-policy`（`tools/execute` 包裹器）强制，从不被送往模型。fs 的 read / write / edit **不设超时**——本地系统调用至多尽力中止，超时无法迫使进行中的 `fsync` / `rename` 停下，故 `timeoutMs` 在此处会成为 seam 无法强制的截止时间。

## File System Defaults to "Read Before Write"

`dsh-tool-fs` 加载时应同时加载 `dsh-fs-observation-policy`，使默认行为是「先读后写 / 先读后编辑」：策略插件用 `WeakMap<owner, Map<targetKey, FsObservation>>` 记录已观测状态（存在带版本 / 确认缺失），在 `fs/write-intent`、`fs/edit-intent` 单槽 waterfall 上按「未见 / 缺失 / 存在」决策。

带版本守卫的写入若后端版本与观测版本不符报 `FS_STALE_VERSION`（而非「匹配失败」），原子地把匹配、行尾处理、陈旧检查与原子替换放进一个变更临界区。错误用稳定 `FsErrorCode` 字符串携带（`FS_NOT_FOUND` / `FS_STALE_VERSION` / `FS_SANDBOX_DENIED` / `FS_PERMISSION_DENIED` / `FS_TOO_LARGE` …），重试 / 权限 / UI 层按 code 分支而不解析文本。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop（工具收口与并行提交）](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Permission（sandbox 对工具的约束）](/docs/CS/AI/LLM/Agent/Product/DSH/Permission.md)
- [DSH Subprocess（bash 执行器如何起进程）](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)
- [MCP 协议（外部工具接入）](/docs/CS/AI/LLM/Protocol/MCP.md)
- [Skill 理论（能力封装）](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- 官方子系统文档：[tools](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/tools.md) / [filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/filesystem.md) / [shell](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/shell.md)

## References

- [DSH：DeepSeek Harness 架构解析](https://mp.weixin.qq.com/s/Kf87hcNdSmY4ODWI4UZ8cg)
