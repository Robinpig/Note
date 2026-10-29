## Introduction

配置与镜像解耦是十二要素应用的核心原则，Kubernetes 用两个原生对象落地：

- **ConfigMap**：存放**非机密**的配置数据（键值对或整文件），如环境变量、配置文件、命令行参数。
- **Secret**：存放**机密**数据（密码、token、证书）。注意 Secret 默认只是 **base64 编码**，不是加密——任何能读到 etcd 或 apiserver 对象的人都能解码。

两者都是 namespace 作用域、可被多个 Pod 引用的"配置面"，变更后可以由 Pod 通过环境变量或卷注入，从而**不重建镜像就能改行为**。

> [!TIP]
> 决策线：数据是"配置"还是"机密"决定了用 ConfigMap 还是 Secret；但凡是敏感数据，**一律走 Secret + 静态加密**，不要因为图省事塞进 ConfigMap（ConfigMap 也进 etcd，且默认明文）。

## Creating

四种常见来源，结果都是 etcd 里的一个对象：

```shell
# 字面量
kubectl create configmap app-cm --from-literal=LOG_LEVEL=info --from-literal=PORT=8080

# 从文件（键名=文件名，值是文件内容）
kubectl create configmap app-cm --from-file=config.yaml

# 从 env 文件（key=value 每行一条）
kubectl create configmap app-cm --from-env-file=app.env

# 从目录（每个文件变成一个键）
kubectl create secret generic db-secret --from-file=./certs
```

Secret 也能用字面量，但明文会进 shell 历史，生产推荐从文件或外部系统同步（见 [External Secrets](#External-Secrets)）。

## Consuming: Env vs Volume

同一个对象可以被多个 Pod 以两种主要方式消费：

| 方式 | 字段 | 热更新 | 适用 |
| :--- | :--- | :--- | :--- |
| 环境变量 | `env[].valueFrom.configMapKeyRef` / `.secretKeyRef` | **不热更新**，需重启 Pod | 启动期只读配置 |
| 整组注入 | `envFrom[].configMapRef` / `.secretRef` | 不热更新 | 批量注入 |
| 卷挂载 | `volume` + `volumeMounts` | **卷模式自动更新**（约 1min 同步、原子替换） | 配置文件、需要热加载 |

环境变量注入示例：

```yaml
env:
  - name: LOG_LEVEL
    valueFrom:
      configMapKeyRef:
        name: app-cm
        key: LOG_LEVEL
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: db-secret
        key: password
```

卷挂载示例（把整个 Secret 挂成目录，每个键一个文件）：

```yaml
volumes:
  - name: cfg
    configMap:
      name: app-cm
      # items: 可重映射键 → 文件名
volumeMounts:
  - name: cfg
    mountPath: /etc/app/config
    readOnly: true
```

> [!WARNING]
> 卷挂载热更新的细节坑：更新后文件是**原子替换**（旧 symlink 指向不变、内容变），大部分应用需要自己重新读取；若用 `subPath` 挂载单个键，**不会热更新**（subPath 绕过的是整个卷的原子替换机制）。需要热加载的配置，避免用 `subPath`。

## Immutable

`immutable: true`（v1.19 GA）一旦设置，对象**不可再改**，只能删除重建。收益：

- apiserver 不再为它维护 watch 缓存版本，集群规模大时显著降低 LIST/WATCH 压力；
- 防止误改导致运行中的 Pod 配置漂移。

```yaml
data: {}
immutable: true
```

需要变更时，按"新建 v2 + 改 Pod 引用 + 删旧"的滚动方式，而非原地 patch。

## Secret Types

`type` 决定结构校验与自动填充的键：

| type | 用途 | 关键键 |
| :--- | :--- | :--- |
| `Opaque`（默认） | 任意用户数据 | 自定义 |
| `kubernetes.io/tls` | TLS 证书 | `tls.crt` / `tls.key` |
| `kubernetes.io/dockerconfigjson` | 拉私有镜像的凭据 | `.dockerconfigjson`（被 `imagePullSecrets` 引用） |
| `kubernetes.io/service-account-token` | SA 令牌（自动化） | `token` / `ca.crt` / `namespace` |
| `kubernetes.io/basic-auth` / `.ssh-auth` / `.token` | 通用凭据便捷类型 | 对应 `username`/`password` 等 |
| `bootstrap.kubernetes.io/token` | 节点 TLS bootstrap | 见 [Identity](/docs/CS/Container/k8s/Identity.md) |

## Encryption at Rest

Secret 在 etcd 里默认是 base64（**明文即可解码**）。生产必须在 apiserver 开启 etcd 静态加密，配置在 `--encryption-provider-config` 指向的 `EncryptionConfiguration`：

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - kms:                       # 推荐：密钥在外部 KMS，apiserver 只持密文句柄
          apiVersion: v1
          name: my-kms
      - identity: {}               # 兜底：不加密（放最后）
```

`kms` provider 把 DEK 用外部 KMS 的 KEK 加密，apiserver 内存里才解密；配合 KMS 轮换可实现密文轮换。开启后需 `kubectl get secrets -o json | kubectl replace` 一次性重写存量 Secret 才会被加密。

## External Secrets

把机密**权威源放在集群外**（Vault、AWS Secrets Manager、GCP Secret Manager、阿里云 KMS 等），集群内用 Operator 周期性同步成原生 Secret，避免机密进 Git 或被手改：

- **External Secrets Operator (ESO)**：`ExternalSecret` → 拉外部 → 写原生 `Secret`，声明式、跨云厂商。
- **Secrets Store CSI Driver**：把外部机密/密钥以 CSI 卷形式挂进 Pod（不落原生 Secret，适合挂载文件场景）。

这样 GitOps 仓库里只放 `ExternalSecret` 声明，真实机密永不进 Git。

## Security Notes

- Secret 同样存 etcd、缓存在 apiserver 内存，靠 [RBAC](/docs/CS/Container/k8s/acl.md) 控制谁能 `get`；对敏感 ns 用 `ResourceQuota` + RBAC 收紧。
- 不要把 Secret/ConfigMap 的 YAML 提交到代码仓库；机密交给外部系统（上节）。
- 容器里 Secret 以 tmpfs 挂载（不落磁盘），但 env 注入会在 `ps`/`/proc` 可见，能不 env 就不 env。
- 镜像拉取凭据走 `imagePullSecrets` 引用 `kubernetes.io/dockerconfigjson` 类型 Secret。

## Links

- [Pod 最小调度单元](/docs/CS/Container/k8s/Pod.md)
- [Identity 与证书](/docs/CS/Container/k8s/Identity.md)
- [集群访问控制 acl](/docs/CS/Container/k8s/acl.md)
- [资源配额 ResourceQuota](/docs/CS/Container/k8s/Resource.md)
- [GitOps 持续交付](/docs/CS/Container/k8s/GitOps.md)

## References

1. [ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/)
2. [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
3. [Encrypting Secret Data at Rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
4. [External Secrets Operator](https://external-secrets.io/latest/)
