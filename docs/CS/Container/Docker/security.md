## Introduction

容器常被当作"轻量虚拟机"来理解，但边界完全不同：**容器与宿主机共享同一个内核**。Namespace 管的是"看得见什么"，不是"能不能碰内核"。所以 Docker 的默认隔离是"减少误伤与降低风险"，不是安全沙箱——一旦容器内进程拿到宿主 root 或触发内核漏洞，隔离就失效了。

Docker 官方的默认配置其实已经不错（默认丢弃一批 capabilities、默认 seccomp profile、默认不 privileged），绝大多数事故来自**人为放宽**：

- 挂载 `/var/run/docker.sock`
- `--privileged`
- 一直用 root 跑业务进程
- `userns-remap` 从不开，rootless 从不考虑

## 威胁模型：先搞清要防谁

| 场景 | 边界 | 需要防什么 |
| :-- | :-- | :-- |
| 跑自己的可信镜像 | 容器内是自己的代码 | 主要防程序漏洞被利用后横向移动 |
| 跑第三方镜像 | 镜像内容不可信 | 防后门、防逃逸、防供应链投毒 |
| 多租户共享宿主 | 容器之间互相不可信 | 需要 gVisor / Kata / VM 级隔离 |
| CI 里跑不可信代码 | 构建过程不可信 | 必须 VM 或沙箱运行时，普通容器不够 |

> [!WARNING]
> 挂载 `/var/run/docker.sock` 等价于把宿主机 root 交给容器：容器可以起一个新的 privileged 容器、把宿主 `/` 挂进去读写。CI 里"用 Docker 构建 Docker"请改用 BuildKit / Kaniko / rootless 方案，或至少用专用的 DinD sidecar 而非共享宿主 socket。

## 身份与权限

### 不要以 root 跑业务

```dockerfile
FROM node:22-alpine
WORKDIR /app
COPY --chown=node:node . .
USER node          # 之后所有 RUN 与容器运行时都是 node
CMD ["node", "server.js"]
```

运行时也可以覆盖：`docker run -u 10001:10001 ...`。注意非 root 无法绑 1024 以下端口，需要改监听端口或用 `--cap-add=NET_BIND_SERVICE`。

### Capabilities

root 的权能被拆成 40 多个 capability，容器默认只保留 14 个左右。原则：**全丢再按需加**。

```shell
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE nginx
```

常见该丢的：`SYS_ADMIN`（能 mount，逃逸常客）、`SYS_PTRACE`、`SYS_MODULE`（能加载内核模块）、`DAC_READ_SEARCH`（绕过文件权限）。

### 用户命名空间与 rootless

- **userns-remap**：daemon 级配置，把容器内的 root 映射到宿主上的高位 uid。代价是 volume 权限与文件属主会变复杂
- **rootless 模式**：daemon 与容器全跑在普通用户下，容器逃逸后拿到的也只是普通用户。原理与限制见 [Docker 运行时](/docs/CS/Container/Docker/runtime.md)

这是"逃逸后的天花板"问题，不是"容器之间隔离"问题。

## 内核侧的加固

| 机制 | 作用 | 用法 |
| :-- | :-- | :-- |
| seccomp | 系统调用过滤，Docker 默认 profile 禁掉约 300 个 syscall | `--security-opt seccomp=/path/profile.json`（`unconfined` 等于关掉） |
| AppArmor | Ubuntu/Debian 的 MAC，限制文件路径与操作 | `--security-opt apparmor=docker-default` |
| SELinux | RHEL 系的 MAC，靠标签控制 | `--security-opt label=type:...` |
| no-new-privileges | 禁止进程通过 setuid 提权 | `--security-opt no-new-privileges:true` |

`no-new-privileges` 成本极低、收益明确，建议默认加上。

### 只读根文件系统

```shell
docker run --read-only --tmpfs /tmp --tmpfs /run app:latest
```

进程无法写任何系统路径，攻击者的"落地"动作（写 cron、改二进制、写 SSH key）基本失效。需要写的目录用 tmpfs 或 volume 单独开。

## 镜像供应链

镜像是"别人编译好的二进制"，四件事值得做：

1. **来源可信**：优先官方镜像 / 组织内部镜像仓库，明确 digest 而非 `latest`（见 [Docker 镜像](/docs/CS/Container/Docker/image.md)）
2. **漏洞扫描**：`docker scout cves`、trivy、grype 接入 CI，按严重级别设门禁
3. **签名验签**：Docker Content Trust 已从 CLI 移除，改用 [cosign](https://github.com/sigstore/cosign)，签名以 referrer artifact 存进同一 registry（registry 的 OCI artifact 与 GC 见 [Docker Registry](/docs/CS/Container/Docker/registry.md)）
4. **来源证明**：`docker buildx build --provenance=true` 生成 SLSA provenance，回答"这个产物由哪份源码、哪次构建产生"

```shell
docker scout quickview app:v1
docker scout cves --only-severity critical,high app:v1
docker buildx build --provenance=true --sbom=true -t app:v1 --push .
```

## Secret 管理

三条硬规则：

1. **不要写进镜像**：`COPY .env` 或 `ENV PASSWORD=...` 会永久留在层里，删掉也还在历史里
2. **不要用 `ARG` 传密钥**：`docker history` 明文可见；构建期凭证用 BuildKit secret mount（见 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)）
3. **运行时用文件或 tmpfs 挂载**，而不是环境变量——环境变量会被 `docker inspect` 和子进程继承看到

```shell
docker run -d --mount type=tmpfs,dst=/run/secrets,tmpfs-size=1m \
           --mount type=bind,src=/etc/app/api.key,dst=/run/secrets/api.key,ro \
           app:latest
```

Swarm 有原生 `docker secret`（加密存储，见 [Docker Swarm](/docs/CS/Container/Docker/swarm.md)），K8s 用 Secret 资源；单机 Docker 就用上面这种文件挂载。

## 资源限额也是安全措施

不限额的容器可以靠 fork 炸弹或写满磁盘拖垮整台宿主，这属于 DoS 而非逃逸，但后果一样严重。

```shell
docker run -d --memory=512m --memory-swap=512m --cpus=1 --pids-limit=200 app:latest
```

各参数与 cgroup 的对应关系、OOM 行为见 [Docker 性能](/docs/CS/Container/Docker/performance.md)。日志无限制写满磁盘同样是常见事故，见 [Docker 存储](/docs/CS/Container/Docker/storage.md)。

## 自查清单

一份可以逐条打勾的基线：

- [ ] 业务进程以非 root 运行
- [ ] 没有 `--privileged`，没有挂载 `docker.sock`
- [ ] `--cap-drop=ALL` 起，只加必需项
- [ ] `no-new-privileges` 已开，seccomp / AppArmor 保持默认
- [ ] 根文件系统只读（能做到的服务）
- [ ] 镜像钉 digest，基础镜像定期重建
- [ ] CI 里有镜像扫描门禁
- [ ] 内存/CPU/PID 都有限额，日志有大小和份数限制
- [ ] daemon 只监听本地 socket，2375 不对外
- [ ] 定期 `docker scout` / `docker bench security`

`docker/docker-bench-security` 可以跑一遍 CIS Docker Benchmark，把上面大部分项自动化检查。

## Links

- [K8s 安全](/docs/CS/Container/k8s/acl.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Container](/docs/CS/Container/Container.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)

## References

1. [Docker security](https://docs.docker.com/engine/security/)
2. [Docker Bench for Security](https://github.com/docker/docker-bench-security)
3. [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
4. [Docker Scout](https://docs.docker.com/scout/)
