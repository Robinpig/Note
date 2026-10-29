## Introduction

`docker buildx` 是 Docker 的扩展构建 CLI，底层统一走 **BuildKit**（经典 `docker build` 用的是旧 builder）。Engine 23.0 起 buildx 随 Docker Desktop / 官方包捆绑，无需单独安装即可用 `docker buildx`。

它要解决的痛点，恰恰是经典 build 做不到或很别扭的：

- **一次构建多平台镜像**（amd64 / arm64 同时出，常见于边缘、Apple Silicon 本地构建后推到 x86 集群）。
- **可移植、可复用的缓存**（缓存能导出到 registry / 本地 / 内联，CI 里能跨机器命中）。
- **Bake**：用一份 HCL/YAML/Compose 描述"一仓库多镜像"的构建矩阵。
- **远程 / 云构建**：构建可以跑在容器、Kubernetes、甚至 Docker Build Cloud 上，而非仅限于本机 daemon。

> 版本基线：buildx 当前稳定线 **v0.38.x**（2026-10），随 Docker Engine 29 捆绑的 BuildKit 为 v0.33 / v0.34 区间。

## 与经典 build 的区别

| 维度 | `docker build`（经典） | `docker buildx build` |
| :-- | :-- | :-- |
| 执行引擎 | 旧 builder | BuildKit |
| 多平台 | 不支持 | `--platform` 一次出多架构 |
| 缓存复用 | 仅本机隐式层缓存 | 可导出/导入到 registry、local、inline |
| secret / ssh | 粗（build-arg 泄露风险） | `mount=type=secret` / `ssh` 不进镜像 |
| Bake 多目标 | 无 | 原生支持 |
| 远程构建 | 无 | container / kubernetes / remote / cloud driver |

构建目标仍是 `Dockerfile`，只是由 BuildKit 把指令编译成 DAG（LLB）并行执行，因此 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md) 里讲的多阶段、`cache mount`、`# syntax=` 在 buildx 下全部生效且更强。

## builder 实例

buildx 的核心抽象是 **builder**：一组运行 BuildKit 的节点。默认有一个 `default`（用 `docker` driver，单节点，不能多平台）。

```bash
docker buildx ls                    # 列出 builder 实例
docker buildx create --name myb \
  --driver docker-container \       # 在容器里跑 buildkitd，支持多平台
  --bootstrap                      # 创建后立即启动
docker buildx use myb              # 切换当前默认 builder
docker buildx inspect --bootstrap  # 查看节点状态
docker buildx rm myb               # 删除
```

**driver 类型**：

| Driver | 形态 | 多平台 | 说明 |
| :-- | :-- | :-- | :-- |
| `docker`（默认） | 复用本机 daemon | 否 | 最简单，等价于旧 build |
| `docker-container` | 独立容器跑 buildkitd | 是（配 QEMU） | 最常用 |
| `remote` | 远程 buildkitd 地址 | 是 | 复用已有构建机 |
| `kubernetes` | K8s Pod 跑 buildkitd | 是 | CI 内复用集群 |
| `cloud` | Docker Build Cloud | 是 | 云端托管，缓存共享（0.37+） |

## 多平台构建

多平台镜像本质是 **manifest list / image index**：一个索引指向多个单架构 manifest。

```bash
# 1) 一次性注册 QEMU + binfmt，让本机内核能执行异架构二进制（仅需一次）
docker run --privileged --rm tonistiigi/binfmt --install all

# 2) 用 container driver 的 builder
docker buildx create --name multi --driver docker-container --bootstrap
docker buildx use multi

# 3) 一次构建并直接推送多平台镜像
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t registry.example.com/myapp:1.4 \
  --push .
```

要点：

- **模拟（emulation）**：靠 QEMU 用户态翻译执行异架构指令，慢但能用，适合本地/CI 单机构建多平台。镜像层是架构相关的，所以要推到支持 OCI 的 registry（`--push`），不能只留本地。
- **原生（native）**：在真实对应架构的机器 / 节点上构建（用 `remote`/`kubernetes` driver 指到 arm 节点），速度接近原生。
- 只构建不推送时用 `docker buildx build --platform linux/arm64 .`（输出进本地 cache，不写 `docker images`，因为本机架构不匹配）。

## 缓存导出与复用

默认 BuildKit 缓存只在当前 builder 内部，机器一换就丢了。CI 里要命中的话，把缓存显式导出/导入：

```bash
# 导出到 registry（模式 max = 含中间层，可跨机复用）
docker buildx build --push \
  --cache-to   type=registry,ref=registry.example.com/myapp/cache:buildkit,mode=max \
  --cache-from type=registry,ref=registry.example.com/myapp/cache:buildkit \
  -t registry.example.com/myapp:1.4 .
```

| `type` | 说明 | 适用 |
| :-- | :-- | :-- |
| `registry` | 缓存作为隐藏镜像推到 registry | CI 跨机器、团队共享 |
| `local` | 导出到本地目录（`dest=` / `src=`） | 单机构建间复用 |
| `inline` | 嵌进镜像（仅 `mode=max` 有意义） | 简单场景，镜像体积变大 |
| `gha` | GitHub Actions 缓存后端 | GitHub CI |

`--cache-from` 的 `ref` 必须与 `--cache-to` 一致，否则命中率低。

## Bake：一仓库多镜像

`docker buildx bake` 从 `docker-bake.hcl` / `docker-bake.json` / `compose.yaml` 读取构建目标，适合 monorepo：

```hcl
# docker-bake.hcl
variable "TAG" { default = "latest" }
group "default" { targets = [ "api", "worker" ] }
target "api" {
  dockerfile = "api/Dockerfile"
  tags = ["registry.example.com/api:${TAG}"]
  platforms = [ "linux/amd64", "linux/arm64" ]
}
target "worker" {
  dockerfile = "worker/Dockerfile"
  tags = ["registry.example.com/worker:${TAG}"]
}
```

```bash
docker buildx bake --push          # 按 default group 构建并推送
docker buildx bake --set api.platform=linux/arm64   # 覆盖变量
```

Bake 的 `--jobs/-j`（0.38+）支持 `defer-error` / `defer-output` 执行模式，方便多目标并行与失败隔离。

## 镜像清单操作（imagetools）

```bash
docker buildx imagetools inspect registry.example.com/myapp:1.4   # 看 manifest list
docker buildx imagetools create \                                 # 合并多个架构 manifest
  registry.example.com/myapp:amd64 registry.example.com/myapp:arm64 \
  -t registry.example.com/myapp:1.4
```

## Docker Build Cloud（云构建）

`cloud` driver 把构建卸载到 Docker 托管的 BuildKit，缓存跨机器共享、本机无需 beefy 资源：

```bash
docker buildx build --builder cloud-<org>-default -t ... --push .
```

适合本地弱机 + 团队共享缓存的场景；注意构建上下文仍会传到云端，敏感代码需评估合规。

## 排障

- **`no builder` / driver 未就绪**：`docker buildx inspect --bootstrap` 或重建 `docker buildx create --bootstrap`。
- **多平台报 `exec format error`**：QEMU 没注册，重跑 `tonistiigi/binfmt --install all`。
- **缓存不命中**：`--cache-to` 与 `--cache-from` 的 `ref` 不一致，或没用 `mode=max`。
- **`--load` 与多平台冲突**：多平台构建不能 `--load` 到本机（`docker images`），只能 `--push` 或配合 `docker buildx imagetools`。

## Links

- [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)
- [Docker 镜像](/docs/CS/Container/Docker/image.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Docker 工具](/docs/CS/Container/Docker/tools.md)
- [BuildKit](/docs/CS/Container/Docker/buildkit.md)

## References

1. [Docker Buildx overview](https://docs.docker.com/build/buildx/)
2. [Multi-platform builds](https://docs.docker.com/build/building/multiplatform/)
3. [docker buildx bake](https://docs.docker.com/engine/reference/commandline/buildx_bake/)
4. [Buildx releases (v0.38.x)](https://github.com/docker/buildx/releases)
