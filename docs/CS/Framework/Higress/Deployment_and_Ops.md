## Introduction

Higress 有四种官方部署形态，但**它们不是"从重到轻"的同一条谱系**：云原生 Helm 是唯一被推荐用于生产的形态，其余三种官方都明确写着"没有大规模生产使用过"。这一页收命令、参数、升级顺序和"配置改了没生效"的定位手法。控制面本身的结构在 [Higress Architecture](/docs/CS/Framework/Higress/Higress.md?id=architecture)。

## Four Forms

| 形态 | 命令入口 | 端口 | 官方定位 |
| --- | --- | --- | --- |
| **K8s + Helm**（云原生） | `helm repo add higress.io https://higress.io/helm-charts` → `helm install higress higress.io/higress -n higress-system --create-namespace` | Gateway 80 / 443，metrics 15020，Console 为 ClusterIP | 生产推荐 |
| **Docker All-in-One** | 单容器 | **8001 = Console，8080 = Gateway HTTP，8443 = Gateway HTTPS** | "主要用于本地部署测试" |
| **Docker Compose / Standalone** | `curl -fsSL https://higress.io/standalone/get-higress.sh \| bash -s -- ./higress [OPTIONS]` | Gateway 80 / 443（`--gateway-http-port` 等可改）、`--console-port` 默认 **8080**、`--gateway-metrics-port` 15020 | "主要用于本地部署测试" |
| **阿里云计算巢** | 一键部署 | 随云产品 | 云上快速起步 |

两个仓库地址写法都要接受：`https://higress.io/helm-charts` 与 `https://higress.cn/helm-charts` 在官方文档里**并存**（前者出现在 `deploy-by-helm`、`prometheus`、`upgrade`，后者出现在 `quickstart`）；`helm repo add` 的本地别名恰好都叫 `higress.io`，容易误以为是域名。引用命令时注明出处页面。

> [!WARNING]
> All-in-One 的镜像名必须带 ACR 前缀，写成 `higress/all-in-one:latest` 拉不到：
>
> ```bash
> docker run -d --rm --name higress-ai -v ${PWD}:/data \
>   -p 8001:8001 -p 8080:8080 -p 8443:8443 \
>   higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:latest
> ```
>
> 三个高频坑：① **8080 是网关 HTTP 入口，不是控制台端口**（控制台是 8001），而 Standalone 形态的 `--console-port` 默认又是 8080——同一数字在两个形态里指不同组件；② 想要内置监控套件必须**换镜像 tag 后缀** `-o11y`（如 `latest-o11y`），只设环境变量 `O11Y=on` 不够；③ 配置以卷挂载存在本地磁盘（`-v ${PWD}:/data`）。
>
> All-in-One 的环境变量：`MODE`（`full` / `gateway` / `console`，默认 full）、`O11Y`（默认 off）、`USE_PLUGIN_SERVER`（默认 on，关掉则需从公网镜像服务器下载 Wasm 插件）、`GATEWAY_HTTP_PORT` 8080、`GATEWAY_HTTPS_PORT` 8443、`CONSOLE_PORT` 8001、`ENABLE_CONSOLE_ROUTE` 0（1 表示在 Gateway 上为 Console 建路由）。

Standalone 形态值得记的是它的**配置源选择**：`-c/--config-url` 可指向独立 Nacos（**版本不低于 2.0.0**，格式 `nacos://192.168.0.1:8848`）或本地磁盘（`file:///opt/higress/conf`）；`--use-builtin-nacos` 用内置 Nacos、官方注明不建议用于生产；`--nacos-ns` 默认 `higress-system`；`-k/--data-enc-key` 是敏感信息加密密钥，**长度必须 32 个字符**，不设则随机生成，**集群部署时必须显式设置**否则各节点密钥不一致（这里只记机制，不记值）。容器名在官方两处文档不一致（创建用 `higress-ai`，`view-logs` 的示例是 `docker exec -it higress-ai-gateway bash`），**照抄前先换成自己创建的名字**。

源码侧（`higress-standalone` @ `aio-v2.2.5`）把这段"脱离 K8s"的实现说清楚了，也修正了两处常见误解：**默认 profile 实际常驻约 10 个容器而不是 5 个**（另有 nacos、plugin-server 与观测四件套），且 apiserver 的持久层**没有 etcd**——`--storage` 只有 `nacos`（默认）与 `file` 两个合法值，CR 实例分别落到 Nacos 配置项（`dataId = <resource>.<name>` + `ListenConfig` 模拟 watch）与本地文件树（fsnotify 模拟 watch）。那个"模拟 K8s API Server"的组件是 **kubernetes `sample-apiserver` 的直接 fork**（`k8s.io/apiserver` v0.31.2），不是 k3s / kine / envtest；controller / pilot / console 拿 precheck 现生成的自签证书与 kubeconfig 连它的 8443，走的就是常规 list/watch，**所以主仓控制面不需要为此改一行代码**。另外，那串端口与凭据参数属于 **`bin/configure.sh`**（822 行，参数逐个核到 case 块 `:85-191`，还有一批文档未列的 `-r/--rerun`、`-s/--storage`、`--nacos-service-port` 等）；本仓另有一个 `src/get-higress.sh` **与主仓同名但不同物**，它是安装器、只认 `-h` 与 `-u`，**不吃这些参数**。All-in-One 则是 supervisord 编排 10 个进程、按 priority 0→3000 依次拉起，且**只有 file 存储、没有 Nacos**，网关端口默认也变成 8080 / 8443。这些细节、参数对照表与可复现性凭据（`release-provenance.json` 把主仓 commit 与五个镜像 digest 钉死）在 [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md)。

控制台侧的登录口径是：**首次访问需先初始化管理员账号，初始化完成后跳转登录页**，没有"内置默认口令"这回事；集群内可用 `hgctl dashboard console` 打开。相关 values：`higress-console.web.login.prompt`（登录页提示文案）、`higress-console.swagger.enabled`（默认 false）。

## Helm Values That Matter

参数全集在 [Higress 参数配置](https://higress.ai/docs/latest/user/configurations/)，这里只留决策相关的：

| 参数 | 默认 | 为什么重要 |
| --- | --- | --- |
| `global.ingressClass` | `higress` | 设 `nginx` 则监听 class 为 nginx **或为空**的 Ingress；设空串监听全部。多网关并存与迁移期都靠它 |
| `global.watchNamespace` | `""` | 非空则只监听该命名空间，用于"每业务一套独立网关" |
| `global.enableStatus` | `true` | 会回写 Ingress 的 `status`；**从 Nginx Ingress 迁移期官方建议设 false**，否则覆盖原入口 IP |
| `global.enableIstioAPI` / `global.enableGatewayAPI` | `false` / `false` | 两者都是显式开启才监听，详见本页 Gateway API 一节 |
| `global.onlyPushRouteCluster` | `true` | 只推送被路由关联的 K8s 服务 cluster，直接决定 Envoy 内存与推送体量 |
| `global.local` | `false` | 装到本地 Kind / Rancher Desktop 时设 true |
| `global.defaultUpstreamConcurrencyThreshold` | `10000` | 单实例与单个后端之间的最大并发，过高会顶高数据面内存 |
| `global.disableAlpnH2` | `false` | 是否在 ALPN 中禁用 HTTP/2 |
| `global.o11y.enabled` | `false` | 装上可观测套件（见 [Observability](/docs/CS/Framework/Higress/Observability.md)） |
| `global.pvc.rwxSupported` | `false` | 是否支持 ReadWriteMany，影响 Console 多副本 |
| `higress-core.gateway.replicas` | `2` | 数据面副本；HPA 默认关（`autoscaling.enabled` false，min 1 / max 5 / 目标 CPU 80） |
| `higress-core.gateway.kind` | `Deployment` | 可设 DaemonSet |
| `higress-core.gateway.resources` | 2000m / 2048Mi（request 与 limit 同值） | 默认是 request 等于 limit 的 Guaranteed 形态 |
| `higress-core.gateway.rollingMaxSurge` / `rollingMaxUnavailable` | `100%` / `25%` | 数据面滚动策略 |
| `higress-core.controller.replicas` | `1` | 控制面默认单副本 |
| `higress-core.controller.automaticHttps.enabled` | `true` | ACME 自动签发默认开，详见 [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md) |
| `higress-console.replicaCount` | `1` | 控制台副本 |

改 Gateway 监听端口（默认 80 / 443）**不是运行时能改的东西**：必须在安装或升级时指定，且要同步 Service 的 `targetPort`。例：

```yaml
higress-core:
  gateway:
    httpPort: 8080
    httpsPort: 8443
  service:
    ports:
    - {name: http2, port: 80,  protocol: TCP, targetPort: 8080}
    - {name: https, port: 443, protocol: TCP, targetPort: 8443}
```

Standalone 用 `--gateway-http-port=8080 --gateway-https-port=8443`，hgctl 用 `hgctl install --set profile=local-docker --set gateway.httpPort=8080 --set gateway.httpsPort=8443`。

`higress-config` 这个 ConfigMap 除观测外还管连接与压缩参数（`higress-https` 是**另一个** ConfigMap，只管证书，两者常被合并叙述）：`downstream.connectionBufferLimits` 32768、`downstream.idleTimeout` 180、`downstream.maxRequestHeadersKb` 60、`downstream.http2` 的 `initialConnectionWindowSize` / `initialStreamWindowSize` / `maxConcurrentStreams`（1048576 / 65535 / 100）、`upstream.connectionBufferLimits` 1048576、`upstream.idleTimeout` 10，以及 `gzip`（`enable` 默认 false、`minContentLength` 1024、`memoryLevel` 5、`windowBits` 12、`chunkSize` 4096、`disableOnEtagHeader` true）。

## Upgrade Order

云原生形态的四步，**顺序有讲究，CRD 必须先行**：

```bash
kubectl apply -f https://github.com/alibaba/higress/releases/download/${higress_version}/crd.yaml
helm repo update
helm get values higress -n higress-system > values.yaml
helm upgrade higress --version ${higress_version} -n higress-system higress.io/higress -f values.yaml
```

> [!WARNING]
> 升级页原文是"**不建议使用 `--reuse-values`，因为它会继承所有上一个版本的 values**"，标准做法是 `helm get values` 导出后用 `-f values.yaml`。但同一份文档的另一处自相矛盾：`deploy-by-helm` 页开启 Gateway API / Istio API 的示例用的正是 `helm upgrade ... --reuse-values`。**以升级页为准**，别把 helm 页示例当通用做法。独立部署形态的升级是 `VERSION=${higress_version} ./get-higress.sh "${higress_dir}" -u`（`-u` 即升级）。

## Gateway API Status

**结论是"部分支持"，既不是不支持也不是完全可用。** 集群要先安装 Gateway API CRD（kubernetes-sigs/gateway-api releases），再 `helm upgrade ... --set global.enableGatewayAPI=true`（默认 false），官方验证样例在仓库 `samples/gateway-api/demo.yaml`。版本配对矩阵是硬约束：

| Higress 版本 | 配套 Gateway API |
| --- | --- |
| ≥ 2.2.4 | 1.6.0 |
| ≥ 2.2.0 且 < 2.2.4 | 1.4.0 |
| ≤ 2.1.x | 1.0.0 |

两条"部分"的证据：TLS 全局配置（含 ACME 自动签发）**当前仅对 Ingress 模式生效，Gateway API 暂不支持**；四层 TCP 路由文档**明确不适用于 ≥ 2.2.0 且 < 2.2.4 的版本**，且 `TCPRoute` 的 apiVersion 在 2.2.4 前后从 `v1alpha2` 升到 `v1`。Roadmap 页早在 v1.3.0 就写了"完整支持 GatewayAPI"——**roadmap 是计划表不是事实表**，以这里列出的约束为准。

## hgctl and Troubleshooting Chain

`hgctl` 的源码在顶层 `hgctl/`（独立 go module，**不是文档目录表暗示的 `tools/hgctl`**），命令树在 `hgctl/pkg/root.go:35-47`，共 13 个顶层子命令：`profile`（list / dump）、`install`、`upgrade`、`dashboard`、`uninstall`、`plugin`，另有 `version`、**`config`**、`manifest`、`completion`、`code-debug`、`mcp`、`agent`。

> [!WARNING]
> **`hgctl config` 确实存在**，但它的语义是**抓 xDS 配置**——二级命令 `all` / `bootstrap` / `cluster` / `endpoint` / `listener` / `route`（`hgctl/pkg/config_cmd.go:45-50`），文档站的 hgctl 页整段没提它。反过来，`profile` / `install` / `upgrade` / `dashboard` / `uninstall` 这些是 **root 的子命令**，不是 `config` 的子命令；旧资料把两组混成"hgctl config 的子命令是 profile / install / …"是错的。`plugin` 子命令组的真实动作是 `build` / `install` / `uninstall` / `ls` / `test` / `config` / `init`（`hgctl/pkg/plugin/plugin.go:36-42`）。

install 核心参数只有 `-s/--set` 与 `-f/--filename`，profile 取值文档里出现的是 `local-k8s` 与 `local-docker`。`dashboard` 可打开 Console、Controller Debug、Envoy、Grafana、Prometheus 五个界面（`--browser` 默认 true）。

"配置改了但没生效"必须按层定位，四段链依次是控制面生成、pilot 收到、pilot 推出、数据面生效：

```bash
# 1) controller 生成的配置
curl http://localhost:8888/debug/configz?pretty
# 2) pilot 收到的配置
curl http://localhost:15014/debug/configz
# 3) pilot 推送出去的：先拿 connectionId，再按 proxyID 取 dump
curl http://localhost:15014/debug/connections
curl "http://localhost:15014/debug/config_dump?proxyID=<gateway-pod-name>.<namespace>"
# 4) gateway 实际生效配置
curl http://localhost:15000/config_dump
```

三种形态都能用：K8s 下 `kubectl exec` 进对应容器，All-in-One 下 `docker exec` 进容器，Standalone 下直接本机 curl。日志侧：K8s 按组件看 controller / gateway 日志，**All-in-One 下所有日志文件都在容器内 `/var/log/higress`**。想看 API 清单可开 Swagger：`--set higress-console.swagger.enabled=true`，地址 `http://<higress-console-endpoint>/swagger-ui/index.html`。

内置插件镜像地址换到私有仓库是运维常见动作：给 **Console 容器**加环境变量 `HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN`，模板占位符 `${name}` / `${version}`（如 `oci://hub.example.com/wasm-plugins/${name}:${version}`，也可指 http 的 `.wasm`）。**三处转义写法不同**：Helm 写在 values 的 `console.env`；Docker Compose 在 `compose/env/console.env` 且 `$` 要写成 `$$`；`docker run -e` 要写成 `\$`。Nacos 3.x 的 MCP 注册中心另有 `MCP_SERVER_WASM_IMAGE_URL`（Controller 环境变量，默认指向公共插件仓库）。

## Production Notes

FAQ 与场景页给出的、值得照抄进决策清单的口径：

网关**无状态**、本身是个 Deployment，弹性伸缩基于 K8s HPA。**离线部署目前没有现成版本，需要自行构建**（Docker 镜像有提供）。除 K8s 外也支持虚拟机与物理机场景。与 Envoy Gateway 的差别，官方表述是：同样基于 Envoy、同样遵循 Gateway API 标准，但 Higress 额外提供 WAF 防护与认证鉴权等安全插件、多注册中心 / 协议转化 / 限流降级，以及 WASM、Lua 等自定义插件，并称后续会支持**进程外插件**。与 Tengine 的差别是 Nginx+Lua 对 Istio+Envoy+Wasm，且 Higress 支持 Nginx Ingress 注解平滑迁移。MSE 云原生网关是其商业化版本，FAQ 说能力差异"主要体现在性能、稳定性、易用性、安全性，详细资源还在整理"——**没有官方对比表，不要凭推测列差异**。

关于"性能比 Java 网关高 2 倍以上"这类倍数，官方文档口径只有定性表述（"基于 Envoy C++ 网关内核的出色性能，相比传统 Java 类微服务网关，可以显著降低资源使用率，减少成本"），**没有出现 2 倍这个数值**，引用时不要写成实测结论。与 Spring Cloud Gateway 的取舍讨论见 [gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)，横向对比见 [Nginx Compare](/docs/CS/CN/nginx/compare.md)。

## Unverified

`hgctl install` 支持的完整 profile 取值集合与 hgctl 级参数全集；Standalone 各参数的必填性校验规则（参数**存在性已逐个核到源码**，但 `-c` 与 `--use-builtin-nacos` 之外的组合约束、`-k` 在升级时是否会轮换既有密文仍未核）；Console 管理员账号是否落地为某个 K8s Secret、密码重置方式与登录失败锁定策略；`crd.yaml` 在各版本间的差异；企业版（MSE 云原生网关）与开源版在 WAF / 认证插件上的功能差异清单。

Istio / Envoy 的内核版本已不再是未决项——主仓 `.gitmodules` 把 fork 分支钉在 **`istio-1.27`**（`istio/pkg` 单独走 `istio-1.19`）与 **`envoy-1.36`**，K8s 侧依赖 pin 在 v0.34.1，证据与推导链在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)。

## Links

- [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md)
- [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)
- [Observability](/docs/CS/Framework/Higress/Observability.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [使用 Helm 进行云原生部署](https://higress.ai/docs/latest/ops/deploy-by-helm/)
- [基于 Docker 容器进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker/)
- [基于 Docker Compose 进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker-compose/)
- [版本升级](https://higress.ai/docs/latest/ops/upgrade/)
- [hgctl 工具使用说明](https://higress.ai/docs/latest/ops/hgctl/)
- [查看运行时配置](https://higress.ai/docs/latest/ops/how-tos/view-configs/)
- [查看日志](https://higress.ai/docs/latest/ops/how-tos/view-logs/)
- [修改 Gateway 监听端口](https://higress.ai/docs/latest/ops/how-tos/gateway-ports/)
- [修改内置插件镜像地址](https://higress.ai/docs/latest/ops/how-tos/builtin-plugin-url/)
- [启用 Swagger 文档](https://higress.ai/docs/latest/ops/how-tos/enable-swagger/)
- [FAQ](https://higress.ai/docs/latest/overview/faq/)
