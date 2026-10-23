## Introduction

A Dockerfile contains a set of instructions for how to build a Docker image. `docker build` 逐条执行这些指令，每条指令产出一个层（layer），层与层之间用缓存衔接——所以 Dockerfile 不只是"安装步骤清单"，它同时决定了**构建速度、镜像体积、缓存命中率和攻击面**。

现代构建由 BuildKit 执行（Engine 23.0 起默认），它把 Dockerfile 编译成 DAG（LLB）并行执行，并带来 cache mount、secret mount、多平台等能力。经典 builder 不支持这些特性。

## 指令速查

按用途分组，加粗的是日常最需要区分清楚的那几条：

| 分类 | 指令 | 要点 |
| :-- | :-- | :-- |
| 起点 | `FROM` | 指定基础镜像；多阶段时每个阶段一个 `FROM`，可用 `AS <name>` 命名 |
| 构建期执行 | **`RUN`** | 每条 RUN 一层；用 `&&` 串起来并在同一层清理缓存 |
| 拷贝 | **`COPY` / `ADD`** | 从构建上下文拷文件；`ADD` 额外支持自动解 tar 与下载 URL |
| 变量 | **`ARG` / `ENV`** | `ARG` 只在构建期可见，`ENV` 会带进镜像和运行时 |
| 入口 | **`CMD` / `ENTRYPOINT`** | 决定容器启动时跑什么 |
| 元数据 | `LABEL` | 镜像元信息（维护者、版本、许可证），`MAINTAINER` 已废弃 |
| 网络 | `EXPOSE` | 只是**声明**端口，不会真的发布，发布靠 `docker run -p` |
| 健康检查 | `HEALTHCHECK` | 周期性命令，让 `docker ps` 显示 healthy/unhealthy |
| 身份 | `USER` | 切换后续指令与运行时的用户 |
| 目录 | `WORKDIR` | 相当于 `cd`，不存在会自动创建；不要用 `RUN cd` |
| 存储 | `VOLUME` | 声明匿名卷挂载点；运行时用 `-v` 更灵活 |
| 信号 | `STOPSIGNAL` | 改默认 `SIGTERM`，对不接受 TERM 的程序有用 |
| 钩子 | `ONBUILD` | 被别人 `FROM` 时延迟执行，可读性差，慎用 |
| Shell | `SHELL` | 改 RUN 使用的 shell（Windows 下常用） |

### CMD vs ENTRYPOINT

| 组合 | 容器启动命令 | 典型用法 |
| :-- | :-- | :-- |
| 只有 `CMD ["nginx"]` | `nginx`，可被 `docker run image <cmd>` 整体替换 | 通用镜像，方便调试 |
| 只有 `ENTRYPOINT ["/app"]` | `/app`，`docker run image args` 的 args 变成参数 | 把镜像当可执行文件 |
| 两者都有 | `/app <CMD>`，CMD 作为默认参数 | 最灵活：固定入口 + 可覆盖参数 |

建议：用 **exec 形式**（JSON 数组），避免 shell 形式——shell 形式会起一层 `/bin/sh -c`，导致 PID 1 是 shell，信号无法直达业务进程，优雅退出会出问题。

### ARG vs ENV

- `ARG` 的值在构建结束后就消失了，`docker history` 里能看到的只是变量名
- `ENV` 会写进镜像 config，容器运行后 `env` 能看到

> [!WARNING]
> `ARG` 的值会出现在 `docker history` 的明文输出里，**不能用它传密钥**。构建期凭证请用 BuildKit 的 secret mount。

### COPY vs ADD

`ADD` 只比 `COPY` 多两件事：自动解压本地 tar、能下载 URL。Docker 官方建议**一律用 `COPY`**，除非确实需要解压——URL 下载还带来"不能走缓存、不受 `.dockerignore` 保护"的问题。

### EXPOSE vs -p

`EXPOSE 80` 只是写在镜像元数据里的声明（配合 `-P` 随机发布时用得上），真正让外部能访问的是 `docker run -p 8080:80`，见 [Docker 网络](/docs/CS/Container/Docker/net.md)。

## 构建上下文与 .dockerignore

`docker build .` 最后的那个 `.` 是**构建上下文**，CLI 会把整个目录打包发给 daemon，`COPY` 只能引用上下文内的路径。

```dockerfile
# 反例：上下文里有 .git 和 node_modules，构建先传几百 MB
COPY . .
```

`.dockerignore` 是必须写的第一个文件：

```plain
.git
.gitignore
node_modules
target
*.log
.env
**/__pycache__
Dockerfile
.dockerignore
```

把 `.env`、私钥、CI 配置挡在上下文外，是最便宜的一条安全措施。

## 缓存与指令顺序

BuildKit 按指令计算缓存 key，任一输入变化则该层及其后所有层失效。规则很简单：**变化频率低的放前面，变化频繁的放后面**。

```dockerfile
# 好：依赖层稳定，改源码只重建最后两步
COPY package.json package-lock.json ./
RUN npm ci
COPY src/ ./src/
RUN npm run build

# 坏：改一行代码就要重装全部依赖
COPY . .
RUN npm ci
```

另外要注意：

- `COPY . .` 的缓存 key 包含文件 mtime/内容，源码树一变就全失效
- `apt-get update && apt-get install` 必须写在同一条 RUN，否则 update 命中缓存后装的是旧包
- `--no-cache` 或 `docker build --no-cache` 强制全量重建
- CI 里想跨机器复用缓存，需要 cache mount 或 registry cache 导出

## 多阶段构建

编译期依赖（编译器、SDK、头文件）不应该出现在运行镜像里。多阶段是唯一干净的解决办法：

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22 AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

要点：

- 阶段可以命名（`AS builder`），`COPY --from=builder` 引用
- 也可以 `COPY --from=<image>` 直接从别的镜像拷文件
- 只拷贝需要的产物，不要 `COPY --from=builder / /`
- 最终阶段另设 `USER`，避免以 root 运行

## BuildKit 增强

docker buildx 是 BuildKit 的 CLI 前端（多平台构建、builder 实例与缓存导出的专页见 [Docker Buildx](/docs/CS/Container/Docker/buildx.md)）。下面这些能力**都需要 BuildKit**：

### 固定 frontend 版本

```dockerfile
# syntax=docker/dockerfile:1      # 跟随最新稳定 frontend
# syntax=docker/dockerfile:1.10   # 钉小版本，避免新检查规则打破构建
```

`# syntax` 让 Dockerfile 特性可以领先本地 BuildKit 版本（`--mount`、heredoc、`--link` 等都依赖它）。用 `--check` 时建议钉版本，否则新增的检查规则可能让旧构建失败。

### Cache mount

缓存目录跨构建保留，且不进最终镜像：

```dockerfile
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends build-essential
```

`sharing` 三档：`shared`（默认，pip/npm 这类内容寻址的可以并发）、`locked`（串行，apt 的 dpkg 锁不安全时用）、`private`（每次构建一份新的）。非 root 用户时必须给 `uid`/`gid`，否则写不进去、缓存静默失效。

### Secret 与 SSH mount

```dockerfile
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc,required=true \
    npm ci
RUN --mount=type=secret,id=gh_token,env=GH_TOKEN \
    gh release download v1.2.3
RUN --mount=type=ssh \
    git clone git@github.com:org/private-repo.git
```

```shell
docker buildx build \
  --secret id=npmrc,src=$HOME/.npmrc \
  --secret id=gh_token,env=GH_TOKEN \
  --ssh default \
  -t myapp .
```

secret 只在 RUN 执行期间存在于内存中，不会留在任何层里。

### 其他值得知道的特性

- **Heredoc**：`RUN <<EOF ... EOF` 写多行脚本，少一堆 `\`
- **`COPY --link`**：拷文件不依赖上一层内容，提升缓存命中
- **`ADD --checksum=sha256:...`**：下载 URL 时校验摘要（1.x labs 先行）
- **`--platform` / buildx**：构建多平台镜像，见 [Docker 镜像](/docs/CS/Container/Docker/image.md)
- **provenance**：`--provenance=true` 生成 SLSA 来源证明
- **bake**：`docker buildx bake` 用 HCL/JSON 声明多目标构建，适合 CI

## 反模式清单

| 反模式 | 问题 | 改法 |
| :-- | :-- | :-- |
| `FROM ubuntu` + 一堆 apt | 体积大、CVE 多 | 用 `-slim` / alpine / distroless |
| 多条 RUN 分别 apt update/install | 缓存串味、层膨胀 | 合并成一条并在同层清理 |
| `RUN cd /app` | 下一条指令又回到原目录 | 用 `WORKDIR /app` |
| shell 形式 CMD | PID 1 是 shell，收不到信号 | 用 exec 形式 JSON 数组 |
| `ARG` 传 token | `docker history` 明文可见 | secret mount |
| 一直用 root 跑 | 逃逸即拿 root | 最终阶段 `USER` 非 root |
| 无 HEALTHCHECK | 编排层只能靠端口判活 | 加 `HEALTHCHECK` |
| 无 `.dockerignore` | 上下文巨大、密钥泄漏 | 写 `.dockerignore` |
| `latest` tag | 无法确定部署了什么 | 钉版本号或 digest |

静态检查可用 `hadolint`，镜像逐层分析用 `dive`，见 [Docker 工具](/docs/CS/Container/Docker/tools.md)。

## Links

- [Docker Compose](/docs/CS/Container/Docker/compose.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)

## References

1. [Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
2. [BuildKit GitHub](https://github.com/moby/buildkit)
3. [BuildKit Dockerfile frontend releases](https://github.com/moby/buildkit/blob/master/frontend/dockerfile/docs/reference.md)
