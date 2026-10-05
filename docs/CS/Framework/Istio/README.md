## Introduction

本目录是 **Istio** 的专题索引。Istio 是 Kubernetes 原生的服务网格：控制面 **Istiod**（Pilot + CA）下发配置，数据面由注入的 **Envoy sidecar** 或 **Ambient** 的 ztunnel / waypoint 代理承载流量。本目录围绕「架构安装 → 流量治理 → 安全 → 可观测 → 扩展」组织，并覆盖 VM 接入、Wasm 插件与生态集成。

```dot
digraph istio_index {
  rankdir=TB;
  node [shape=box, style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica"];
  edge [color="#555", fontsize=10];

  arch [label="架构与安装\nIstio/Install", fillcolor="#fdeccb"];
  traffic [label="流量治理\nTrafficManagement", fillcolor="#e7f4e4"];
  sec [label="安全\nSecurity", fillcolor="#e4eef7"];
  obs [label:"可观测与排障\nObservability/Performance/Troubleshooting", fillcolor="#f3e4f7"];
  ext [label:"扩展与形态\nWasmPlugin/Envoy/VMWorkload/Ambient/ecosystem", fillcolor="#f7e9e4"];
  dp [label="数据面\nEnvoy sidecar / ztunnel", fillcolor="#efefef"];

  arch -> traffic;
  traffic -> sec;
  traffic -> obs;
  obs -> ext;
  sec -> ext;
  ext -> dp;
  traffic -> dp;
}
```

## 架构与安装

- [Istio](/docs/CS/Framework/Istio/Istio.md)：整体架构、Istiod 组件（Pilot / CA / Galley）、sidecar 注入、版本基线。
- [Install](/docs/CS/Framework/Istio/Install.md)：安装方式（istioctl / Helm / Operator）、多集群与版本选择。

## 流量治理

- [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)：核心流量治理——VirtualService / DestinationRule / Gateway / Sidecar、路由、熔断、超时、重试、灰度。

## 安全

- [Security](/docs/CS/Framework/Istio/Security.md)：mTLS（STRICT / PERMISSIVE）、AuthorizationPolicy、JWT、PeerAuthentication。

## 可观测与排障

- [Observability](/docs/CS/Framework/Istio/Observability.md)：指标（Telemetry v2）、分布式追踪、日志、流量镜像。
- [Performance](/docs/CS/Framework/Istio/Performance.md)：性能调优、sidecar 资源、连接池、mTLS 开销。
- [Troubleshooting](/docs/CS/Framework/Istio/Troubleshooting.md)：常见排障命令集、配置不生效、代理状态排查。

## 扩展与部署形态

- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)：Wasm 插件开发（扩展 Envoy 的首选方式）。
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)：Envoy 代理与 Istio 的关系、xDS 配置下发。
- [VMWorkload](/docs/CS/Framework/Istio/VMWorkload.md)：虚拟机工作负载接入网格（WorkloadEntry / WorkloadGroup）。
- [Ambient](/docs/CS/Framework/Istio/Ambient.md)：Ambient 模式（无 sidecar，用 ztunnel + waypoint 简化数据面）。
- [ecosystem](/docs/CS/Framework/Istio/ecosystem.md)：生态与集成（各语言 SDK、第三方扩展）。

## Links

- [Higress（另一网关/网格方案）](/docs/CS/Framework/Higress/Higress.md)
- [Consul（自带服务网格，跨 VM/K8s）](/docs/CS/Framework/consul/README.md)
- [Envoy（数据面代理，本库另见 nginx 服务端侧）](/docs/CS/CN/nginx/nginx.md)
- [Framework 总索引](/docs/CS/Framework/README.md)

## References

1. [Istio Documentation](https://istio.io/latest/docs/)
2. [Istio Ambient Mode](https://istio.io/latest/docs/ambient/)
3. [Envoy Documentation](https://www.envoyproxy.io/docs/envoy/latest/)
