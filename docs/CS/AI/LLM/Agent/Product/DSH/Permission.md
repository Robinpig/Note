> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。权限与沙箱的通用机制见 [权限与沙箱理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)；本页聚焦 DSH 自己的源码实现。

## Introduction

DSH 把「能不能做」拆成两个正交的 knob：**审批策略**（`approval/policy`，管「要不要问人」）与**沙箱模式**（`sandbox/mode`，管「进程能碰什么文件」）。二者由 `dsh-permission-presets` 捆绑成客户端可见的具名预设，但底层始终是两个独立事件。

> 版本基线：v0.2.2-rc.3。

几个反直觉的点：

- **类型层面不存在"永久授权"**：`ApprovalOutcome` 只有 `allowed-once` / `rejected` / `cancelled` / `unavailable`——这是 DSH 在同类产品里最保守的设计。
- **沙箱有两个层次常被混为一谈**：fs-sandbox 是策略围栏（受信代码做路径规范化→包含判定，明确"不是安全边界"），sandbox-local 才是内核隔离；前者防不可信"路径"，后者防不可信"代码"。
- **`never` 策略在 waterfall 之外确定**：审批服务在分发前就返回 `rejected`，因为后注册的 `prepend` 监听器不可能被"listener 形状的门"可靠地绕过。

## Approval: allowed-once and Fail-Closed

`ctx.approval` 是闭合的审批 seam。结果类型把 fail-closed 写进类型系统（`packages/interaction/user-approval/src/index.ts`）：

```ts
const OUTCOMES: readonly ApprovalOutcome[] = ['allowed-once', 'rejected', 'cancelled', 'unavailable']
```

`decide()` 把 `never` 策略、异常应答者、词表外的返回值全部归一化成拒绝，绝不沉默放行：

```ts
  private async decide(req: ApprovalRequest, session: Session): Promise<ApprovalOutcome> {
    const signal = req.signal
    if (signal?.aborted) return 'cancelled'
    // The 'never' policy is decided HERE, before any dispatch: a listener
    // registered with `prepend: true` after this service mounts would sit
    // ahead of any gate LISTENER, so a listener-shaped gate cannot keep the
    // documented promise that 'never' rejects deterministically ...
    if (this.effectivePolicy(session) === 'never') return 'rejected'
    const answer: Promise<ApprovalOutcome> = Promise.resolve().then(
      () => this.ctx.waterfall(
        scopeTarget(req.agent, req.agent), 'approval/request', req,
        () => Promise.resolve<ApprovalOutcome>('unavailable'),
      ),
    ).then(
      outcome => OUTCOMES.includes(outcome) ? outcome : 'unavailable',
      () => 'unavailable',
    )
```

每个请求有品牌化 `ApprovalRequestId`，`approval/asked` 与 `approval/decided` 成对写入 session 审计日志。 consume 侧（tools 管线）只把 `allowed-once` 映射成 allow，其余拒绝（见 [Tools 的审批接线](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)）。

## Two Forms of the Sandbox

| 形态 | 提供方 | 隔离性质 | 防什么 |
| --- | --- | --- | --- |
| **文件系统策略围栏**（fs-sandbox） | `dsh-fs-sandbox` | 策略层，不是内核边界 | 模型可控的"路径" |
| **进程沙箱**（sandbox-local） | `dsh-sandbox-local` | 真内核边界（namespace / LSM / token） | 不可信"代码"的文件效果 |

`SandboxMode` 只管**文件效果**三态：`read-only`、`workspace-write`、`danger-full-access`。网络可见性与进程可见性不在其词汇内。

### fs-sandbox: A Policy Fence, Not a Security Boundary

源码注释直白说明边界（`packages/fs/fs-sandbox/src/index.ts`）：

```
 * The fence is a policy check in TRUSTED code over a MODEL-CONTROLLED path,
 * NOT a kernel boundary ... This is containment, not a security boundary;
 * kernel-grade isolation of untrusted CODE stays `ctx.shell`'s job.
```

`checkedTarget()` 在 workspace-write 下对**新解析的路径**重新做包含判定，防止工具解析后祖先符号链接被替换（收窄 TOCTOU；残余竞态被接受）：

```ts
    const fresh = await this.resolve(target.displayPath)
    let contained = false
    for (const root of writableRoots(policy)) {
      if (await isPathUnder(fresh.targetKey, root)) {
        contained = true
        break
      }
    }
    if (!contained) {
      throw new FsError(`cannot write "${target.displayPath}": file access denied under workspace-write mode`, 'FS_SANDBOX_DENIED')
    }
    return fresh
```

错误码 `FS_SANDBOX_DENIED` 区别于内核拒绝的 `FS_PERMISSION_DENIED`。

### sandbox-local: Kernel Boundary

`SandboxProvider.confine()` 抽象只做一件事——把 argv 包成受限执行，并返回强制完整性等级（`packages/sandbox/sandbox/src/index.ts`）：

```ts
export abstract class SandboxProvider extends Service {
  abstract confine(argv: readonly string[], policy: SandboxPolicy, signal?: AbortSignal): Promise<ConfinedArgv>
}
```

平台后端的 argv 构造（`packages/sandbox/sandbox-local/src/profiles.ts`）：

```ts
export function bwrapProfileArgs(policy: SandboxPolicy): string[] {
  const args = ['--ro-bind', '/', '/', '--dev', '/dev', '--unshare-pid', '--proc', '/proc', '--die-with-parent']
  if (policy.mode === 'workspace-write') {
    args.push('--tmpfs', '/tmp')
    for (const root of workspaceWritableRoots(policy)) args.push('--bind', root, root)
  }
  return args
}

export function landlockProfileArgs(policy: SandboxPolicy): string[] {
  const readWrite = ['/dev/null']
  if (policy.mode === 'workspace-write') {
    readWrite.push('/tmp', ...workspaceWritableRoots(policy))
  }
  return landlockGrantArgs({ readOnly: ['/'], readWrite })
}
```

macOS 用 Seatbelt 的 SBPL 规则（`(deny file-write*)` + 白名单 subpath），Windows 用受限令牌 ACL。完整性等级 `full` / `partial` 由后端上报，要求绝对边界的消费方必须拒绝 `partial`。消费方按后端方言的 `denialSignatures`（bwrap 的 EROFS、Landlock 的 EACCES、Seatbelt 的 EPERM）从 stderr 区分"沙箱正常工作但拦了命令"与"runner 本身故障"。

**fail-closed 贯穿全局**：没有可用后端时 `ctx.sandbox.confine()` 抛 `SANDBOX_UNAVAILABLE`，绝不静默无隔离透传；escalation 要求严格更宽的 mode + 审批，且只在本次调用生效。

## Permission Preset Layer

`dsh-permission-presets` 把两个旋钮捆成具名预设（`packages/interaction/permission-presets/src/index.ts`）：

```ts
  private apply(session: Session, name: string, setApproval: (policy: ApprovalPolicy) => void): void {
    const spec = this.resolve(name)
    if (name === AUTO_PRESET) this.autoAdmit?.()
    const current = this.current(session)
    // ...
    if (current !== name) session.append('permission/preset', { preset: name })
    updateKnobs()
  }
```

默认两项：`workspace-write`（workspace-write + ask）与 `danger-full-access`（danger-full-access + never）；`custom` / `auto` 是保留名。切换写 `permission/preset` 事件，再经各 knob 的 setter 落到 `sandbox/mode` 与 `approval/policy`——该层不拥有执行策略，只做组合。进程树收尾见 [Subprocess](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [权限与沙箱理论（通用机制）](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [DSH 工具层](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [DSH Subprocess 子进程管理](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）sandbox](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/sandbox)
2. [subsystems/approval.md](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/subsystems/approval.md)
3. [subsystems/sandbox.md](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/subsystems/sandbox.md)
