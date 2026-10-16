> 版本基线：核实于 2026-10-06，来源 `docs/subsystems/approval.md` 与 `docs/subsystems/sandbox.md`（官方子系统文档，与源码 `packages/interaction/user-approval`、`packages/sandbox/*` 同步生成）。**权限与沙箱的通用机制（沙箱形态分档、权限判定层级、fail-closed 实现）见 [权限与沙箱理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)**；本页聚焦 DSH 自己的实现细节。

## Introduction

DSH 把「能不能做」拆成两个正交的 knob：**审批策略**（`approval/policy`，管「要不要问人」）与**沙箱模式**（`sandbox/mode`，管「进程能碰什么文件」）。二者由 `dsh-permission-presets` 捆绑成客户端可见的具名预设，但底层始终是两个独立事件。

DSH 在几家产品里的保守程度最显著：审批类型层面不存在「永久授权」，沙箱有 fs-sandbox 策略围栏 + sandbox-local 内核边界双形态且都以 fail closed 为底线。

## Approval Subsystem

`ctx.approval` 是闭合的审批 seam，回答「这个具体操作能不能继续」。结果类型把 fail-closed 写进了类型系统：

```ts
type ApprovalOutcome = 'allowed-once' | 'rejected' | 'cancelled' | 'unavailable'
```

- **唯一授权是 `allowed-once`**：类型层面就不存在「永久授权」——这是 DSH 在几家产品里最保守的设计（详见 [权限与沙箱理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 的审批粒度对比）。`rejected` / `cancelled` / `unavailable` 对调用方一律按拒绝处理。
- **`unavailable` 是 fail-closed 的兜底**：应答者缺失、不负责该请求、抛异常、返回词表外的值，或不合规，结果都是 `unavailable` 而非放行——沉默的故障不会变成放行。
- **按会话策略 `ask` / `never`**：`ask`（默认）委托给组合的应答者链，链无应答则落到 `unavailable`（fail closed）；`never` 在分发前、waterfall 之外确定性返回 `rejected`，是 headless / CI 的严格姿态。生效值由会话日志最后一条 `approval/policy` 事件决定，回放可重建。
- **入口是 `approval/request` waterfall**：UI 通道提供人类应答者，ACP（Agent Client Protocol）自动化桥接层为它拥有的 agent 提供一次性机器决策；调用方（`dsh-tools`、`dsh-tool-bash`）消费闭合结果，非 `allowed-once` 即拒绝。每个请求有独立的品牌化 `ApprovalRequestId`，把 `approval/asked` 与 `approval/decided` 审计事件配对，不与 tool call id 或会话 id 混淆。

## Two Forms of the Sandbox Subsystem

DSH 的「沙箱」其实是两个不同层次的能力，常被人混为一谈：

| 形态 | 提供方 | 隔离性质 | 作用范围 |
| --- | --- | --- | --- |
| **文件系统策略围栏**（fs-sandbox） | `dsh-fs-sandbox`（文件系统 seam 的一部分） | **策略层，不是内核边界** | 路径级：把 read / write / edit 限制在 workspace 根与后端承诺的临时区 |
| **进程沙箱**（sandbox-local） | `dsh-sandbox-local` | **真内核边界**（namespace / LSM / token） | 子进程的文件效果（写入被拒、目录视图受限） |

`SandboxMode` 只管**文件效果**三态：`read-only`（拒绝写入，POSIX runner 仅给 `/dev/null` 接收器）、`workspace-write`（允许在工作区根与临时区写）、`danger-full-access`（绕过隔离，消费方直接 spawn 不调 `ctx.sandbox`）。**网络可见性与进程可见性不在 `SandboxMode` 的词汇内**——这部分由沙箱后端外的其它机制负责。

### fs-sandbox（策略围栏）

文件系统后端在 `writeText` / `editText` 上携带 `sandboxPolicy`；策略插件（`dsh-fs-observation-policy`）通过 `fs/write-intent`、`fs/edit-intent` 两个单槽 waterfall 裁决，未加载策略插件时退化为「无条件裸写入」。它本质是 canonicalize-then-contain 的路径围栏，错误码 `FS_SANDBOX_DENIED` 区别于内核拒绝的 `FS_PERMISSION_DENIED`。

### sandbox-local（内核边界）

`dsh-sandbox-local` 提供平台后端——**Linux 用 bwrap / Landlock、macOS 用 Seatbelt、Windows 用受限令牌（restricted-token）ACL**。强制完整性由后端报告：`full`（管控了模式承诺的全部文件效果）或 `partial`（老旧 Landlock ABI、Windows ACL 的硬链接 / 宽松读 / AppContainer 缺口，归为 `partial`——要求绝对边界的消费方必须拒绝或向上暴露）。消费方按后端方言（`denialSignatures`：bwrap 的 EROFS、Landlock 的 EACCES、Seatbelt 的 EPERM）从 stderr 识别「沙箱正常工作但命令被拦」，与「runner 本身故障」区分开。

### per-call 策略 + fail closed

完整策略（`SandboxExecutionPolicy`）逐次能力调用解析并携带，因此 bash 与受限子 agent 可在同一瞬间向同一提供方请求不同边界；无可用后端时 `ctx.sandbox.confine()` 抛 `SandboxUnavailableError`（`SANDBOX_UNAVAILABLE`），**静默的无隔离透传永远不合法**。

## Permission Preset Layer

`dsh-permission-presets` 把上面的两个 knob 捆绑成具名预设，供客户端作为单一 Permissions 选择器。**默认配置表**自带两项：`workspace-write`（`workspace-write` + `ask`）与 `danger-full-access`（`danger-full-access` + `never`）；`custom` 与 `auto` 是保留名（派生态 / Auto review 集成），不可配置。Auto review 集成在其 effect 生命周期内发布当前会话专属的 `auto` 预设（`danger-full-access` + `ask`，委派子会话固定 `never`）。切换写 `permission/preset` 日志事件，再经各 knob 自己的 setter 落到 `sandbox/mode` 与 `approval/policy`——该层不拥有执行策略，只做组合。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [权限与沙箱理论（通用机制）](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [DSH 工具层](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [官方 approval 文档](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md)
- [官方 sandbox 文档](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md)

## References

- 官方子系统文档（与源码同步生成）：[approval](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md) / [sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md) / [permission-presets](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/permission-presets.md)
