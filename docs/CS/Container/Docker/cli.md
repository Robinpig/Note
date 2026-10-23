## Introduction

Docker 的命令可以按"你在解决什么问题"来记，而不是按字母表背。本文是速查与套路合集，原理归各分册：[镜像](/docs/CS/Container/Docker/image.md)、[存储](/docs/CS/Container/Docker/storage.md)、[网络](/docs/CS/Container/Docker/net.md)、[性能](/docs/CS/Container/Docker/performance.md)。

## 生命周期

容器创建、停止、重启、删除的命令见此；背后的 PID 1、信号转发与优雅终止机制见 [容器生命周期](/docs/CS/Container/Docker/lifecycle.md)。

```shell
docker run -d --name web -p 8080:80 --restart unless-stopped nginx:1.27-alpine
docker run -it --rm ubuntu:24.04 bash        # 交互式，退出即删
docker run -d --memory=512m --cpus=1.5 app   # 带资源限额
docker start|stop|restart web
docker pause|unpause web                     # cgroup freezer，进程还在
docker rm -f web
docker update --memory=1g --restart=always web   # 改运行中容器的配置
```

`docker run` 最常一起出现的参数：

| 参数 | 作用 |
| :-- | :-- |
| `-d` | 后台运行 |
| `--name` | 指定名字，后续命令可以用名字代替 ID |
| `-p host:container` | 发布端口 |
| `-v / --mount` | 挂载数据 |
| `--network` | 指定网络模式 |
| `-e KEY=VALUE` | 环境变量 |
| `--restart` | 重启策略 |
| `--rm` | 停止后自动删除 |
| `-it` | 分配交互终端（调试必备） |
| `--entrypoint` | 覆盖镜像入口 |

## 查看与过滤

```shell
docker ps -a                          # 含已停止
docker ps -s                          # 带磁盘占用
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker ps -q                          # 只要 ID，便于管道
docker ps -f "status=exited" -f "name=web"
docker logs -f --tail 200 --since 10m web   # 日志驱动与轮转见 [Docker 日志](/docs/CS/Container/Docker/logging.md)
docker top web                        # 容器内进程
docker port web                       # 端口映射
docker diff web                       # 相对镜像改了哪些文件
docker stats                          # 实时资源占用
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

`--filter` 支持 `status`、`name`、`label`、`ancestor`（按镜像）、`network`、`volume` 等，批量操作时先 `-q` 再 `xargs`：

```shell
docker rm -f $(docker ps -aq -f "status=exited")
```

## inspect 与 Go template

`docker inspect` 输出的是 daemon 视角的完整状态 JSON，几乎所有"这个容器到底是怎么起的"的问题都能在这里找答案：

```shell
docker inspect web
docker inspect -f '{{.State.Pid}}' web                 # 宿主机上的 PID 1
docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' web
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web
docker inspect -f '{{json .HostConfig}}' web | jq .     # 启动参数全貌
docker inspect -f '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' web
```

几个高频字段：

| 字段 | 内容 |
| :-- | :-- |
| `.State.{Status,Running,Pid,ExitCode,StartedAt}` | 运行状态 |
| `.Config.{Env,Cmd,Entrypoint,ExposedPorts,Labels}` | 镜像 + 启动时的配置 |
| `.HostConfig.{Binds,PortBindings,RestartPolicy,Privileged,NanoCpus,Memory}` | `docker run` 那些参数 |
| `.NetworkSettings.{Networks,Ports}` | 网络与端口 |
| `.Mounts` | 挂载明细 |

从 PID 反查容器、或从容器定位到宿主机进程，见 [容器定位](/docs/CS/Container/locate.md)。

## 进入容器

```shell
docker exec -it web sh                 # 大多数精简镜像没有 bash
docker exec -it -u root web sh         # 以 root 进入
docker exec -it -e DEBUG=1 web sh      # 带环境变量
docker exec web cat /etc/os-release    # 非交互执行单条命令
docker cp ./file web:/tmp/file         # 拷进去
docker cp web:/tmp/file ./file         # 拷出来
docker attach web                      # 接上主进程 stdio（Ctrl-C 会杀容器，慎用）
```

`docker exec` 是**新起一个进程**加进已有 namespace，所以它不受容器 cgroup 之外的限制，也不影响 PID 1；`docker attach` 是接主进程的 stdio，退出姿势不对会连带停掉容器。

## 镜像侧命令

```shell
docker images
docker pull nginx:1.27-alpine
docker tag app:latest registry.example.com/app:v1.2.3
docker push registry.example.com/app:v1.2.3
docker history --no-trunc nginx:1.27-alpine
docker save app:v1 | gzip > app.tgz && docker load < app.tgz
docker rmi $(docker images -q -f "dangling=true")
```

构建相关（BuildKit / buildx）见 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)：

```shell
docker build -t app:v1 .
docker buildx build --platform linux/amd64,linux/arm64 --push -t app:v1 .
docker buildx bake -f docker-bake.hcl
```

## 排查一条龙

容器起不来或行为异常时，按这个顺序走：

```shell
# 1. 先看在不在、状态是什么
docker ps -a | grep web

# 2. 看日志（ExitCode 非 0 时尤其重要）
docker logs --tail 100 web

# 3. 看 daemon 视角的最终配置，确认参数是不是你以为的
docker inspect -f '{{json .HostConfig}}' web | jq .

# 4. 起不来就换个入口进去看
docker run -it --rm --entrypoint sh app:v1

# 5. 起来了但不健康：看健康检查和实时资源
docker inspect -f '{{json .State.Health}}' web | jq .
docker stats web

# 6. 资源类问题下钻到宿主机
docker inspect -f '{{.State.Pid}}' web        # 拿到 PID
cat /proc/<pid>/cgroup                        # 看 cgroup 归属
nsenter -t <pid> -n ss -lntp                  # 进网络 namespace 看端口
```

第 6 步的完整方法论见 [容器定位](/docs/CS/Container/locate.md)，性能瓶颈见 [Docker 性能](/docs/CS/Container/Docker/performance.md)。

## 系统级

```shell
docker version                 # client + server 版本
docker info                    # 驱动、cgroup 版本、安全选项、存储占用
docker system df -v            # 分项磁盘占用
docker system events --since 1h   # daemon 事件流（谁被 kill/oom 了）
docker system prune            # 清理（见存储分册，别乱加 --volumes）
```

`docker system events` 是查"容器什么时候、被谁、为什么停掉"的利器，配合 `--filter 'type=container'` 与 `--filter 'event=die'` 使用。

## 顺手可用的别名

```shell
alias dps='docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"'
alias dip='docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"'
alias dpid='docker inspect -f "{{.State.Pid}}"'
alias dlog='docker logs -f --tail 100'
alias dex='docker exec -it'
alias dprune='docker system prune -f'
```

## Links

- [Docker Compose](/docs/CS/Container/Docker/compose.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)

## References

1. [Docker CLI reference](https://docs.docker.com/reference/cli/docker/)
2. [docker inspect examples](https://docs.docker.com/reference/cli/docker/inspect/)
