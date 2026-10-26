## Introduction

By default all files created inside a container are stored on a writable container layer. 这带来三个问题：

- The data doesn't persist when that container no longer exists，且很难被别的进程取出来
- 可写层与宿主机强耦合，无法随容器迁移
- Writing into a container's writable layer requires a storage driver to manage the filesystem（联合挂载），相比直接写宿主机文件系统多一层抽象，性能更差

Docker 给容器持久化提供了三种挂载方式：**volumes**、**bind mounts**、**tmpfs**——它们解决的是"数据放哪"的问题；而 storage driver（overlay2 / containerd snapshotter）解决的是"镜像层怎么叠"的问题。两者经常被人混为一谈，其实完全不是一层东西。

```plain
容器看到的视图（由下往上）
┌─────────────────────────────────┐
│ 容器可写层（CoW）                │  ← 容器删了就没了
├─────────────────────────────────┤
│ Init 层（/etc/hosts、resolv.conf）│  ← Docker 临时注入
├─────────────────────────────────┤
│ 镜像只读层 N ... 1               │  ← 来自 [Docker 镜像](/docs/CS/Container/Docker/image.md)
└─────────────────────────────────┘
   ↑ volume / bind mount 会直接"盖"在某个路径上，绕过 CoW
```

## 三种挂载方式

An easy way to visualize the difference among volumes, bind mounts, and `tmpfs` mounts is to think about where the data lives on the Docker host。

| 方式 | 数据落在哪 | 生命周期 | 典型场景 |
| :-- | :-- | :-- | :-- |
| volume | 宿主机上由 Docker 管理的区域（Linux 下 `/var/lib/docker/volumes/`） | 独立于容器，`docker volume rm` 才删 | 数据库数据、需要备份/迁移的有状态服务 |
| bind mount | 宿主机任意路径 | 与宿主机文件同生共死 | 挂载源码热更新、共享配置文件、读 `/proc` 之类 |
| tmpfs | 只存在于宿主机内存 | 容器停止即消失 | 密钥、session、不需要落盘的临时文件 |

No matter which type of mount you choose, the data looks the same from within the container——都是容器文件系统里的一个目录或文件。

```shell
# 具名 volume（推荐）
docker run -d -v dbdata:/var/lib/postgresql/data postgres:17

# 匿名 volume（Docker 随机命名，容器删了容易变孤儿）
docker run -d -v /var/lib/postgresql/data postgres:17

# bind mount
docker run -d -v "$PWD/conf:/etc/nginx/conf.d:ro" nginx

# --mount 语法（更显式，支持更多选项）
docker run -d --mount type=volume,src=dbdata,dst=/data \
           --mount type=tmpfs,dst=/run/secrets,tmpfs-size=16m app:latest
```

### 该选哪个

- **持久化数据一律用 volume**：Docker 管理、有 API、可备份、可跨容器共享，且不需要关心宿主机目录权限
- **开发期挂载代码用 bind mount**：改文件立即生效，比重建镜像快
- **密钥与临时文件用 tmpfs**：不落盘、不进镜像层，见 [Docker 安全](/docs/CS/Container/Docker/security.md)
- 挂载 **单个文件**（如 `nginx.conf`）时，某些编辑器用"删除+新建"保存会导致 inode 变化、挂载失效，这是 bind mount 的经典坑

## Volume 的日常操作

```shell
docker volume create dbdata
docker volume ls
docker volume inspect dbdata          # 看真实路径 Mountpoint
docker volume rm dbdata
docker volume prune                   # 清理未被任何容器引用的卷
```

备份与迁移的标准姿势是"用第三方容器挂载同一个卷"：

```shell
# 备份
docker run --rm -v dbdata:/data -v "$PWD":/backup alpine \
  tar czf /backup/dbdata.tgz -C /data .

# 恢复
docker run --rm -v dbdata:/data -v "$PWD":/backup alpine \
  tar xzf /backup/dbdata.tgz -C /data
```

注意：不要把宿主机进程直接写进 `/var/lib/docker/volumes/`——这块区域归 Docker 管，非 Docker 进程改它可能导致权限和 SELinux 标签错乱。

## Storage Driver 与 snapshotter

storage driver 负责把镜像的多个只读层和容器可写层联合挂载成一个目录视图。

- **overlay2**（长期默认）：基于内核 [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md)，把镜像层设为 `lowerdir`、容器可写层设为 `upperdir`
- **containerd snapshotter**：Engine 29 起**新装环境的默认 image store** 走 containerd 的 content store + snapshotter，传统 graph driver 转为 deprecated，未来会移除

这次切换带来的变化：

| 维度 | graph driver（overlay2） | containerd image store |
| :-- | :-- | :-- |
| 层管理 | graphdriver 自己管 | containerd content store + snapshotter |
| 生态对齐 | Docker 独有 | 与 [containerd](/docs/CS/Container/k8s/containerd.md)、K8s 一致 |
| 新能力 | 无 | 多 snapshotter、lazy pulling（nydus/stargz/soci） |
| 迁移 | 老安装不受影响 | 新装默认，可显式退出 |

Engine 29.9.0 起 lazy pulling 对 nydus / overlaybd / soci / stargz 默认开启——大镜像可以先起容器、按需拉取层，冷启动明显变快。

驱动选择（`docker info | grep -A5 "Storage Driver"`）一般不用改，但要留意：

- `vfs` 是"每个层一个完整目录"，只用于测试，性能极差
- `devicemapper`、`aufs` 属于历史遗留
- Windows / macOS 上的 Docker Desktop 跑在 VM 里，性能瓶颈往往是虚拟化层的文件共享而非驱动本身

## 写时复制的性能陷阱

CoW 在"小文件多、读多写少"的场景很划算，但也有明确的代价：

1. **改大文件要整份上浮**：第一次写 2GB 的文件会复制 2GB 到可写层
2. **删除不减体积**：删文件只是写 whiteout，底层块还在
3. **层层叠加的查找开销**：层数越多，路径解析越慢，建议控制在十几层以内
4. **数据库类负载**：高 IOPS + 大文件随机写，直接放 volume 走宿主机文件系统，别走容器可写层

验证容器到底占了多少空间：

```shell
docker ps -s              # 每容器的 size（可写层）与 virtual size（含镜像）
docker system df -v       # 镜像/容器/卷/构建缓存分项占用
```

## 日志也是磁盘杀手

默认日志驱动是 `json-file`，**没有大小限制**。一个疯狂打印的容器可以把宿主磁盘写满，进而拖垮整台机器（Docker daemon 也会异常）。

`daemon.json` 里必须设限：

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

或者按容器指定：`docker run --log-opt max-size=10m --log-opt max-file=3 ...`。高吞吐场景可换 `local`（紧凑二进制格式）或 `journald`/`fluentd` 交给外部日志系统（驱动全目录、轮转与 dual logging 详见 [Docker 日志](/docs/CS/Container/Docker/logging.md)）。

## 清理

```shell
docker container prune     # 已停止的容器
docker image prune -a      # 未被任何容器引用的镜像（含 dangling）
docker volume prune        # 未被引用的卷
docker network prune       # 未被引用的网络
docker builder prune       # 构建缓存
docker system prune -a --volumes   # 一次全清（危险：会删卷）
```

> [!WARNING]
> `docker system prune -a --volumes` 会删除**所有未被运行中容器引用的卷**，包括数据库数据卷。执行前先 `docker volume ls` 确认，生产环境不要随手跑。

## Links

- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker 性能](/docs/CS/Container/Docker/performance.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [K8s 存储](/docs/CS/Container/k8s/Storage.md)

## References

1. [Manage data in Docker](https://docs.docker.com/engine/storage/)
2. [Storage drivers](https://docs.docker.com/engine/storage/drivers/)
3. [containerd image store](https://docs.docker.com/engine/storage/containerd/)
