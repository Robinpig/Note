## Introduction

标准的 Docker 支持以下网络模式：

| 模式 | 指定方式 | 原理 | 典型场景 |
|------|---------|------|---------|
| bridge | `--network=bridge`（默认） | veth pair + docker0 网桥 + iptables NAT | 单机容器互通 |
| host | `--network=host` | 直接共享宿主机 Network Namespace | 追求网络性能、监听固定端口的守护进程 |
| container | `--network=container:NAME_or_ID` | 加入另一个容器的 Network Namespace | Kubernetes Pod 的实现基础 |
| none | `--network=none` | 只有 lo，不做任何网络配置 | 交给 CNI 等外部工具接管 |
| overlay | `docker network create -d overlay` | VXLAN 隧道跨主机组网 | Docker Swarm 跨主机通信 |
| macvlan | `--network=macvlan` | 容器直接获得物理网络 MAC/IP | 需要容器以"物理机"身份入网 |

## bridge Mode

在 bridge 模式下首次启动会创建一个虚拟网桥，默认名称 docker0，按照 RFC1918 模型在私有网络命名空间给网桥分配一个子网（默认 `172.17.0.0/16`）。

对每一个创建的容器都会创建一个虚拟以太网设备（[Veth 设备对](/docs/CS/OS/Linux/net/network.md)），其中一端关联到网桥上，另一端使用 [Linux 的网络命名空间](/docs/CS/OS/Linux/namespace.md) 技术映射到容器的 eth0 设备，然后在网桥的地址段内给 eth0 接口分配一个 IP 地址。

流量路径：

- **容器 → 外网**：宿主机充当 NAT 网关，iptables 的 `MASQUERADE` 规则（POSTROUTING 链）做源地址转换；
- **外网 → 容器**：`-p 8080:80` 发布端口时，DNAT 规则（DOCKER 链）把宿主机 8080 转到容器 80，这也是"容器端口映射"的底层实现。

这样做的结果是在同一台机器的容器之间可以互相通信，不同机器上的容器不能互相通信，即使它们可能在相同的网络地址范围（不同主机上的 docker0 地址段可能是一样的）。

### 端口发布与 userland-proxy

`-p 8080:80` 的完整语义可以写成 `-p <宿主IP>:<宿主端口>:<容器端口>/<协议>`：

```shell
docker run -d -p 8080:80 nginx                 # 宿主所有 IP 的 8080
docker run -d -p 127.0.0.1:8080:80 nginx       # 只监听本机，外部访问不到
docker run -d -p 8080:80/udp dns-server
docker run -d -P nginx                         # 按 EXPOSE 声明随机发布
```

端口转发早期由一个用户态进程 `docker-proxy` 承担（每条映射一个进程，开销不小）。现在默认走 iptables DNAT，只有需要 IPv6 或老内核时才回落到 userland-proxy。可以用 `daemon.json` 的 `"userland-proxy": false` 关掉它，代价是 `localhost` 访问容器端口的行为会变化（hairpin 流量不再经过用户态转发）。

### 自定义 bridge 与内嵌 DNS

默认的 `bridge` 网络有个历史包袱：容器之间不能用名字互访，只能靠 `--link`（已废弃）。**自建网络**则自带 DNS 发现：

```shell
docker network create appnet
docker run -d --name db --network appnet postgres:17
docker run -d --name api --network appnet app:v1   # api 里能 ping db
```

Docker 在每个容器里起一个内嵌 DNS 服务器（`/etc/resolv.conf` 里是 `127.0.0.11`），负责解析同网络内的容器名和 service 名；外部域名则转发给宿主机配置的 DNS。注意它是**按网络隔离**的：不同网络的容器互相解析不到名字。

其他值得知道的行为：

- 一个容器可以加入多个网络：`docker network connect appnet web`
- `--network-alias` 可以给容器起额外的 DNS 名
- 容器的 `/etc/hosts`、`resolv.conf`、`hostname` 由 Docker 在 Init 层注入，镜像里改这些文件会被覆盖

## host / none 模式

- **host**：容器直接共享宿主 Network Namespace，没有 veth、没有 NAT、没有端口映射，`-p` 会失效，容器监听什么端口宿主就占什么端口。省掉一层转发，网络性能最好，代价是**端口空间与宿主冲突**，且网络隔离消失
- **none**：只有 loopback，容器完全断网。K8s 生态里 kubelet 就是以 `none` 模式起 sandbox，再交给 [CNI](/docs/CS/Container/k8s/net.md) 插件配网

## container Mode and K8s

container 模式让新容器加入另一个已有容器的 Network Namespace，两个容器共享 IP 和端口空间，彼此通过 loopback 通信。**Kubernetes Pod 内的容器就是这样组织的**：所有业务容器都 `join` 到 pause 容器的 Network Namespace。区别在于，K8s 不用 docker0，而是通过 [CNI 插件](/docs/CS/Container/k8s/net.md) 完成网络配置。

## To Achieve Cross-host Communication

Docker 原生方案是以单机为边界的，跨主机通信主要有三条路：

1. **overlay 网络**（Swarm 的 overlay 驱动）：VXLAN 隧道封装，实现简单但有隧道开销；
2. **macvlan / 路由方案**：把容器直接接入物理网络或依赖三层路由（Calico 的思路）；
3. **放弃 Docker 网络，交给 CNI**：K8s 生态的通用做法——kubelet 创建 sandbox 时以 `none` 模式启动，随后调用 CNI 二进制完成 IP 分配和路由配置。

macvlan 的特点是容器拿到物理网段的真实 MAC 和 IP，在局域网里等同于一台独立机器（适合跑需要被外部直接访问的 legacy 服务），但宿主与容器之间默认不能互通（需要再加一个 macvlan 子接口）。

无论哪条路，底层都是同一套 [Linux 网络](/docs/CS/OS/Linux/net/network.md) 设施：veth pair、bridge、iptables、VXLAN。

## libnetwork 与防火墙后端

网络由 libnetwork 实现，driver 分两类：

- **内置**：bridge、host、none、overlay、ipvlan、macvlan
- **remote**：第三方插件（如各类 SDN 方案）通过 HTTP API 接入

iptables 规则由 daemon 在容器启停时动态下发，常见链：`DOCKER`、`DOCKER-ISOLATION-STAGE-1/2`（隔离不同网络）、`DOCKER-USER`（**给用户预留的自定义链**，规则优先级最高）。

Engine 29 起提供**实验性的 nftables 后端**（`"firewall-backend": "nftables"`），用于替代逐步被各发行版弃用的 iptables legacy。相关变化也在持续修（如 firewalld zone 相关的 bridge 恢复问题）。

> [!NOTE]
> 如果 daemon 重启后容器之间突然不通，先看是不是 firewalld/ufw 重启把 DOCKER 链冲掉了。生产环境建议把自定义规则写在 `DOCKER-USER` 链里，而不是直接改 `FORWARD`。

## 网络的日常操作

```shell
docker network ls
docker network create --driver bridge --subnet 172.28.0.0/16 appnet
docker network inspect appnet
docker network connect appnet web
docker network disconnect appnet web
docker network prune
docker run -d --network appnet --network-alias api1 app:v1
```

## 排障

容器"访问不通"时按网络栈从内到外查：

```shell
# 1. 容器自己的 IP、网关、DNS
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{.Gateway}}{{end}}' web
docker exec web cat /etc/resolv.conf

# 2. 进容器的网络 namespace 看端口与连接（宿主工具直接用）
PID=$(docker inspect -f '{{.State.Pid}}' web)
nsenter -t $PID -n ss -lntp
nsenter -t $PID -n ip addr

# 3. 宿主上的 NAT 规则
iptables -t nat -L DOCKER -n -v
iptables -L DOCKER-USER -n -v

# 4. 抓包定位到底丢在哪一跳
nsenter -t $PID -n tcpdump -i eth0 -nn port 80
```

要点：

- 容器内 `curl localhost` 通不通，取决于服务监听的是 `127.0.0.1` 还是 `0.0.0.0`——容器里的 localhost 是容器自己
- 宿主访问容器要用**映射后的宿主端口**或容器 IP，不是 `localhost`（除非用了 host 模式）
- DNS 解析失败先查 `/etc/resolv.conf` 的 `127.0.0.11`，再查宿主 DNS 是否可达
- 从 PID 到 namespace 的完整换算见 [容器定位](/docs/CS/Container/locate.md)

## Links

- [Docker Compose](/docs/CS/Container/Docker/compose.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [虚拟网络设备](/docs/CS/OS/Linux/net/Virtual.md)

## References

1. [Docker network drivers](https://docs.docker.com/engine/network/drivers/)
2. [Container networking](https://docs.docker.com/engine/network/)
3. [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
