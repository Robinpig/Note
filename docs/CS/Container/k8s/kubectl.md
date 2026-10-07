## Introduction

kubectl 是与 [apiserver](/docs/CS/Container/k8s/apiserver.md) 交互的官方命令行客户端，本身无状态：所有集群状态都存在 [etcd](/docs/CS/Container/k8s/etcd.md) 中，kubectl 只是把用户意图翻译成 REST 请求。它的配置来自 kubeconfig（`--kubeconfig` / `$KUBECONFIG` / `~/.kube/config`），支持配置多个 cluster / user / context 并一键切换。

## Common Commands Quick Reference

```shell
# 资源查询
kubectl get pods -A --show-labels -o wide
kubectl get deploy myapp -o yaml
kubectl describe pod myapp-xxx        # Events 是排障第一手线索
kubectl explain deployment.spec       # 内置 API 文档，不用查网页

# 日志与执行
kubectl logs myapp-xxx -c app --tail=100 --previous
kubectl exec -it myapp-xxx -- /bin/sh
kubectl port-forward pod/myapp-xxx 8080:80   # 本地调试
kubectl top pod                       # 依赖 metrics-server

# 变更
kubectl apply -f deploy.yaml          # 声明式，CI/CD 首选
kubectl diff -f deploy.yaml           # 预览 apply 的效果
kubectl rollout restart deploy/myapp  # 滚动重启
kubectl rollout status deploy/myapp
kubectl scale deploy myapp --replicas=5
kubectl delete -f deploy.yaml --grace-period=0 --force   # 慎用，跳过优雅终止

# 调试
kubectl debug -it myapp-xxx --image=nicolaka/netshoot
kubectl get events --sort-by=.lastTimestamp
```

几个值得记住的行为差异：`create` 是命令式（存在即报错），`apply` 是声明式（合并 patch）；`edit` 改动的是存活对象，不会回写本地 YAML，容易造成配置漂移——用 GitOps（见 [Helm](/docs/CS/Container/k8s/Helm.md)）管理时禁止直接 edit。

## Source Code View: Request Construction Flow

kubectl 是了解 client-go 的最佳入口（详见 [client-go](/docs/CS/Container/k8s/client-go.md)）。

创建资源对象的流程可分为：实例化 Factory 接口、通过 Builder 和 Visitor 将资源对象描述文件（deployment.yaml）文本格式转换成资源对象。将资源对象以 HTTP 请求的方式发送给 kube-apiserver，并得到响应结果。最终根据 Visitor 匿名函数集的 errors 判断是否成功创建了资源对象。

其中 Builder/Visitor 模式是 kubectl 代码的特色：Builder 负责把命令行参数（文件名、label selector、resource type）归一化为统一的资源对象流，Visitor 则以责任链方式对每个对象执行操作（转换、打印、发送），这也是 `kubectl` 能用同一套骨架支持几乎所有资源命令的原因。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)

## References

1. [Kubernetes源码分析——从kubectl开始](https://qiankunli.github.io/2018/12/23/kubernetes_source_kubectl.html)
