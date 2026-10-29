# BuildKit（构建引擎）

BuildKit 是 Moby 项目下的**构建引擎**，是 `docker buildx` 的底层执行器，也是现代 `docker build`（Engine 23.0+ 默认 BuildKit）真正干活的部分。它把一份构建定义（Dockerfile 或任意 LLB 源）编译成依赖图，并行求解、内容寻址缓存、按 OCI 规范产出镜像。本文是 BuildKit 引擎的归属分册；上层 CLI 与多平台实践见 [Docker Buildx](/docs/CS/Container/Docker/buildx.md)，Dockerfile 指令语义见 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)。

> 版本基线：随 Docker Engine 29 捆绑的 BuildKit 为 v0.33 / v0.34 区间（经 buildx v0.38.x 调用）；经典 `docker build` 自 18.06 起可用 `DOCKER_BUILDKIT=1` 切换引擎。

## 为什么是 BuildKit

经典 builder 把每条指令串行执行、缓存颗粒粗（整层）、secret 容易随 `build-arg` 泄露进层历史。BuildKit 的三个结构性改进：

- **DAG 并行**：指令被编译成有向无环图，互不依赖的 step 并行跑。
- **内容寻址缓存**：同一输入哈希命中缓存、跳过执行，缓存可导出到 registry / 本地 / S3 / GHA。
- **安全 mount**：`RUN --mount=type=secret|ssh` 让凭证只在运行期可见、永不落层。

## 架构分层

BuildKit 由守护进程 `buildkitd` 与客户端 `buildctl` 组成，二者经 gRPC 通信（默认 unix socket `/run/buildkit/buildkitd.sock`，也可暴露 TCP）。一次构建自上而下穿过五层：

```
Client(buildctl / buildx)
   ↓ SolveRequest
Frontend（dockerfile.v0 / gateway.v0 / buildpacks）
   ↓ 把定义翻译成 LLB
LLB（Protobuf DAG，中间格式）
   ↓
Solver（依赖解析、并行调度、缓存命中判定、Jobs Manager）
   ↓ 派发 operation
Worker（OCI / runc，或 containerd）
   ↓
Executor（runc / crun / containerd）
   ↓
Exporter（image / OCI / local / tar / containerd image store）
```

**Frontend**：把构建定义翻成 LLB 的组件，跑在 BuildKit 内部。`dockerfile.v0` 是 Dockerfile 的官方 frontend，用 `# syntax=docker/dockerfile-upstream:...` 指定版本；`gateway.v0` 允许把任意镜像当作 frontend 来用（Earthly、Dagger 等都基于它）；buildpacks 也是一种 frontend。

**Solver**：构建的调度核心。负责把 LLB 图拆成可并行的 operation、查缓存、管理并发 job。

**Worker**：执行环境抽象。两种后端：

| Worker | 形态 | 说明 |
|--------|------|------|
| OCI（runc） | 直接调 runc / crun | 默认 `--oci-worker`，轻量、依赖少 |
| containerd | 复用 containerd daemon | `--containerd-worker`，镜像管理 / snapshot 更丰富，K8s 集成更好，支持 runc / runsc(gVisor) / kata 多运行时 |

**Executor**：真正起进程的地方，OCI 下是 runc，containerd 下是 containerd executor。

**Exporter**：把构建结果写成不同产物（镜像、OCI tar、本地目录、containerd 镜像存储）。

## LLB：Low-Level Build

LLB 是 BuildKit 的**二进制中间格式**（Protobuf 编码），用于定义构建过程的依赖图。一句话类比：**LLB 之于 Dockerfile，如同 LLVM IR 之于 C**——高层 frontend 把各自语法翻成 LLB，solver 只认 LLB。

它的设计目标：

- **内容可寻址**：同一输入产生同一哈希，天然可缓存。
- **可并行执行**：DAG 无环，互不依赖的节点并发。
- **厂商中立**：非 Dockerfile 语言（Buildpacks、Earthfile、HLB、Nix 等）都能实现成 LLB frontend。

## RUN 的 mount 类型

BuildKit 在 `RUN` 上扩展了 `--mount`，是它相比经典 build 最有价值的能力之一。Mount 由 solver 的 mount manager 统一调度：

| mount 类型 | 用途 | 是否入层 |
|-----------|------|---------|
| `type=bind` | 把构建上下文的某文件 / 目录挂进这一步（只读） | 否 |
| `type=cache` | 持久化缓存目录（apt / go mod / npm），跨构建保留 | 否 |
| `type=secret` | 挂载秘密文件，只在运行期可见 | 否 |
| `type=ssh` | 转发 SSH agent，用于私有仓库拉取 | 否 |
| `type=tmpfs` | 临时文件系统 | 否 |
| `readonly` | 配合 bind，挂载为只读 | — |

```dockerfile
# 缓存：Go 模块目录跨构建命中
RUN --mount=type=cache,target=/go/pkg/mod \
    go build -o /out/app .

# 秘密：token 只在这一步可见，绝不进镜像层
RUN --mount=type=secret,id=GH_TOKEN \
    curl -H "Authorization: Bearer $(cat /run/secrets/GH_TOKEN)" https://api.github.com

# SSH：转发 agent，拉私有 git 依赖
RUN --mount=type=ssh \
    git clone git@github.com:org/private-repo.git

# 只读挂单文件，避免 COPY 进层
RUN --mount=type=bind,source=pyproject.toml,target=/tmp/pyproject.toml,readonly \
    pip install -r /tmp/pyproject.toml
```

> 对比：经典 build 把凭证当成 `ARG` 会**永久写进层历史**，任何人拿到镜像都能提取。secret / ssh mount 从根上消除这个问题。

## 缓存模型

BuildKit 的缓存是多层的、内容寻址的：

- **内容哈希缓存**：对文件内容做哈希，输入相同即命中，跳过执行。
- **blob-chain 缓存**：对层 digest 做哈希，便于 registry 缓存复用。
- **引用**：`cache.ImmutableRef`（只读快照）与 `cache.MutableRef`（进行中的构建），带引用计数。
- **存储**：`content.Store` 存不可变内容 blob；`Snapshotter`（overlay / native / fuseoverlayfs）管文件系统快照；`metadata.Store`（BBolt）持久化缓存关系。

两类缓存要分清：

- **层缓存**：每条指令产出的层，受 `RUN` 输入影响。
- **`--mount=type=cache` 持久缓存**：挂载目录独立保留，不因层失效而清空（如包管理缓存）。

**远程缓存后端**（CI 跨机命中）：`registry`（隐藏镜像推到 registry，`mode=max` 含中间层）、`local`（本地目录）、`inline`（嵌进镜像）、`gha`（GitHub Actions）、`s3` / `azblob`（对象存储）。`--cache-from` 与 `--cache-to` 的 `ref` 必须一致，否则命中率低。

## 安全：Entitlements 与 Session

BuildKit 默认以最严格的 `sandbox` 模式执行；越权操作需**显式 opt-in（entitlement）**：

| Entitlement | 作用 |
|-------------|------|
| `network.host` | 允许 step 用宿主机网络（如 `RUN --network=host`） |
| `security.insecure` | 允许特权执行（类似 `--privileged`） |

`insecure` 等于把构建环境敞给 Dockerfile，只应在可信构建里开。

**Session** 是 client 与 daemon 之间的安全通道，用于传输构建上下文与敏感数据，provider 包括：File Sync（传 context / 收产物）、Auth（registry 鉴权）、SSH（转发 agent）、Secret（注入秘密）。秘密经 session 注入，**从不落盘到层**。

网络模式三种：`default`（命名空间隔离）、`host`（需 entitlement）、`none`。

## buildkitd 配置要点

- **worker 选择**：`--oci-worker` / `--containerd-worker`；containerd worker 复用已有 daemon、与 K8s 镜像存储一致。
- **registry mirror**：在 buildkitd 配置里挂 mirror，加速基础镜像拉取。
- **GC**：自动垃圾回收（Automatic GC）清理未被引用的缓存层；可调阈值。
- **rootless**：buildkitd 可 rootless 运行（同 [Docker rootless](/docs/CS/Container/Docker/rootless.md) 的 userns 思路），`docs/rootless.md` 有步骤。
- **TCP 暴露 / 负载均衡**：可把 gRPC 暴露成 TCP 服务做分布式 worker；生产注意鉴权。

## 可观测性

- `BUILDKIT_PROGRESS=plain|auto|tty` 控制进度输出格式。
- `buildctl debug` 可 dump LLB、查 cache 命中、看每步耗时。
- 支持 OpenTelemetry trace（`OTEL_*` 环境变量），把构建过程接入链路系统。
- `buildctl build ... --trace` 导出 trace 文件。

## 与 buildx、containerd 的关系

- **buildx ↔ BuildKit**：buildx 是 BuildKit 的用户态 CLI 封装，负责 builder 实例生命周期、`--platform` 多平台、Bake、缓存导出；真活儿全是 buildkitd 干。
- **containerd ↔ BuildKit**：BuildKit 可作为 containerd worker 跑，镜像直接落 containerd 存储；[containerd](/docs/CS/Container/k8s/containerd.md) 的 snapshotter 与 BuildKit 的 Snapshotter 概念一致。

## Links

- [Docker Buildx](/docs/CS/Container/Docker/buildx.md)
- [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)
- [Docker 镜像](/docs/CS/Container/Docker/image.md)
- [Docker rootless](/docs/CS/Container/Docker/rootless.md)
- [containerd](/docs/CS/Container/k8s/containerd.md)

## References

- [BuildKit GitHub](https://github.com/moby/buildkit)
- [BuildKit Architecture（DeepWiki）](https://deepwiki.com/moby/buildkit/1-overview)
- [Dockerfile frontend syntax（RUN --mount）](https://github.com/moby/buildkit/blob/master/frontend/dockerfile/docs/syntax.md)
- [buildkitd toml reference](https://github.com/moby/buildkit/blob/master/docs/buildkitd.toml.md)
