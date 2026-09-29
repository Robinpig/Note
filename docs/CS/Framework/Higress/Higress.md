## Introduction

Higress 是一款云原生 API 网关，内核基于 Istio 和 Envoy，可以用 Go/Rust/JS 等编写 Wasm 插件，提供了数十个现成的通用插件，以及开箱即用的控制台



代码目录结构说明

- cmd: 命令行参数解析等处理代码
- pkg/ingress: Ingress 资源转换为 Istio 资源等相关代码
- pkg/bootstrap: 包括启动 gRPC/xDS/HTTP server 等的代码
- registry: 实现对接多种注册中心进行服务发现的代码
- envoy: 依赖的 envoy 仓库 commit
- istio: 依赖的 istio 仓库 commit
- plugins: Higress 插件 sdk，以及官方内置插件代码
- script: 编译相关脚本
- docker: docker 镜像构建相关脚本















## Links

