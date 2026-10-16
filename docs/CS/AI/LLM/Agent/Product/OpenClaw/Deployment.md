## Introduction

这一页是 OpenClaw 的**部署与托管形态**：单机怎么装、容器怎么跑、多机怎么管。入口形态（CLI / TUI / 原生 app）在 [Clients](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Clients.md)，这一页只管「Gateway 这个进程被谁托管、跑在哪」。所有形态共用同一套端口模型：18789 主端口 + 18790 MCP App sandbox 延迟端口，见 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md)。

## Deployment Forms

按「由内到外」分三层：

- **本地原生 + 本地 Gateway**：`apps/`（Swift）作为前端连本机 Gateway，即「个人安装独占一台设备」形态。
- **容器 / 平台**：Docker Compose 里 `openclaw-gateway`（18789 + 18790）与 `openclaw-cli` 共享 gateway 网络命名空间，安全基线是 `cap_drop: NET_RAW/NET_ADMIN`、`no-new-privileges`、只读 host 路径 pin；另有 `fly.toml`（Fly.io）与 `render.yaml`（Render）。
- **共享 vs 个人**：共享 Gateway 用于团队协作（同一 session 可承载多个人类、信用与历史），个人安装独占设备。

## Daemon

`src/daemon/` 管「单机 Gateway 如何成为系统守护进程」，几处设计相当克制：

- **macOS launchd 事务性安装**：`launchd-install.ts` 做安装 / 卸载（先 `launchctl bootout` 再移入 `.Trash`，带 rollback），而不是覆盖式写 plist——卸载失败能退回原状。
- **自适应堆策略**（`gateway-heap.ts`）：按物理 / 受限内存算 `maxOldSpaceSize`，floor 2048 MiB、cap 8192 MiB——既防小内存机起不来，也防大内存机上 Gateway 无限吃内存。注意它与 [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) 的运行期堆采样（`diagnostic-heap-profile.ts`）**同名异主**：一个管启动预算，一个管采样快照。
- **托管停机**（`hosted-stop.ts`）：先校验进程身份与 cgroup（读 `/proc/<pid>/cgroup`），并区分监督者——由外部 supervisor 托管时**拒绝自停**，避免把被监督的进程误杀。

## Fleet

`src/fleet/` 管「多机 cell」：把多个 Gateway 实例容器化统一管理。

- **`FleetCellRecord`**（tenantId / image / runtime / hostPort / containerName / dataDir）落 state DB 的 `fleet_cells` 表；`reserveFleetCell` 在**单写锁内分配 hostPort**——防并发创建两个 cell 抢同一端口。
- 对同一 cell 的并发操作用 `state_leases` 表做**带 TTL 的操作租约**（`acquireFleetCellOperation`）——与 Claw 包安装、插件生命周期共用同一张表、三种 scope。
- 容器化默认 docker bridge，podman 支持 `--internal` 网络；创建时做端口探测但**明确标注 TOCTOU 间隙**——runtime bind 才是权威，又一次「探测不等于生效」。
- **CLI 读 `fleet_cells` 必须走只读事务**——避免把自己挂进 Gateway 可写 SQLite 的生命周期里（与 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 写路径的 commit guard 同族思路）。
- `doctor.runtime.ts` / `backup.runtime.ts` 提供 cell 健康检查与备份 / 恢复；cell 即一个独立 Gateway 实例，复用同端口模型。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Clients](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Clients.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md)
