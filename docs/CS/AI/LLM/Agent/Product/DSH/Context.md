> 版本基线：核实于 2026-10-06。上下文、记忆、知识三者围绕 Session Log 协同，共享一条约束：**模型看到的内容必须有可追踪来源，且能从会话记录重建**。

## Introduction

上下文、记忆、知识三者不是三个独立系统，而是围绕 Session Log 协同工作。核心链路：

```
SystemPrompt.assemble() 组装上下文
→ ReactLoopAgent.preStep() 决定动态内容是否进入会话
→ Session.append() 保存事件
→ Session.deriveMessages() 生成模型历史
→ buildRequest() 构建最终请求
→ llm.stream() 完成模型调用
```

本文覆盖：四类上下文的装配与避免重复注入、Compaction（会话内记忆压缩）的完整机制、以及 DSH 如何获取外部知识（不依赖统一向量库）。

## Context Management

### Four Categories of Context, Each with Ownership

**四类上下文、各有归属**：系统规则（SystemPrompt）/ 动态状态（Runtime Context）/ 会话历史（Session）/ 工具定义（ToolRuntime），模型调用前统一装配；AgentLoop 只管执行流程，不承担拼接。

- `SystemPrompt.assemble()` 收集 `sections`（稳定提示）、`contexts`（动态环境）、`tools`、`variables`，各插件只注册自己的内容，每次生成本轮快照
- **避免重复注入**：`RuntimeContextProjection` 比较本轮与上轮快照——不变则沿用，变化才生成新上下文消息写入 Session（省 token + 保留状态变化轨迹；投影状态可从 Session 恢复，重启不重复注入）
- **三层结构**：**Log**（完整原始事件）→ **Surface**（当前参与派生的事件视图）→ **Messages**（发给模型的协议消息）。`deriveMessages()` 是唯一出口——模型输入不是各模块临时修改的消息数组，而是会话记录的派生
- `buildRequest()` 同时记录 `request/header` 和 `request/context`：可回答"模型当时看到了哪些历史/哪版系统提示/哪些工具/异常是推理问题还是输入问题"

## Memory Compaction (Compaction = Session Memory)

跨 Session 的长期记忆目前**没有形成完整系统**，现有记忆能力是 Compaction——服务于当前会话的连续运行。

- **只改 Surface**：摘要作为 replacement 节点遮蔽旧历史，原始事件留盘（比"删除前 N 条"安全：可审计压缩范围和摘要来源）——但**模型无法取回**，召回工具（`recall_history` 式）仍是 proposed 状态的 Agent Note
- **触发**：`floor(min(W × thresholdRatio, W − O − headroomTokens))`，默认 `thresholdRatio = 0.8`、`headroomTokens = 65536`（`W` 上下文窗口、`O` 单次请求输出预留）。两个入口——`agent/pre-step` 的 `pressure` 前瞻检查 + `agent/request-error` 的 `context-overflow` 兜底（后者绕过常规阈值与保留策略，`maxOverflowRetries` 默认 1）
- **区域选择**：优先折叠旧历史、保留近期（`retainRatio = 0.16`，按 `W − O` 计）；`validateSurfaceRegion()` 校验不切开 tool-call/tool-result 配对；surface 节点 0 的 `system/message` 永不被遮蔽
- **摘要固定模板**（8 节，以源码为准）：`Primary Request and Intent / Key Technical Concepts / Files and Code / Errors and Fixes / Pending Jobs / Current Work / Next Step / Critical Context`——防摘要退化成流畅但执行接不上的对话概述
- **替换事务**：`compaction/start` → 摘要 → `user/message`（`surfaceOp: replace`，`sourceEventSeqs` 关联被覆盖事件）→ `compaction/end`；三个 compaction 事件**仅写日志、绝不进 surface**，摘要由那条 `user/message` 承载；压缩失败时旧 surface 继续可用
- **收缩校验**：若摘要的 frame 后 token 数 ≥ 被遮蔽内容的 route 定价 token 数，直接抛错拒绝提交——摘要必须真的变小
- **有损风险**：摘要漏掉约束后模型可能执行错误命令——Log 完整性解决审计，没解决信息恢复；改进方向是 `recall_history` 式历史召回工具（按 turn/step/event seq/tool call id/文件路径结构化检索）
- **调度延迟**：压缩调一次 LLM 且在主流程上，长会话会卡顿；已落地的缓解是把指令放在回放前缀**之后**作为最后一条 user 消息，使辅助请求复用热前缀缓存（换 provider/model 或压缩非头部范围则放弃复用）

> 压缩机制的通用原理与各家实现对比见 [Compaction 理论](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)。

## Knowledge Acquisition (without vector store)

DSH **没有传统统一向量知识库**。知识入口 = 文件路径引用 + Web 搜索抓取 + 工具结果写回 Session。代码仓库有路径/符号/引用结构，统一切块进向量库会损失结构信息。

- **文件引用分层**：`file-reference-local` 只负责找到路径（`@path` 插入输入框），`read` 工具负责读取内容——选择路径时就展开文件会占满上下文、绕过 guard、丢失版本记录；`WorkspaceFileSearch` 控制目录边界、拒绝 `..`/符号链接跳出 workspace
- **检索四层逻辑**（优先消耗确定性信息）：已知路径直接 read → 已知文本 grep → 已知符号 LSP（定义/引用/诊断）→ 只有概念描述才考虑语义检索
- **Web 检索三层**：`WebRuntime` 定义能力 → search/fetch provider 具体请求 → `tool-web` 注册为模型可见工具；provider 选择严格（指定 id 或唯一可用，多 provider 报错，避免加载顺序影响线上行为）
- **网络边界**：HTTP fetch provider 限制协议/私网地址/重定向/字节数/固定 DNS；模型生成的 URL 是不可信输入，Prompt Injection 可能诱导请求内网——**网络策略必须在模型之外执行**

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [Compaction 理论（通用机制与各家对比）](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [DSH 的上下文管理、记忆和知识库剖析](https://mp.weixin.qq.com/s/RG5oQ6rpNDNn7Fwo9GoqIA)

## References

- [DSH 的上下文管理、记忆和知识库剖析](https://mp.weixin.qq.com/s/RG5oQ6rpNDNn7Fwo9GoqIA)
- [DSH 的宝藏之一：Session 持久化的设计](https://mp.weixin.qq.com/s/uH3vuY9nNCmp-q4yUtRRYA)
