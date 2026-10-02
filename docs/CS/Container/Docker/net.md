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

## bridge 模式

在 bridge 模式下首次启动会创建一个虚拟网桥，默认名称 docker0，按照 RFC1918 模型在私有网络命名空间给网桥分配一个子网（默认 `172.17.0.0/16`）。

对每一个创建的容器都会创建一个虚拟以太网设备（[Veth 设备对](/docs/CS/OS/Linux/net/network.md)），其中一端关联到网桥上，另一端使用 [Linux 的网络命名空间](/docs/CS/OS/Linux/namespace.md) 技术映射到容器的 eth0 设备，然后在网桥的地址段内给 eth0 接口分配一个 IP 地址。

流量路径：

- **容器 → 外网**：宿主机充当 NAT 网关，iptables 的 `MASQUERADE` 规则（POSTROUTING 链）做源地址转换；
- **外网 → 容器**：`-p 8080:80` 发布端口时，DNAT 规则（DOCKER 链）把宿主机 8080 转到容器 80，这也是"容器端口映射"的底层实现。

这样做的结果是在同一台机器的容器之间可以互相通信，不同机器上的容器不能互相通信，即使它们可能在相同的网络地址范围（不同主机上的 docker0 地址段可能是一样的）。

## container 模式与 K8s

container 模式让新容器加入另一个已有容器的 Network Namespace，两个容器共享 IP 和端口空间，彼此通过 loopback 通信。**Kubernetes Pod 内的容器就是这样组织的**：所有业务容器都 `join` 到 pause 容器的 Network Namespace。区别在于，K8s 不用 docker0，而是通过 [CNI 插件](/docs/CS/Container/k8s/net.md) 完成网络配置。

## 若要实现跨主机通信

Docker 原生方案是以单机为边界的，跨主机通信主要有三条路：

1. **overlay 网络**（Swarm 的 overlay 驱动）：VXLAN 隧道封装，实现简单但有隧道开销；
2. **macvlan / 路由方案**：把容器直接接入物理网络或依赖三层路由（Calico 的思路）；
3. **放弃 Docker 网络，交给 CNI**：K8s 生态的通用做法——kubelet 创建 sandbox 时以 `none` 模式启动，随后调用 CNI 二进制完成 IP 分配和路由配置。

无论哪条路，底层都是同一套 [Linux 网络](/docs/CS/OS/Linux/net/network.md) 设施：veth pair、bridge、iptables、VXLAN。

## Links

- [Docker](/docs/CS/Container/Docker/Docker.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [Linux 网络](/docs/CS/OS/Linux/net/network.md)
- [虚拟网络设备](/docs/CS/OS/Linux/net/Virtual.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
