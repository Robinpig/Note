## Introduction

cc-haha 的 **REPL（交互式命令行）** 是产品的核心交互骨架，区别于 Electron 桌面 GUI 的可视化层。无论是终端直跑、SDK 调用（`-p`）、还是桌面内部的命令通道，所有用户输入与系统生成命令都经由**同一个统一命令队列**流动。本篇深挖该队列的内部机制，以及它如何在 turns 之间 drain、如何与计划任务 / 远控子系统咬合。

底层引擎进程的 NDJSON 通信（`sessionRunner.ts` 引擎子进程）在 [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md) 已涉及，本篇聚焦交互骨架而非进程协议。

## Unified Command Queue

队列实现位于 `src/utils/messageQueueManager.ts`，是**模块级单例，独立于 React state**（`messageQueueManager.ts:40-56`）：

- **统一入口**：所有命令——用户输入、`task-notification`、orphaned permissions——都进同一个 `commandQueue` 数组（`messageQueueManager.ts:43-53`）。
- **React 订阅**：通过 `useSyncExternalStore`（`subscribeToCommandQueue` / `getCommandQueueSnapshot`）订阅，每次 mutation 重建 frozen snapshot（`useCommandQueue.ts:13-15`）。
- **非 React 读取**：`print.ts` 的 streaming loop 直接读 `getCommandQueue()` / `getCommandQueueLength()`，无需走 React 渲染（`messageQueueManager.ts:46-47,90-99`）。

### Priority: now > next > later

`PRIORITY_ORDER` 定义三档（`messageQueueManager.ts:151-155`），同档 FIFO：

- `enqueue()` 默认 `next` —— 用户输入、orphaned permission（`messageQueueManager.ts:128-135`）。
- `enqueuePendingNotification()` 默认 `later` —— 系统通知（计划任务触发、proactive ticks、plan verification、channel messages），**注释明言「user input is never starved by system messages」**（`messageQueueManager.ts:137-149`）。这正是计划任务触发不打断当前 streaming 的根因。
- `dequeue(filter?)` 支持谓词过滤——between-turn drain（SDK / REPL）用 `cmd.agentId === undefined` 限制只取主线程命令，不重排既有 while-loop 模式（`messageQueueManager.ts:157-193`）。

### Visibility and Editability

系统生成的命令常含 raw XML（计划任务、plan 校验、channel 消息），必须不能泄露到用户输入框：

- `isQueuedCommandEditable()` —— 非 editable 模式（如 `task-notification`）且非 `isMeta` 才可编辑（`messageQueueManager.ts:359-361`）。
- `isQueuedCommandVisible()` —— channel 消息可见但不可编辑（`messageQueueManager.ts:368-375`）。
- `popAllEditable()` —— 把 editable 命令与当前输入合并供编辑，`task-notification` 类 non-editable 留队列稍后自动处理（`messageQueueManager.ts:428-484`）。
- `clearCommandQueue()` —— ESC 取消时丢弃排队的 notifications（`messageQueueManager.ts:322-328`）。

> 历史痕迹：文件末尾保留大量 `subscribeToPendingNotifications` / `getPendingNotificationsSnapshot` 等 `@deprecated` 别名（`messageQueueManager.ts:490-516`），说明这个「统一命令队列」是从早期的「pending notifications」机制演进合并而来。

## Drain Timing: Between Turns

队列不在用户输入瞬间立即执行，而是在**主线程 turn 间隙**被 drain：

- `dequeue(filter)` 的 `filter` 参数让 SDK / REPL 的 between-turn drain 只取主线程命令（`agentId === undefined`），跨进程 teammate 命令留在队列由各自 runner 取走（`messageQueueManager.ts:160-166`）。
- **计划任务触发**即在此间隙派发：teammate/lead 的 cron 触发经 `enqueuePendingNotification({ priority: 'later', isMeta: true, workload: WORKLOAD_CRON })`（见 [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)），`later` 优先级保证它排在用户输入之后、且不打断正在进行的 model stream。

## Integration with Subsystems

统一队列是多个子系统的「注入点」：

- **计划任务**：`useScheduledTasks.enqueueForLead(prompt)` → `enqueuePendingNotification(later, WORKLOAD_CRON)`，隐藏于队列预览 / transcript，billing 标 `cc_workload=` 低 QoS。
- **远控 / 协作**：`RemoteTrigger`（cloud CCR 触发器）、`SessionCollaboration`（loopback 桌面服务器桥）、`claude ssh`（SSH child process）都通过把命令送入同一队列来驱动本地执行（见 [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)）。
- **ESC 取消**：`clearCommandQueue()` 丢弃排队中的系统通知，避免取消后仍被执行。

## REPL Bridge and Launcher

- `replLauncher.tsx` 负责启动 REPL 入口。
- `useReplBridge.tsx`（~115KB）是 REPL 的桥接核心，连接底层 runtime（Ink / 终端 UI）与上层 UI 状态；引擎子进程的 NDJSON 通信经由它或 `sessionRunner.ts` 桥接（详见 [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md) 的引擎子进程引用）。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)
- [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [messageQueueManager.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/messageQueueManager.ts)
- [useCommandQueue.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useCommandQueue.ts)
- [useReplBridge.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useReplBridge.tsx)
- [replLauncher.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/src/replLauncher.tsx)
