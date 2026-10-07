## Introduction

Alpine Linux 是**容器基础镜像的事实标准之一** —— 你见过的 `FROM alpine` 多半就是它。它和 Debian/Ubuntu 的根本区别只有一句话：**换掉了 glibc 与 GNU 用户态**。

Alpine = **musl libc** + **BusyBox** + **OpenRC** + **apk**。这四样都是嵌入式领域的产物，组合起来的结果是**一个没有 bash、没有 git、没有时区数据、只有 8 MB 的根文件系统**。

> [!WARNING]
>
> **Alpine 不是 Debian/Ubuntu 的即插即用替代品。** 为 glibc 编译的二进制（包括 most Python wheel、厂商 CLI、部分 Java/Node 生态组件）**在 Alpine 上不能直接运行**。这不是配置问题，是 libc ABI 不同。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前版本 | **Alpine 3.24.0**（2026-06-10） |
| 内核 | **6.18**（主线）/ Embedded 版本另有 5.10 与 6.6 双内核 |
| libc | **musl**（非 glibc） |
| 工具链 | **BusyBox 1.37** |
| init | **OpenRC**（非 systemd） |
| 包管理 | **apk** |
| 架构 | aarch64 / armv7 / i486 / loongarch64 / ppc64le / **riscv64** / s390x / x86 |

> **loongarch64（龙芯）与 riscv64 都在支持列表里** —— 这让它在国产化与嵌入式场景里比多数发行版覆盖更广。

## Specific Differences between musl and glibc

这是 Alpine 一切取舍的根源，也是踩坑的源头。Alpine 官方 wiki 的表述很直接：

> Musl does not implement most of the `locale` features that glibc implements. As of May 2026, work to support this is ongoing.

**locale 支持是最显著的缺口**（截至 2026-05 仍在补）。其余关键差异：

| 领域 | glibc | musl | 后果 |
| :-- | :-- | :-- | :-- |
| **DNS 解析** | 走 **NSS**（可插拔模块） | 解析器**内置**，不走 NSS | `search` 域与 `ndots` 语义不同，**busybox 工具可能解析失败而 `nslookup` 成功** |
| **动态链接** | 支持 **lazy binding** | **无 lazy binding** | 符号缺失在启动时立刻暴露，而非调用时 |
| **`dlclose()`** | 真正卸载 | **基本是 no-op** | 依赖"卸载插件释放资源"的程序行为不同 |
| **线程默认栈** | 数 MB | **128 KiB** | 假定大栈的原生代码会崩 |
| **locale** | 完整 | **缺失大部分** | 依赖 locale 的程序行为异常 |
| **glibc 符号版本** | `GLIBC_2.x` 版本化 | 无 | **glibc 二进制不能运行** |

> **128 KiB 栈是最隐蔽的杀手** —— 程序能启动（无 lazy binding 让错误提前暴露，这反而是好事），但在深递归或大栈帧时崩栈，错误信息还可能指向看似无关的地方。

### gcompat: Not a Solution

Alpine 提供 `gcompat`（glibc 兼容层），但官方定位是**给简单二进制用的部分桥接**，不是 glibc 的替代品。它能跑一部分预编译程序，但依赖完整 glibc 语义的东西仍然不行。

**判断能否用 Alpine 的实用标准**：这个镜像是否发布了 `musllinux` wheel？PEP 656 定义了 `musllinux` 平台标签，**musl 在各发行版间 ABI 兼容，但不与 glibc 构建兼容**。有 `musllinux` wheel 就没问题；只有 `manylinux`（glibc）就不行。

## Container Image: Actual Size

实测压缩体积（linux/amd64，Docker registry，2026-08）：

| 镜像 | 压缩后 |
| :-- | --: |
| `alpine:3.24` | **3.7 MiB** |
| `debian:bookworm-slim` | 26.9 MiB |
| `debian:trixie-slim` | 28.4 MiB |
| `static-debian13`（distroless） | ~2 MiB |

**但 Alpine 不是最小的**：

| 镜像 | 压缩后 | 说明 |
| :-- | --: | :-- |
| `node:22-alpine` | 55.1 MiB | vs `node:22-slim` 76.2 MiB（**只小 25%**） |
| distroless / scratch | **~2 MiB** | 只有应用 + 运行时库 |

**关键判断**：语言栈镜像的优势会**被稀释**（25% 而非 7 倍）。**目标如果是单个静态二进制，distroless 或 scratch 比 Alpine 更好** —— Kubernetes 从 v1.15 起就内置了 distroless。

Alpine 官方项目自己的说法是"一个容器不超过 8 MB"。

## Three Required Dockerfile Fixes

Alpine 镜像的"极简"是把双刃剑 —— 以下三项**必须在构建时显式补上**，否则会在事故现场才发现：

```dockerfile
FROM alpine:3.24

# ① 时区数据：Alpine 镜像不带 tzdata，日志/时间戳默认 UTC
RUN apk add --no-cache tzdata
ENV TZ=Asia/Shanghai

#    两者结果不一致 = 命中此问题
#    Test: getent hosts example.com vs nslookup example.com
#    Both Results Inconsistent = Hit This Issue

# ③ node-gyp / pip 源码编译需要构建依赖
RUN apk add --no-cache --virtual .build-deps python3 make g++ musl-dev linux-headers \
    && npm ci --omit=dev \
    && apk del .build-deps          # 用虚拟包，用完即删
```

① 的后果最隐蔽：**日志时间戳全是 UTC**，排障时对着时差猜原因。

③ 的两个具体形态：

- **node-gyp** 编译原生模块需 `python3` `make` `g++` `musl-dev`；
- **pip** 在没有对应 `musllinux` wheel 时会**从源码编译**，需 `gcc` `musl-dev` `linux-headers`。

## Kernel Mechanism Association

Alpine 在容器里的特殊性：

- **容器不自带内核** —— Alpine 镜像只带用户态，内核由宿主提供。所以"Alpine 的内核 6.18"指的是它**作为宿主系统**时的内核，容器里跑时内核版本由宿主决定。
- **cgroup v2 与 namespace** 由宿主内核提供，见 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md) 与 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **CPU 基线（x86-64-v3）** —— Alpine 默认 v1 基线（与 Debian/Ubuntu/Fedora 一致），这在老 CPU 上反而是优势，见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md) 的微架构级别对照表。

## OpenRC instead of systemd

Alpine 用 **OpenRC** 做 init，服务管理语法与 systemd 完全不同：

```shell
rc-update add <service> default      # 启用服务（相当于 systemctl enable）
rc-update del <service> default      # 禁用
rc-service <service> start|stop|restart|status
rc-status                            # 看整体状态
rc-update show                       # 列出各 runlevel
```

runlevel 概念（`default`、`boot`、`sysinit` 等）继承自 BSD，与 systemd 的 target 不是一一对应。**从 Debian/Ubuntu 迁到 Alpine（或反过来）时，这套要重新学**。

## Why Alpine Is Suitable for Containers

| 优势 | 机制 |
| :-- | :-- |
| 体积小 | musl + BusyBox，无 bash/git/文档 |
| 攻击面小 | 包管理器只有 `apk`，无 dpkg/rpm 的复杂依赖解析 |
| 启动快 | 少量进程、OpenRC 比 systemd 轻 |
| **无 setuid 程序** | 官方说法：默认配置阻止 setuid 程序提权 |

> **最后一条常被误解**：`qemu-binfmt` 服务从 3.24 起被弃用，官方给出的原因正是 **"新默认配置阻止 setuid 程序授予权限"** —— 这被解读为一个安全改进。想执行 setuid 的外来架构二进制，需复制 `/usr/lib/binfmt.d/qemu-*.conf` 手动加 `C` flag。**这是一个刻意的取舍，不是配置疏漏。**

## Troubleshooting Quick Reference

```shell
# libc 到底是 musl 还是 glibc
ldd /bin/sh 2>&1 | head -2        # musl 输出格式不同
ls /lib/ld-musl-*                 # 有则是 musl
apk info musl

# 静态链接检查（判断镜像能否换 Alpine）
file /app/myapp
ldd /app/myapp                    # "not a dynamic executable" = 可移植

# DNS 问题诊断（musl 的头号坑）
getent hosts example.com          # 走 musl 解析器
nslookup example.com              # 走别的路径
# 两者结果不一致 = 命中 musl NNS 差异
cat /etc/resolv.conf              # search 与 ndots 配置

# 时区
ls /usr/share/zoneinfo/            # 空 = 缺 tzdata
date                              # 没装 tzdata 就是 UTC
apk add tzdata

# locale
locale                            # 看可用 locale
apk add musl-locales               # 补 musl 的 locale 数据
locale -a

# 栈大小（128KiB 限制）
ulimit -s                         # 默认 8192 KB = 8 MiB? 实际 musl pthread 默认不同
# pthread 默认栈：glibc 8MB / musl 128KB

# 服务管理（OpenRC，非 systemd）
rc-status
rc-service <svc> status
rc-update show
ls /etc/init.d/ /etc/conf.d/      # OpenRC 的配置目录

# 包与仓库
cat /etc/apk/repositories
apk update
apk add --no-cache <pkg>          # --no-cache 不留索引，省空间
apk info -a <pkg>

# 静态链接构建（交叉编译最佳实践）
apk add musl-dev                   # 本机编译
musl-gcc --version
```

## Interfaces with Other Subsystems

- 容器与 cgroup v2 / namespace 的关系，见 [Container](/docs/CS/Container/Container.md) 与 [cgroup](/docs/CS/OS/Linux/cgroup/README.md)。
- CPU 微架构基线（Alpine 用 v1，老 CPU 友好），见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)。
- OpenRC vs systemd 的 unit 语义差异（`Type=` 等概念不存在），见 [systemd](/docs/CS/OS/Linux/Tools/systemd.md)。
- 其它独立系发行版见 [NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md)（声明式）与 [Arch](/docs/CS/OS/Linux/Distribution/Arch.md)（滚动 KISS）。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)
- [Container 知识地图](/docs/CS/Container/README.md)
- [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)
- [systemd（OpenRC 的对照）](/docs/CS/OS/Linux/Tools/systemd.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Alpine Linux 官网](https://alpinelinux.org/)
2. [Alpine 3.24.0 Release Notes](https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.24.0)
3. [Alpine Wiki — Musl](https://wiki.alpinelinux.org/wiki/Musl)
4. [musl libc 官网](https://musl.libc.org/)
5. [PEP 656 — musllinux platform tag](https://peps.python.org/pep-0656/)
6. [Alpine for Production Containers: Pros, Cons, and Tradeoffs](https://goranstimac.com/blog/alpine-linux-production-containers-pros-cons-tradeoffs)
