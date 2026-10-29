## Introduction

K8s 里"发生了什么"有两套互补的记录，常被混为一谈：**Events**（集群状态变化，给运维排障）与 **Audit logs**（谁调了什么 API，给安全合规）。

## Events

Events 是集群内**对象状态变更**的记录：Pod 调度失败、镜像拉取失败、节点 NotReady、容器 OOMKilled、killing/created 等。由 kubelet、controller-manager、scheduler 产生，写入 apiserver、存 etcd。

- 类型：`Normal` / `Warning`；字段含 `reason`（如 `FailedScheduling`、`BackOff`、`Unhealthy`）、`source`（组件）、`involvedObject`（关联对象）、`message`、`count`、`lastTimestamp`。
- 对象：`v1` Events（`events.k8s.io/v1`）。
- 保留：默认 `--event-ttl=1h`（apiserver 参数），过期自动清理——**Events 不是长期存档**。
- 查看：

```shell
kubectl get events -n <ns> --sort-by=.lastTimestamp
kubectl describe pod <pod>     # Events 是第一手排查线索
```

- 体量：量大，生产应接 **Event Router** 把 Events 转发到 ES/Loki，否则默认只留 1 小时。详见 [常见问题排查](/docs/CS/Container/k8s/Issues.md)。

> [!WARNING]
> Events 是"给运维看的状态变化"，不是审计。它不含"谁发起的 API 请求"，且默认仅保留 1 小时。排障够用，合规不够。

## Audit Logs

审计日志记录 **谁、何时、对哪个 API 对象、做了什么请求**（request 级），用于安全合规与溯源。由 **kube-apiserver** 产生。

配置 `--audit-policy-file` 定义策略——对哪些资源、哪些阶段记录什么级别：

| 阶段 | 含义 |
| :--- | :--- |
| `RequestReceived` | 请求一收到就记 |
| `ResponseStarted` | 响应头已发（大响应/流式） |
| `ResponseComplete` | 响应完成 |
| `Panic` | 请求中出现 panic |

级别：`None`（不记）/ `Metadata`（记 meta 不记 body）/ `Request`（记 body）/ `RequestResponse`（记请求+响应 body）。

输出到文件或 **webhook**（对接 SIEM/Splunk），webhook 模式可实时送审。

## Events vs Audit

| | Events | Audit |
| :--- | :--- | :--- |
| 记录内容 | 对象状态变化（Warning/Normal） | 谁调了什么 API（request 级） |
| 用途 | 排障、可观测 | 安全合规、溯源 |
| 产生方 | kubelet/controller/scheduler | kube-apiserver |
| 保留 | 默认 1h | 按输出后端（可长期） |
| 含身份信息 | 否 | 是（user/group） |

> [!WARNING]
> `RequestResponse` 级别会把请求/响应 body 落盘，可能含 **Secret/token**（如创建 Secret 的请求体）。生产务必对审计后端做脱敏/访问控制，或对其敏感资源降到 `Metadata`。

## Links

- [常见问题排查](/docs/CS/Container/k8s/Issues.md)
- [集群访问控制 acl](/docs/CS/Container/k8s/acl.md)
- [身份与证书](/docs/CS/Container/k8s/Identity.md)
- [K8s 主笔记](/docs/CS/Container/k8s/K8s.md)

## References

1. [Events](https://kubernetes.io/docs/reference/kubernetes-api/cluster-resources/event-v1/)
2. [Auditing](https://kubernetes.io/docs/tasks/audit/)
