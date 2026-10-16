> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

沙箱回答「能访问什么」——文件可写范围、网络、系统调用。Codex 的策略层只有三个模式，但每个模式在三平台上的落地机制都不一样：macOS 走 Seatbelt，Linux 走 seccomp + Landlock + bubblewrap，Windows 走受限令牌 + 独立沙箱服务。策略描述（`sandboxing` crate）与平台执行（各平台 crate）分离，是这层代码的基本结构。

## SandboxMode

`protocol/config_types.rs:104` 的 `SandboxMode` 三态（kebab-case 序列化）：

| 模式 | 语义 |
| :--- | :--- |
| `read-only`（默认） | 只读；一切写操作都要审批或落在显式授权根内 |
| `workspace-write` | 工作区内可写，配 `writable_roots` 等细项 |
| `danger-full-access` | 完全访问，无沙箱保护 |

**默认 `read-only`**——这与 Claude Code 沙箱默认关闭正好相反，是 Codex 保守安全姿态的基线。模式由 `TrustLevel`（项目目录信任级）与显式配置共同决定，见 [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)。

## Platform Backends

`sandboxing/src/lib.rs` 按目标 OS 编列不同后端，统一出口是 `SandboxManager` / `SandboxExecRequest` / `SandboxTransformRequest` 一族（`get_platform_sandbox` 选择当前平台实现，`SandboxType` 标注类型）：

| 平台 | 机制 | 源码落点 |
| :--- | :--- | :--- |
| macOS | Seatbelt（`sandbox-exec` 风格配置文件） | `sandboxing/src/seatbelt.rs`、`seatbelt_daemon.rs`、`seatbelt_scratch.rs` |
| Linux | 进程内限制（`no_new_privs` + seccomp）+ bubblewrap 文件系统隔离 | `linux-sandbox/src/`（`seccomp.rs`、`bwrap.rs`、`launcher.rs`、`fd_mount.rs`） |
| Windows | 受限令牌沙箱 + 独立服务进程 | `windows-sandbox-rs`、`windows-sandbox-service`、`mxc-sandbox` |

几个值得知道的实现细节：

- **Linux 侧双管齐下**：`no_new_privs` + seccomp 收窄系统调用（进程内、无外部依赖），bubblewrap 做文件系统命名空间隔离；bwrap 可以打包随二进制分发，且**启动前做摘要校验**（`BUNDLED_BWRAP_DIGEST_VERIFICATION_FAILURE_EXIT_CODE = 8`），校验失败直接拒绝启动
- **Seatbelt 有配套 daemon 与 TLS 测试**：`seatbelt_daemon.rs`、`seatbelt_tls_tests.rs`、`seatbelt_network_tests.rs` 说明网络与 TLS 行为是沙箱策略的一等公民
- **WSLg 适配**：`linux-sandbox/src/wslg.rs` 处理 WSL 图形环境
- **错误归因**：`denial.rs` 的 `is_likely_sandbox_denied` / `is_likely_executor_managed_sandbox_denied` 判断一次失败是不是沙箱拒绝——排障时先把「沙箱挡了」和「程序自己错了」分开

## Network Policy

网络默认是**禁**的，放开有两条路：配置里的静态规则，或会话中经审批的 `NetworkPolicyAmendment`（按 host allow/deny，见 [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)）。执行侧：

- `network-proxy` crate 承担代理与路由（Linux 侧还有 `proxy_lifecycle` / `proxy_routing` 管理其生命周期）
- `sandboxing` 里的 `with_managed_mitm_ca_readable_root`：托管 MITM CA 的可读根——沙箱内进程发起的 TLS 连接由代理终结，** CA 根证书对沙箱内可读**，所以证书验证不会失败（也意味着流量可被审计）
- `network_policy_decision.rs` 与 `exec-server` 的 `network_policy_decisions` 是策略判定点；`NetworkSandboxViolation` / `record_network_sandbox_violation` 记录违规

## Integrity and Violations

两块横向能力：

- **完整性检查**（`sandbox_integrity`）：`FileContentsChecker` / `IntegrityFinding` 校验沙箱相关文件内容未被篡改—— bundled 二进制的摘要校验是同一思路的延伸
- **违规记录**（`violation.rs`）：`FileSystemSandboxViolation` / `NetworkSandboxViolation` 带 `SandboxViolationBackend`（哪个后端记录的）落遥测，违规不是静默失败

`sandbox_tags.rs` 给沙箱事件打标签（哪个后端、哪种策略），`policy_transforms.rs` 负责策略在层间的变换，`compatibility_sandbox_policy_for_permission_profile` 处理权限 Profile 与沙箱策略的兼容映射。

## Sandbox and Exec-server

沙箱不是「在进程里 fork 一个受限子进程」这么简单：`exec-server` 提供 `sandboxed_file_system` / `sandboxed_file_open` / `sandbox_selection` 与 `process_sandbox`，把文件与进程执行都收拢到同一套受控通道，且可以经 Noise 加密中继代理到远端——本地沙箱与云端执行因此共享同一份策略代码，见 [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Approval：审批](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Codex/Tools.md)
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) — 沙箱与权限的两层之分、各产品默认值对照
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 四层安全模型

## References

- [openai/codex](https://github.com/openai/codex)
