## Introduction

镜像（image）不是一个"大文件"，而是一组**按内容寻址的对象**：manifest 描述层顺序，config 描述运行时默认参数，layer 是文件系统差分 tarball。理解这点，`docker pull` 为什么快、为什么改一行代码只重传一层、为什么 tag 可以随便改而 digest 不能，就都顺理成章了。

标准由 OCI Image Spec 定义（当前 v1.1.1），Docker 与 [containerd](/docs/CS/Container/k8s/containerd.md)、Podman、CRI-O 共用这套格式，所以一个 `docker build` 出来的镜像可以直接被 K8s 拉起来。

## 镜像的内部结构

```
             ┌─ index (manifest list) ── 多平台入口
             │      ├── linux/amd64 manifest ─┐
             │      └── linux/arm64 manifest ─┤
             └─ manifest ─────────────────────┘
                    ├── config blob（Env / Cmd / 层 diffID 历史）
                    └── layers[]（每个是 tar.gz 的 digest + size）
```

- **index**：可选，把同一 tag 指向多个平台的 manifest；客户端按 `os/architecture/variant` 选一份
- **manifest**：列出 config 与有序的 layer 描述符
- **config**：镜像的"运行说明书"——环境变量、默认命令、暴露端口、用户、层历史
- **layer**：文件系统差分，删除文件用 whiteout 标记（`.wh.` 前缀）表达

全部对象按 **SHA-256 digest** 寻址，所以：

```shell
# tag 可变，digest 不可变——部署时钉 digest 才叫"确定版本"
docker buildx imagetools inspect alpine:3
docker pull alpine@sha256:<digest>
```

## 分层与写时复制

镜像层全部只读，多个镜像共享同一层（这就是"一个基础镜像被多个镜像共用"的缓存逻辑）。容器启动时在最上面加一层**可写层（container layer）**：

- **读**：从上往下找，命中即返回
- **写**：新文件直接写可写层
- **改**：把只读层的文件复制到可写层再改，即 **Copy-on-Write**
- **删**：在可写层写 whiteout 标记，遮蔽下层文件

```shell
docker images

# 需要先修改为规范的镜像
docker tag name:version username/name:version

docker push username/name:version
```

CoW 的两个副作用值得记住：

1. 删掉只读层里的大文件**不会**让镜像变小，因为底层还在；瘦身必须靠多阶段构建
2. 修改大文件（如 2GB 的数据库文件）会触发整文件向上复制，写放大很明显——这类数据应该放 volume，见 [Docker 存储](/docs/CS/Container/Docker/storage.md)

## 与 registry 的交互

registry 按 OCI Distribution Spec（v1.1.1）提供 HTTP API（registry 的协议模型、私有部署与 GC 见 [Docker Registry](/docs/CS/Container/Docker/registry.md)），pull/push 实际是：

1. 解析 tag → 拿 index/manifest
2. 比对本地 content store，**只下载缺失的 blob**
3. 校验 digest，解压层到 snapshotter
4. 生成镜像记录

Docker Hub 对匿名/免费账号有拉取速率限制，CI 里建议：镜像仓库自建或用云厂商镜像服务、登录账号、加 registry mirror（配置见 [Docker](/docs/CS/Container/Docker/Docker.md)）。

Image Spec 1.1 引入的 **Referrers API** 让签名、SBOM、provenance 可以作为独立 artifact 挂在同一个 digest 上，这是供应链安全的地基，见 [Docker 安全](/docs/CS/Container/Docker/security.md)。

## 常用命令辨析

| 命令 | 作用 | 边界 |
| :-- | :-- | :-- |
| `docker pull / push` | 与 registry 交换镜像 | 需要登录与网络 |
| `docker images / rmi` | 查看 / 删除本地镜像 | 被容器引用的镜像删不掉（除非 `-f`） |
| `docker tag` | 给同一个镜像 ID 加一个名字 | 只是起别名，不复制数据 |
| `docker history --no-trunc` | 看每层对应的构建指令 | 元数据可能被 `--squash` 抹掉 |
| `docker save / load` | 导出/导入含层的完整镜像归档 | 走 stdin/stdout，适合离线交付 |
| `docker export / import` | 导出/导入**容器的文件系统快照** | 丢掉层历史与元数据，慎用 |
| `docker buildx build` | 构建，支持多平台与缓存导出 | 见 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md) |

`docker history --no-trunc <image>` 是不装任何工具就能做的"层考古"，排查镜像来源时先跑它。要还原成 Dockerfile 见 [Docker 工具](/docs/CS/Container/Docker/tools.md)。

## 体积优化

镜像体积直接影响拉取时间、CI 时长、攻击面和存储成本。按收益从高到低：

1. **选对基础镜像**：`scratch` < `distroless` < `alpine` < `slim` < 完整发行版。`scratch` 是空镜像，只放静态编译产物；`alpine` 用 musl libc，注意 DNS 解析与 glibc 行为差异
2. **多阶段构建**：编译期依赖留在 builder 阶段，只把产物 `COPY --from` 到运行阶段
3. **层顺序与缓存**：把变化频率低的指令（装依赖）放前面，变化频繁的（拷源码）放后面
4. **`.dockerignore`**：挡住 `.git`、`node_modules`、构建产物，既减小上下文又避免误拷密钥
5. **同一层内清理**：`apt-get install && rm -rf /var/lib/apt/lists/*` 必须写在同一条 `RUN`，否则删除只是 whiteout
6. **不要装用不上的东西**：curl、vim、systemd 之类调试工具在生产镜像里都是负担

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.25 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download          # 依赖层独立，源码变了不重跑
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app ./cmd/server

FROM gcr.io/distroless/static-debian12
COPY --from=builder /app /app
USER nonroot:nonroot
ENTRYPOINT ["/app"]
```

分析工具：`docker scout quickview`、`dive`（交互式看每层增了什么），见 [Docker 工具](/docs/CS/Container/Docker/tools.md)。

## 供应链安全

镜像是"别人给你的二进制"，交付链路上有三件事要做：

- **扫描**：`docker scout cves`、`trivy`、`grype` 扫 CVE；CI 里按严重级别设门禁
- **签名与验签**：Docker Content Trust 已从 CLI 移除，改用 Sigstore [cosign](https://github.com/sigstore/cosign) 签名并存成 registry 里的 referrer artifact
- **来源证明**：BuildKit 的 SLSA provenance（`--provenance=true`）记录构建输入与环境，回答"这个二进制是怎么来的"

```shell
cosign sign --key cosign.key myregistry/app:v1
cosign verify --key cosign.pub myregistry/app:v1
```

## 多平台镜像

一个 tag 可以指向多份机器码，客户端按本机平台选（构建端用 [Docker Buildx](/docs/CS/Container/Docker/buildx.md) 的 `--platform` 一次出多架构）：

```shell
docker buildx create --use --name multi --driver docker-container
docker buildx build --platform linux/amd64,linux/arm64 -t app:v1 --push .
docker buildx imagetools inspect app:v1
```

原生构建（多台构建机）最快，跨架构靠 QEMU 仿真则慢得多，交叉编译是折中方案。注意：平台匹配只保证"选对了那份二进制"，不保证内核 ABI 与库依赖可跑。

## Links

- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Container](/docs/CS/Container/Container.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [OCI Image Specification](https://github.com/opencontainers/image-spec)
2. [OCI Distribution Specification](https://github.com/opencontainers/distribution-spec)
3. [Docker Scout](https://docs.docker.com/scout/)
4. [Sigstore Cosign](https://github.com/sigstore/cosign)
