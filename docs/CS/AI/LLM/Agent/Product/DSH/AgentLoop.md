> 版本基线：核实于 2026-10-06。Agent Loop 的结束判断与 Session 持久化设计是 DSH 最有辨识度的两块——前者把结束拆成五层边界，后者把一切操作变成可重建的追加日志。

## Introduction

DSH 的 Agent Loop 本身也是插件——这在整个 Agent 产品里几乎是独一无二的。它不只是一个 `while` 循环，而是一套精心设计的状态机 + 事件日志系统，解决了"为什么 Agent 知道自己该停"和"崩溃后怎么恢复"两个核心问题。

本文覆盖：默认 AgentLoop 的执行路径、五层结束语义边界、Turn/Step 状态机、工具收口与并行提交、Goal 外循环，以及 Session 持久化的事件溯源设计。

## Default AgentLoop

默认 loop 依赖五项 service：`["agents", "sessions", "llm", "tools", "systemPrompt"]`。主流程：

```
输入进入 inbox
  → turn/start
  → 领取 next-step input 与一条排队消息
  → 读取 prompt sections 与 tool schemas
  → agent/pre-step 接纳、拒绝或改写输入
     → 拒绝：turn/end（blocked），不产生 step
     → 接纳：
       step/start
       → user/message 写入会话日志
       → deriveMessages() 投影模型历史
       → agent/request → llm/stream
       → assistant/chunk* → assistant/message
       → tool/call* → tools/pre-execute → tools/execute → tools/post-execute → tool/result*
       → step/end（仍有工具后续或 next-step input：进入下一 step）
  → agent/turn-stopping
  → turn/end
```

## Five-Layer Boundary of Termination Semantics

生产环境里 `while (hasToolCalls)` 远远不够——结束判断是 Agent Loop 最难的部分（它为什么继续、谁允许它继续、失败后还能不能继续、恢复后应不应该继续）。DSH 把结束拆成五层：

1. **模型请求结束**：Provider 流式输出完成（正常停止/工具调用/最大 token/错误/取消）
2. **step 结束**：一次模型调用 + 该响应发起的一整批工具执行；step 结束不代表 turn 结束（通常欠一次模型回访）
3. **turn 结束**：需同时满足 ①模型不欠回复（无未收口 tool call）②`next-step` inbox 无待处理输入——由"**模型债务 + 消息债务**"共同决定
4. **driver activity 结束**：一个 driver 连续处理多个 turn，队列耗尽回 idle
5. **长期工作流结束**：Goal Driver 监听 idle 检查持久 Goal 开启新 turn；idle 只描述当前 activity，不回答长期目标是否完成

与 Pi 的层级映射：DS step ≈ Pi turn；DS driver activity ≈ Pi invocation。Pi 保留更扁平的循环（steering/follow-up 暴露成回调，复杂度交宿主），DSH 把状态分层、事件日志作重建依据——适合多插件、持久恢复和长期任务。

## Turn / Step State Machine Details

- Driver 入口 `while (await this.turn())`；phase 状态机 `idle / maintenance / running`；`maintenance` 锁存维护期到来的唤醒意图，维护后查 inbox 决定是否重启（解决竞态）
- 领输入前写 `turn/start`，必有唯一 `turn/end` 收口（即使被 pre-step 拒绝或消息为空）
- `step()` 判断顺序（不可改）：`max-tokens` → 返回（**即使有 tool call 也不执行**，防截断 JSON 副作用）→ 无 tool call → `completed` → 有 tool call 执行整批 → 批次 declared concluded → `completed` → 普通批次 → `null`（欠回复，非错误）
- **max-tokens 粘性**：某 step 达上限后，即使后续 step 正常，`turn/end` 仍保留 `max-tokens`——记录整个 turn 的质量，防监控丢失截断事实
- **停止钩子 `agent/turn-stopping` 无布尔返回**：插件向 `next-step` inbox 写消息表示继续。数据驱动消除多插件布尔合并的优先级冲突，代价是学习成本高但可审计

## Tool Consolidation and Ordered Commit

- **收口聚合（OR）**：任一已提交结果 `concludesTurn === true` → 整批 concluded。软收口，取消模型回访债务但不压消息债务，并行工具继续跑——适合权威工具（如取得用户最终决定）。Pi 用 **AND 聚合**（全部 `terminate: true` 才终止），更保守，防单工具吞掉其他结果
- **并行执行、顺序提交**：scheduler 维护 `slots`，工具并行跑，但提交严格按模型调用顺序（`commitReady()` 连续提交就绪 slot）——保证日志/replay/插件观察顺序稳定
- **取消三原则**：①停止补充未启动调用 ②清空已启动调用 ③为跳过的工具写合成错误结果（配对 `tool/call` + `tool/result(error)` 维持协议）；已启动工具可能产生副作用，等 settle 按序提交
- **TurnEndReason 结构化 union**：`completed / blocked / max-tokens / aborted / error / interrupted`（最后者由持久化恢复层产生，闭合进程崩溃留下的开放 turn）；Pi 主要用 provider 的 `stopReason`

## Goal Outer Loop

Round Driver 监听 idle → 检查 Goal 有效/phase active/round 上限 → 构造 goal user message 开新 turn。**持久 phase（active/complete/blocked/paused）与进程内 activation（armed/disarmed）分离**：恢复后 active Goal 默认 disarmed，需人工授权（fail-safe）。Goal 收尾：先 `update_goal` 改持久状态并注入收尾指令，模型生成总结后 turn completed——解决"状态完成"与"用户看到输出"的时间差。

## Session Persistence Design

### Two Sources of user/message

消息来源有两种：**用户直接输入**和**插件注入的上下文**。

- 插件注入：① 通过 inject 直接注入一条 UserMessage；② 通过 `systemPrompt.context` 注册动态上下文，Agent 在发送消息给 LLM 前拼接系统提示词时注入
- 用户输入有三种注入方式：

| 方式 | 语义 | 是否唤醒 Agent |
| --- | --- | --- |
| `followup` | 下一个 turn 进入，进消息队列等待 | 立即唤醒 |
| `steer` | 消息补充，进入下一个 step（类似 Codex 中 Cmd+Enter 强插消息） | 立即唤醒 |
| `inject` | 与 steer 类似，但**静默**，不主动唤醒 | 否 |

### Why tool/call Is Defined Separately

`assistant/message` 输出的调用指令与 `tool/call` 内容非常相似，为何不直接让 `assistant/message` 和 `tool/result` 结对？——设计层面：`assistant/message` 是**模型输出节点**，`tool/call` 是**工具执行前置条件**。不拆出来，执行链路就"隐性"藏在代码后面；显式拆分后节点变多但链路更清晰，且：

- 工具执行时间戳独立，崩溃恢复有据可查
- 配对的 `tool/call` / `tool/result` 降低消息格式错误导致模型调用失败的概率

### request/header: Incremental Recording of Request Parameters

```ts
export interface EpochHeader {
  config: LlmCallConfig
  adapterDefaults?: LlmCallConfigAdapterDefaults
  system?: string        // 系统提示词
  tools?: ToolSchema[]   // 工具定义
}
export interface LlmCallConfig {
  provider: string
  model: string
  reasoningEffort?: ReasoningEffortId
  temperature?: number
  maxTokens?: number
  stop?: string[]
}
```

除 messages 外几乎一次完整 LLM 请求参数的记录。**变动时才追加写入**，多次请求复用同一份内容——省空间且保留了每次请求的完整上下文快照。

### Plugin Extension Point Events (9)

| 事件 | 模式 | 作用 |
| --- | --- | --- |
| `system-prompt/assemble` | waterfall | 组装系统提示词、动态上下文和工具列表 |
| `agent/pre-step` | waterfall | 执行门禁：决定是否进入 Step、带什么消息进入；返回 reject 则直接 turn/end |
| `agent/request` | waterfall | 改变模型供应商/型号/配置参数，**不能修改消息** |
| `llm/stream` | waterfall | 包装或替换自定义流式迭代器 |
| `agent/request-error` | waterfall | 模型请求失败后的恢复，控制重试 |
| `tools/pre-execute` | waterfall | 工具执行前权限校验，返回 `allow / deny / ask`——插件接管权限模块的入口 |
| `tools/execute` | waterfall | 包装实际工具执行函数，可做超时、重试 |
| `tools/post-execute` | waterfall | 操作工具结果，决定以什么形式交给模型（替换内容、做标记） |
| `agent/turn-stopping` | **serial**（唯一） | Turn 即将关闭的最后机会 |

### Notification Events (emit, 5 related to the main chain)

| 事件 | 作用 |
| --- | --- |
| `agent/session-start` | 获取完整 Agent 对象和启动信息 |
| `agent/status` | 获取当前 Agent 状态（执行中/已结束）+ 完整 Agent 对象 |
| `tools/result` | 拿到工具执行链路完整信息（结果+参数），**只能读不能改** |
| `agent/error` | `{ agent, turn, step, error }` 详细错误定位 |
| `session/event` | 每条持久化事件写入 session 存储时立即通知订阅者——前端显示推送、驱动统计/投影重算 |

### Projection: init / apply / view Three Functions

适配模块用三个函数决定一切行为：**init** 初始化数据结构、**apply** 收到更新时计算、**view** 控制展示给前端的数据。

保证**唯一数据源**是 session 持久化文件（Agent 的数据底座）：上下文由它决定，前端显示只是"只读投影"，所有投影适配器的原始数据都来自同一份。设计哲学：把 Agent 上下文作为整个 Harness 最核心的东西，开发专注力放在"Session 文件该放什么、怎么设计"上——有点像上下文驱动整个 Harness 启动。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Cordis 微内核](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)
- [DSH Context / Memory](/docs/CS/AI/LLM/Agent/Product/DSH/Context.md)
- [DSH 子进程管理](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)
- [Agent 四组件](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Pi（AND 聚合对照）](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [DSH 和 Pi 的 Agent Loop 循环结束判断架构细节解析](https://mp.weixin.qq.com/s/7KJgpnKQ0VVHe-oMnS2L5Q)

## References

- [DSH 的宝藏之一：Session 持久化的设计](https://mp.weixin.qq.com/s/uH3vuY9nNCmp-q4yUtRRYA)
- [DeepSeek Harness 底层原理图解（时序图 + 流程图）](https://mp.weixin.qq.com/s/1NWC0Qk-bDkvr8QIVPr1Zg)
