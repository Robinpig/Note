# 升级与版本偏移（Upgrade & Version Skew）

Kubernetes 不支持组件的任意版本组合，也不支持跨小版本（minor）直接升级。集群要长期处在安全补丁窗口内，必须同时理解两条规则：**Version Skew Policy（各组件允许的最大版本差）** 与 **Upgrade Order（升级顺序，控制平面先、禁止跳版本）**。本文是升级与版本偏移的归属分册；集群排障见 [Issues](/docs/CS/Container/k8s/Issues.md)，etcd 存储与快照见 [etcd](/docs/CS/Container/k8s/etcd.md)，节点代理见 [kubelet](/docs/CS/Container/k8s/kubelet.md)。

## 为什么存在版本偏移

控制平面必须对**更旧**的 kubelet 保持向后兼容：apiserver 仍理解旧 kubelet 的请求与对象编码，所以 kubelet 可以落后几个小版本。但 apiserver **不向前兼容**新 kubelet——一个 N+1 的 kubelet 可能使用 N 尚未支持的特性或编码，向 N 的 apiserver 发请求会失败，甚至让节点失联。因此所有偏移规则都指向同一方向：**下层组件（kubelet / kube-proxy）只能比 apiserver 旧，不能更新**。

偏移窗口（kubelet 3 个、kube-proxy 3 个）本身是为「一次只升一个小版本」预留的过渡期，而不是让你长期运行大跨度混合版本。

## Version Skew Policy

下表为官方支持的最大偏移（以 apiserver 为 1.N 为例；组件历史上 < 1.25 只允许多旧 2 个，后续放宽到 3 个）：

| 组件对 | 偏移规则 | 示例（apiserver = 1.37） |
|--------|----------|--------------------------|
| HA 内多 apiserver 实例 | 最新与最旧相差 ≤ 1 小版本 | 1.37 + 1.36 |
| kubelet vs apiserver | 不得更新；最多旧 3 小版本 | 1.37 / 1.36 / 1.35 / 1.34 |
| kube-proxy vs apiserver | 不得更新；最多旧 3 小版本 | 1.37 / 1.36 / 1.35 / 1.34 |
| kube-proxy vs 同节点 kubelet | 可旧可新 ±3（但通常被 apiserver 主约束收紧） | 见上两行取交集 |
| controller-manager / scheduler / cloud-controller-manager vs apiserver | 不得更新；最多旧 1 小版本 | 1.37 / 1.36 |
| kubectl vs apiserver | ±1 小版本（可旧可新） | 1.38 / 1.37 / 1.36 |
| etcd vs apiserver | 版本随 K8s 小版本绑定，查当版 release notes | 1.37 → etcd 3.x（见当版 release notes） |

注意 HA 内若 apiserver 实例之间存在偏移，会把允许的下层版本范围**收窄**：例如实例为 1.37 与 1.36 时，kubelet 只能取 1.36 / 1.35 / 1.34（不能取 1.37，因为那比 1.36 实例更新），kube-proxy 同理。

## 支持窗口（Supported Releases）

- 项目同时维护**最近 3 个小版本**的发布分支（2026-10 为 1.37、1.36、1.35）。
- 1.19 起每个 minor 约 **1 年**的 patch 支持（安全与关键修复回灌到这 3 个分支）。
- 1 年约对应 3 个 minor（每年发 3 个），所以「至少每年升一次」才能停在支持窗口内。
- 托管服务（EKS / AKS / GKE）有自己的支持日历，可能比上游更紧或不同，须以 provider 文档为准。

## 升级顺序（Upgrade Order）

跨小版本升级必须**逐个小版本**（1.N → 1.N+1），且严格「控制平面先、工作节点后」：

1. 备份 etcd（[etcd](/docs/CS/Container/k8s/etcd.md) 快照）。
2. 第一个控制平面节点：`kubeadm upgrade apply v1.N+1.0`。
3. 其余控制平面节点：`kubeadm upgrade node`。
4. 控制平面组件（controller-manager / scheduler / cloud-controller-manager）随之上到 1.N+1。
5. 插件（kube-proxy、CoreDNS）推到新版本。
6. 工作节点逐个：`kubectl drain` → `kubeadm upgrade node` → 升 kubelet / kubectl → `systemctl restart kubelet` → `kubectl uncordon`。
7. 每步用 `kubectl get nodes` / `kubectl get pods -A` 验证健康后再动下一个。

**永远不要先升 kubelet 再升 apiserver**——会违反 skew 规则让节点失联。

## 为什么不能跳版本

- 每个 minor 可能**移除上一版已弃用的 API**（API deprecation policy 给 2 个 release 的预告，但仍需逐个过渡）。跨版本直接跳会撞上 apiserver 已不再服务的 API 版本，导致 workload 无法创建或更新。
- 存储版本与数据编码迁移可能是**单向**的：对象一旦迁移到新存储编码，旧二进制可能无法正确读回，因此**跨小版本降级不被支持**（etcd 快照是唯一回滚路径）。
- 发布节奏约每 4 个月一个 minor、维护窗口约 14 个月，跳过会让版本偏离快速超出 N-2 窗口。

## kubeadm 实操要点

- 升级前把包仓库指到目标 minor（pkgs.k8s.io 按 minor 分仓，否则 apt 看不到新版本）。
- `kubeadm upgrade plan` 会做 skew 预检并展示将变更项。
- **etcd 升级注意**：apiserver 是常驻静态 Pod，kubeadm 升级内含 etcd 升级时，etcd 重启会让在途请求 stall。官方 workaround 是先在控制平面 `killall -s SIGTERM kube-apiserver` 优雅关闭，sleep 约 20s 让在途请求完成，再跑 `kubeadm upgrade apply`。
- 升级后所有容器因 spec hash 变化而重启，属预期行为。
- `kubeadm upgrade` 不支持对已有集群 reconfigure；改配置需走 Reconfiguring 流程。
- 推荐 kubelet 与 kubeadm 版本匹配；kubelet 可略旧，只要在 skew 范围内。

## Managed vs Self-managed

| 职责 | 托管（EKS / AKS / GKE） | 自建（kubeadm） |
|------|------------------------|-----------------|
| 控制平面升级 | provider（按钮 / API） | operator（kubeadm upgrade） |
| 工作节点升级 | provider（托管节点组）或 operator | operator |
| 节点 OS 补丁 | provider（托管节点组） | operator |
| 版本选择 | 受限（provider 支持列表） | 任意 |

托管集群把控制平面升级自动化、工作节点交给托管节点组，窗口通常更短但灵活性更低；自建集群每一步都由 operator 执行，负担更重但版本选择完全自由。

## 升级前检查清单

- 用 pluto / kubent 或 apiserver 的 `apiserver_requested_deprecated_apis` 指标，确认没有 workload 仍在用目标版本已移除的 API。
- `etcdctl snapshot save` 先打快照（唯一回滚手段）。
- 读路径上每个版本的 release notes（deprecated / removed API、行为变更）。
- 校验 CNI / CSI / Ingress Controller / cert-manager 等插件对目标版本的兼容矩阵。
- 先在 staging 集群跑一遍升级再上生产。

## Links

- [Issues](/docs/CS/Container/k8s/Issues.md)
- [etcd](/docs/CS/Container/k8s/etcd.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

- [Version Skew Policy（官方）](https://kubernetes.io/docs/setup/release/version-skew-policy/)
- [Upgrading kubeadm clusters（官方）](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade)
- [Kubernetes Releases](https://kubernetes.io/docs/setup/release/)
