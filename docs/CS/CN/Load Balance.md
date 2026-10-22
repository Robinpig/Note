## Introduction

负载均衡（Load Balancing）把涌入的流量按既定策略分摊到多台后端服务器，解决两个单点问题：**容量**（一台扛不住的总量由多台分担）与**可用性**（单台故障时流量自动绕行）。按工作层次分为 L4（传输层转发）与 L7（应用层代理）两大类，选型本质是在「转发效率」与「请求智能」之间取舍。

本页讲通用概念与算法；协议栈内的具体实现，nginx 侧见 upstream 专题、HAProxy 侧见 HAProxy 专题（见文末 Links）。

## L4

L4 LB 工作在传输层，只按 IP + 端口改写和转发报文、不解析应用层载荷，即「**转发（forward）**」。代表作是 **LVS（Linux Virtual Server）**——内核 IPVS 模块实现，LB 跑在 Linux 上，提供四种报文转发模式：

| 模式 | 报文流向 | 优点 | 缺点 |
|---|---|---|---|
| DR（直接路由） | LB 只把帧的 MAC 地址改写成目标 RS 的地址后二层转发；**目的 IP 仍是 VIP，响应由 RS 直接回给客户端** | 性能最高，响应不经过 LB | LB 与每台 RS 必须在同一个不间断的二层网段 |
| NAT（DNAT） | LB 改目的地址 + 端口发给 RS，回程再改源地址 + 端口 | 应用服务器无需任何改动 | LB 必须充当网关，所有报文都走 LB（双向经 LB 改写，容易成为吞吐瓶颈——由报文流向推出的结论） |
| TUNNEL（IP 隧道） | LB 把请求封装进 IP 隧道发给 RS，RS 解封后直接把响应回给客户端 | RS 可跨网段甚至跨地域 | RS 需支持 IP 隧道并在隧道设备上配置 VIP |
| FULLNAT（SNAT+DNAT） | LB 把 cip→lip、vip→rip 双向改写（lip/rip 均为内网地址） | 应用服务器无需改动；LB 与 RS 可处于不同 VLAN，RS 只需访问内网 | RS 看不到客户端真实 IP（需 TOA 等内核补丁补救） |

> [!NOTE]
> FULLNAT 是 LVS 的第四种模式，由淘宝的吴嘉明等人为 kernel 2.6.32 的 IPVS 编写（LVSKB 同时提醒该模块当时测试有限），keepalived/ipvsadm 随后补齐了用户态支持。

选 LVS 的理由就一条：**高性能**——调度发生在内核态，没有用户态拷贝和应用层解析开销。同思路的还有美团基于 DPDK 的 MGW，把报文转发搬进用户态快速路径。

## L7

L7 LB 工作在应用层，必须走完整 TCP/IP 栈、解析请求内容后再决定去向，即「**代理（proxy）**」。能按 URL、Header、Cookie 分流，代价是更高的单请求成本。

### Scheduling Algorithms

nginx 官方口径的算法清单：

- **加权轮询**（默认）：按 `weight` 比例轮流分配，不写任何调度指令时的默认行为
- **least_conn**：把请求发给当前活跃连接数最少的服务器（计入权重）
- **ip_hash**：按客户端 IP 哈希——取客户端 IPv4 的**前三段**或**整个 IPv6** 地址作为 key，同一客户端总是落到同一台
- **hash key [consistent]**：按自定义 key（文本、变量及其组合）哈希；带 `consistent` 时走 **ketama 一致性哈希**，增删服务器只重映射少量 key

Envoy 另支持 ring hash（ketama 一致性哈希）、**Maglev**（Google Maglev 论文的一致性哈希）、random、weighted least request（等权时是「随机二选一取空闲」的 P2C 策略）。

### Health Check

- **主动检查**：LB 周期性探测后端。Envoy 支持三类——HTTP（默认期望 **200**）、gRPC、L3/L4（TCP connect 或字节回显）。nginx 开源版**只有被动检查**（`max_fails` / `fail_timeout`），主动健康检查属 NGINX Plus 商业订阅。
- **被动检查**：Envoy 的 **outlier detection**——从真实请求中统计错误与超时，把异常实例逐出集群，不产生额外探测流量。

### Session Persistence

有状态服务需要同一客户端落到同一后端：nginx 用 `ip_hash` / `hash` / `sticky`（cookie、route、learn 三种粘法），Envoy 则用 ring hash / Maglev 等哈希类策略自然实现。

## Examples

- **Maglev**（Google）：一致性哈希 L4 负载均衡器（NSDI 2016 论文），Envoy 直接内置该调度策略
- **Katran**（Facebook）：官方描述只有一句 "A high performance layer 4 load balancer"，2018 年开源

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [upstream](/docs/CS/CN/nginx/upstream.md)
- [compare](/docs/CS/CN/nginx/compare.md)
- [HAProxy](/docs/CS/CN/Tools/HAProxy.md)
- [C10k](/docs/CS/CN/C10k.md)

## References

- [Linux Virtual Server for Scalable Network Services（VS/NAT、VS/TUN、VS/DR 工作原理）](http://www.linuxvirtualserver.org/ols/lvs.pdf)
- [LVSKB - IPVS FULLNAT and SYNPROXY](https://kb.linux-vs.org/wiki?title=IPVS_FULLNAT_and_SYNPROXY)
- [nginx - Module ngx_http_upstream_module](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
- [Envoy - Supported load balancers](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers)
- [Envoy - Health checking](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/health_checking)
- [Maglev: A Fast and Reliable Software Network Load Balancer](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/44824.pdf)
- [Katran - A high performance layer 4 load balancer](https://github.com/facebookincubator/katran)
