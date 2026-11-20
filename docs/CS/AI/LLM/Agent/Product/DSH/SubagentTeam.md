## Introduction

DSH 没有 harness 级的独立多 Agent 编排循环。它把"多 Agent"拆成两件正交的事：`subagent` 是一个 provider seam（负责"怎么跑一个子 agent"），`team` 是一个共享任务板（负责"谁干什么"），结果靠 inbox/turn 送回父 agent。

> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。

几个反直觉的点：

- **spawn 不是一次性进程**：它和 fork 一样实现 `prepareContinuable`，都是可后续发消息的可续子 agent；差异只在 seed——spawn 返回空 seed、不继承上下文，fork 冻结父级已完成回合前缀。真正"一次性"的是走 `start()` 的 provider（codex/claude-code/acp）。
- **`inheritsParentContext` 不是能力开关**：它只是描述性字段，不继承工具注册、注入服务或权限；fork 甚至不能独立选 preset（`agentPreset: false`）。
- **team 的任务变更不唤醒任何人**：写任务不结束 wait_agent、不加 inbox 消息、不启动 idle agent——要别人动就得 `send_message`。

## The Subagent Provider Seam

`SubagentProvider` 是 Service Definition：trusted 同进程实现，按能力声明自己支持什么（`packages/subagent/subagent/src/types.ts`）：

```ts
export interface SubagentProvider {
  readonly name: string
  readonly capabilities: SubagentCapabilities
  readonly inheritsParentContext: boolean
  readonly agentRouteDefaults?: Readonly<{ provider: string; model: string }>
  start?(request: ResolvedSubagentStartRequest): Promise<SubagentRun>
  prepareContinuable?(request: ContinuableCreateRequest): Promise<ContinuableCreateSpec>
}
```

判断走哪条执行路径的，就是"有没有 `prepareContinuable` 方法"（`packages/subagent/subagent/src/index.ts`）：

```ts
    const prepare = provider.prepareContinuable?.bind(provider)
    if (prepare !== undefined) {
      return manager.startLocal(spec, (request) => { /* ... */ return prepare(request) })
    }
    const start = provider.start!.bind(provider)
    return manager.startExternal(spec, (request) => { /* ... */ return start(request) })
```

`registerProvider()` 是 effect-scoped、HMR 安全的：移除 provider 阻止新启动，但不撤销已交给持有者的 run（`packages/subagent/subagent/src/index.ts`）：

```ts
  registerProvider(provider: SubagentProvider): () => void {
    if (provider.start === undefined && provider.prepareContinuable === undefined) {
      throw new SubagentError(`subagent provider "${name}" must implement start or prepareContinuable`, 'UNSUPPORTED_CAPABILITY')
    }
    return this.ctx.effect(function* (this: SubagentRuntime) {
      if (this.providers.has(name)) throw new SubagentError(`a subagent provider named "${name}" is already registered`, 'DUPLICATE_PROVIDER')
      this.providers.set(name, provider)
      yield () => { this.providers.delete(name); this.emitLifecycle('subagent/provider-removed', name) }
    }.bind(this), 'subagents.registerProvider()')
  }
```

## Fork vs Spawn vs External

三个 provider 的差异集中在 seed 与继承标记：

```ts
// subagent-spawn-in-process: fresh child, no seed
  readonly inheritsParentContext = false
  prepareContinuable(): Promise<ContinuableCreateSpec> {
    return Promise.resolve({})   // starts fresh, contributes no seed
  }
```

```ts
// subagent-fork-in-process: seeded with completed-turn prefix
  readonly inheritsParentContext = true
  prepareContinuable(request): Promise<ContinuableCreateSpec> {
    const seed = completedTurnPrefix(request.parent)
    return Promise.resolve(seed.length > 0 ? { seed } : {})
  }
```

fork 的 `completedTurnPrefix` 只截到最后一个 `turn/end`（当前 in-flight 回合因 seq 不平衡不能重放），而且**创建时冻结一次**——冷恢复重放那段 seed，而非重新 fork 父级更新后的历史。

外部 provider（如 codex）实现 `start()`、不接后续消息（`packages/subagent/subagent-codex/src/index.ts`）：

```ts
class CodexProvider implements SubagentProvider {
  readonly capabilities: SubagentCapabilities = NO_START_CAPABILITIES
  readonly inheritsParentContext = false
  start(request) {
    const spec: CodexRunSpec = { cwd, permissionMode: this.config.permissionMode,
      spawn: spawnSpec => this.ctx.subprocess.spawn(spawnSpec), /* ... */ }
    return startCodexRun(request, spec)
  }
}
```

模型可见的委派工具 `subagent` 调 `startActivation` 并据 `inheritsParentContext` 生成诚实措辞——fork 与 spawn 对模型说不同的话（`packages/subagent/tool-subagent/src/index.ts`）：

```ts
        const started = await ctx.subagents.startActivation({
          provider: config.provider,
          label: args.description,
          ...request,
          signal: exec.signal,
          delivery: 'parent',
        })
        return { kind: 'activation' as const, name: started.name }
```

`delivery: 'parent'` 表示结算后给直接创建者发一条新消息（相当于给父 agent 开新 turn）；程序化消费者（workflow）用 `delivery: 'caller'`，结果只返回给脚本、不污染父会话。

## Runtime Tree Membership

subagent 的树成员关系从 runtime ownership 解析，不依赖创建者是否驻留（`packages/subagent/subagent/src/manager.ts`）：

```ts
  rootOf(caller: Agent): Agent {
    if (this.ctx.agents.get(caller.id) !== caller) {
      throw new SubagentError('subagent tree access requires the exact live caller', 'UNAUTHORIZED')
    }
    const identity = this.host.identityOf(caller.session)
    const delegated = caller.session.header.origin === 'subagent' || identity != null && caller.session.isOwnSeq(identity.seq)
    // ...
  }
```

发现事实写进父 Session 的 `subagent/catalog` 事件（continuable 或 external），子级身份与创建时间成为父级日志的一部分（`packages/subagent/subagent/src/catalog.ts`）：

```ts
  parent.append('subagent/catalog', { version: SUBAGENT_CATALOG_VERSION, childId: child.id,
    childCreatedAt: child.createdAt, mode: descriptor.mode, label: descriptor.label, name })
```

## Agent Teams: A Shared Task Board

team 不新增创建或消息机制（那些归 subagent），只在 Lead Session 里加一个任务 DAG。任务快照带 CAS 修订号、依赖、owner 与咨询式写范围（`packages/team/agent-team/src/types.ts`）：

```ts
export interface TeamTaskSnapshot {
  readonly id: TeamTaskId
  readonly revision: number
  readonly subject: string
  readonly status: TeamTaskStatus
  readonly ownerId?: SessionId
  readonly blockedBy: TeamTaskId[]
  readonly writeScopes: string[]
}
```

任务写入走 Lead-log 事务 + CAS（`packages/team/agent-team/src/task-board.ts`）：

```ts
      if (current.revision !== request.expectedRevision) {
        throw new TeamError(`stale team task "${current.id}" revision ${request.expectedRevision}; current revision is ${current.revision}`, 'TEAM_TASK_STALE_REVISION')
      }
```

assignee 必须是 root 的可继续后代——team 完全寄生在 subagent 树的成员关系上：

```ts
    const descendants = await this.ctx.subagents.listDescendants(root.id, signal)
    const member = descendants.find(entry => entry.kind !== 'diagnostic' && entry.mode === 'continuable' && entry.id === target)
    if (member === undefined) throw new TeamError(`agent "${target}" is not a continuable descendant ...`, 'TEAM_MEMBER_NOT_FOUND')
```

任务工具按 root 的 session mode 条件可见（`when: ({ agent }) => enabled(agent)`），`writeScopes` 是 advisory 而非锁。

## Presets, Goals, Workflow

**Preset** 是会话级 agent 组合：在 `cordis:group` isolate realm 内挂一棵 preset 插件树，且服务不得泄漏到 root realm（`packages/preset/agent-preset-registry/src/mount.ts`）：

```ts
  const leaked = leakedServices(ctx, ctx.fiber)
  if (audit.failed.length > 0) throw new Error(audit.failed.join('\n'))
  if (leaked.length > 0) throw new Error(`Preset services require isolate realms: ${leaked.join(', ')}`)
```

局部 isolate 不沿 agent scope 传播——普通 `agent.ctx.get()` 看到的仍是 Host realm。

**Goal** 只记录状态、不调度：`goal/change` 事件持久化完整快照，续跑靠 round driver 给自己 inbox 投一条 `source.kind='goal'` 的消息（详见 [Agent Loop 的 Goal Outer Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md?id=goal-outer-loop)）。

**Workflow** 看起来像编排循环，实质是模型写的编排脚本在共享 PTC Node 进程里跑，脚本的每个 `agent()` 最终仍落到 `ctx.subagents.startActivation({ delivery: 'caller' })`（`packages/workflow/workflow-ptc/src/host.ts`）。它是"用户态脚本编排"，不是 harness 内建循环。外部 provider（acp / codex / sdk）作为表示层适配器接入，与前端同属表示层，见 [Boot & Frontends](/docs/CS/AI/LLM/Agent/Product/DSH/BootAndFrontends.md)。

## Comparison with Codex / Claude Code

- **Codex / Claude Code = harness 拥有编排**：内建 Task/Agent 工具，父 agent 主动拉结果。
- **DSH = provider seam + task board**：provider 负责"怎么跑子 agent"，task board 负责"谁干什么"，agent 自己靠 inbox/turn 推进。模型调完 `subagent` 立即拿到 name 并**结束自己的 turn**，结果到达时开新 turn。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Session & Persistence](/docs/CS/AI/LLM/Agent/Product/DSH/SessionPersistence.md)
- [DSH Cordis 微内核](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)
- [多 Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）subagent](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/subagent)
2. [架构文档 — Capability seams](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/architecture.md)
3. [DSH 官方文档站](https://deepseek-harness.github.io/deepseek-harness/)
