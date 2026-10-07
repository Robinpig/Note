## Introduction

Helm 是 Kubernetes 的包管理器，类比于 apt / yum / brew 之于操作系统。K8s 原生资源清单（YAML）存在两个痛点：一是同一套应用部署到 dev/staging/prod 时镜像 tag、副本数、资源配额各不相同，纯 YAML 只能复制粘贴；二是应用往往由几十个资源对象组成（Deployment、Service、ConfigMap、Ingress……），缺少整体的安装/升级/回滚单元。Helm 用"模板 + 变量 + 版本化发布"解决这两个问题。

## Three Core Concepts

- **Chart**：一个应用的打包格式，本质是目录树。`Chart.yaml` 描述元信息，`templates/` 放 Go template 语法的资源模板，`values.yaml` 放默认值。
- **Repository**：Chart 仓库，本质是一个可索引的 HTTP 静态服务（`helm repo add`）。
- **Release**：Chart 的一次运行实例。同一个 Chart 安装到不同 namespace（或安装多次）会生成不同 Release，每次安装/升级都会产生递增的 revision——这是 `helm rollback` 的基础。

## Templates and Values

模板中通过 `.Values.xxx` 引用值，值的优先级从低到高：chart 自带 `values.yaml` → `--set` 参数 → `-f` 自定义 values 文件：

```yaml
# templates/deployment.yaml
replicas: {{ .Values.replicaCount }}
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

```shell
helm install myapp ./mychart -f values-prod.yaml --set image.tag=v2.1
helm upgrade myapp ./mychart -f values-prod.yaml   # 升级
helm rollback myapp 3                               # 回滚到 revision 3
helm get manifest myapp                             # 查看 Release 实际渲染出的 YAML
helm template ./mychart -f values-prod.yaml         # 只渲染不安装（调试模板）
```

`--dry-run --debug` 组合可以在不落库的情况下验证渲染结果。

## Hooks and Testing

Helm 生命周期通过 Hook 注入：给资源加 `helm.sh/hook: pre-install` / `post-upgrade` 等 annotation，就能在 Release 生命周期的特定节点执行（典型用法：`pre-install` 的数据库迁移 Job）。测试 Pod 用 `helm.sh/hook: test` 标注，`helm test <release>` 触发。

## Alternatives Beyond Chart

- **Kustomize**：不做模板渲染，用"base + overlay"的 patch 思路管理差异（kubectl 已内置，`kubectl apply -k`）。适合差异化小的场景；逻辑复杂、需要条件分支时 Helm 的模板能力更强。
- **Argo CD / Flux**（GitOps）：解决的是"谁来把 Chart/YAML 应用到集群"的持续交付问题，与 Helm 是互补关系而非竞争——Argo CD 可以直接以 Helm Chart 作为部署源。

## Links

- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [kubectl](/docs/CS/Container/k8s/kubectl.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
