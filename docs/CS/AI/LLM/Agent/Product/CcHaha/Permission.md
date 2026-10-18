## Introduction

cc-haha 提供 **5 档可在 GUI 切换的权限模式**，覆盖从「每次都问」到「跳过权限」的连续光谱。危险命令、工具调用与 AI 追问统一在桌面端审批——把原本分散在终端的权限确认收口到图形界面。

权限判定逻辑（deny → ask → allow）与沙箱（OS 强制边界）的区分见 [Permission 理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)；底层的权限 machinery 与 [ClaudeCode/Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md) 同源。

## The Five Modes

用户可见的 5 档来自 `PermissionModeSelector.tsx:120-156` 的 `PERMISSION_ITEMS`（源码核实）；`PermissionMode` 类型本身还多一个 `dontAsk`（定义在 `permissionModeState.ts:27` 的 label/icon/dot 映射里），但**不在菜单中可选**。5 档语义与配色（`PermissionModeSelector.tsx:36-52` 的 `MODE_DOT_TONE`）：

| 模式 | 语义 | 配色 |
| :--- | :--- | :--- |
| `default` | **每次都问**（ask every time） | 绿（success） |
| `acceptEdits` | 自动接受文件编辑，命令仍问 | 琥珀（warning） |
| `auto` | 自动模式（带 opt-in 徽标，需用户确认开启） | 琥珀（warning） |
| `plan` | 计划模式（只读，先出方案） | 绿（success） |
| `bypassPermissions` | **跳过所有权限 / 自动放行**（最宽松，带 risky 徽标） | 红（danger） |

默认起始模式是 `default`（即「每次都问」档）。`lean` 模式下还会隐藏 `plan`（`PermissionModeSelector.tsx:234`）。模式解析优先级（`permissionModeState.ts:14-24`）：显式值 → 活动会话 → 已保存会话 → 侧聊 → 全局默认。

## GUI Approval Flow

审批弹窗（`PermissionDialog.tsx`）读取 `getPendingPermission`，pending 时渲染卡片，展示工具图标 / 标题 / 文件 / 命令预览（`DiffViewer`、`INSET_BLOCK`），动作区三选（`PermissionDialog.tsx:216-241`）：

- **Allow**：本次允许。
- **Allow for session**（带 `{rule:'always'}`）：本会话内永久允许该规则。
- **Deny**：拒绝。

退出计划模式走专用 `ExitPlanModePermissionDialog`（`PermissionDialog.tsx:246`），额外提供 **Approve / Approve+acceptEdits / Approve+bypassPermissions / Keep planning**，并可切换执行模型（`runtimeOverride`）。`bypassPermissions` 在主选择器内触发二次确认 `ActionDialog`（危险色，列三项风险），`auto` 触发 `AutoModeOptInDialog` 需用户 opt-in。

可视化 SubAgent 管理器可为**每个 SubAgent 单独设权限模式**，实现粗细粒度混合。

## Permission Decision Chain

GUI 对话框只是**最后一级**。工具真正执行前，判定按运行上下文分三条委派链（`src/hooks/toolPermission/handlers/`），任一 handler 给出非 null 决定即短路返回。

- **swarm worker → 转交 leader 裁决**（`swarmWorkerHandler.ts`）：当 `isAgentSwarmsEnabled() && isSwarmWorker()` 时，bash 命令先试 classifier 自动审批（`feature('BASH_CLASSIFIER')`），否则经 **mailbox 把请求转发给 leader**（`createPermissionRequest` / `sendPermissionRequestViaMailbox`），同时置 `pendingWorkerRequest` 显示等待指示。竞态防护两道：**先注册 callback 再发请求**（避免 leader 响应早于 callback 注册），并用 `createResolveOnce` 的 `claim()` 原子标记防重复 resolve；等待期 abort 会 resolve 为 cancel 而非挂死。转发抛错则回退本地处理。
- **coordinator worker → hooks + classifier**（`coordinatorHandler.ts`）：自动化检查**顺序执行**——先 hooks（快、本地），再 classifier（慢、推理、仅 bash）；任一得出决定即返回，都不决或抛错则**落回交互对话框**（fail-safe）。
- **interactive → 用户**（`interactiveHandler.ts`）：仅当前两者返回 null 时才进 GUI 对话框（即上方 Approval Flow）。

三者共同点是**失败即降级到人工**（swarm 转发失败→本地处理，coordinator 检查抛错→对话框），没有静默放行；且自动化检查只消费一次——注释明示「hooks 已跑、classifier 已消耗」，不重复执行。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)

## References

- [cc-haha 文档：What cc-haha is](https://cchaha.ai/en/start)
- [PermissionModeSelector.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/components/controls/PermissionModeSelector.tsx)
- [PermissionContext.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/toolPermission/PermissionContext.ts)
- [swarmWorkerHandler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/toolPermission/handlers/swarmWorkerHandler.ts)
- [coordinatorHandler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/toolPermission/handlers/coordinatorHandler.ts)
- [interactiveHandler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/toolPermission/handlers/interactiveHandler.ts)
- [permissionLogging.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/toolPermission/permissionLogging.ts)
