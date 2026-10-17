## Introduction

Higress 作为"微服务网关"与一个普通 Ingress 控制器的分野就在这里：**后端不必是 Kubernetes Service**。它把 Nacos、ZooKeeper、Consul、Eureka、静态 IP、DNS 都变成可路由的目标，并且让 Dubbo 这类 RPC 协议能以标准 HTTP 接口暴露出去。承担这件事的是同一个 CRD——`McpBridge`，加上一个协议转换 CRD `Http2Rpc`。

## McpBridge the Single Object

`McpBridge`（`apiVersion: networking.higress.io/v1`）是服务来源的**唯一载体**。它有两条硬约束，都在配置页顶部的"注意"块里：

- **当前仅会监听 higress 安装命名空间下、命名为 `default` 的 mcpbridge 资源**；`metadata.name` 标注为"是，当前该值只能是 `default`"。
- 因此**多租户不能靠建多个 McpBridge 实现**，只能在它的 `registries` 数组里配多个来源。控制台里对应的菜单项是"服务来源"。

`registries` 是一个 `RegistryConfig` 数组，可混配不同类型的注册中心；**必填只有 4 个字段**：`type`、`name`、`domain`、`port`，其余全部选填。对 Nacos 类型还支持配置多个不同命名空间，从而"不同命名空间的微服务共用一个网关"。

```yaml
apiVersion: networking.higress.io/v1
kind: McpBridge
metadata:
  name: default
  namespace: higress-system
spec:
  registries:
    - name: my-nacos
      type: nacos2
      domain: 192.168.1.2
      port: 8848
      nacosNamespaceId: d8ac64f3-xxxx-xxxx-xxxx-47a814ecf358
      nacosGroups:
        - DEFAULT_GROUP
    - name: my-backends
      type: static
      domain: "1.1.1.1:80,2.2.2.2:80"
      port: 80
```

## Registry Types

`type` 的完整枚举是 8 个值：`nacos`、`nacos2`、`nacos3`、`zookeeper`、`consul`、`eureka`、`static`、`dns`。

| 类型 | 专有选填字段 | 说明 |
| --- | --- | --- |
| `nacos` / `nacos2` / `nacos3` | `nacosNamespaceId`、`nacosGroups`、`nacosAccessKey`、`nacosSecretKey`、`nacosRefreshInterval` | 三个值是并列的独立取值：**`nacos` = Nacos 1.x，只支持 HTTP；`nacos2` = Nacos 2.x，支持 gRPC**，官方建议升到 2.x 用 `nacos2`，"从而更快速地感知到服务变化，并消耗更少的 Nacos 服务端资源"；`nacos3` 目前唯一被文档点名的用途是作为 MCP Server 的注册源（见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)）。`*RefreshInterval` 单位是**纳秒**，示例 `30000000000` 即 30 秒。默认端口 8848 |
| `zookeeper` | `zkServicesPath`（字符串数组） | 默认同时监听 `/dubbo` 与 `/services`，"前者为 dubbo 服务默认根路径，后者为 SpringCloud 服务默认根路径"。默认端口 2181 |
| `consul` | `consulDatacenter`、`consulServiceTag`、`consulRefreshInterval`（纳秒） | 无额外强制字段 |
| `eureka` | 无 | **本页只在枚举里出现 `eureka`，没有任何专属字段与示例** |
| `static` | `protocol`、`sni` | `domain` 直接写多个后端地址 `1.1.1.1:80,2.2.2.2:80` |
| `dns` | `protocol`、`sni` | `domain` 写域名（如 `www.alibaba.com` + `port: 443` + `protocol: HTTPS`） |

`protocol`（`HTTP` / `HTTPS` / `GRPC` / `GRPCS`，默认 HTTP）**仅对 static 与 dns 生效**；`sni` 在 protocol 为 HTTPS 或 GRPCS 时设置 TLS 握手用的 SNI。这两点解释了为什么"给注册中心类型配 protocol"不生效。

认证统一走 `authSecretName`，引用 `higress-system` 命名空间下的 Secret，**当前只支持 nacos 与 consul**：nacos 的 key 是 `nacosUsername` + `nacosPassword`，consul 是 `consulToken`。（凭据内容不落文档，只记机制与字段名。）

## Destination Naming

Ingress 指向"注册中心里的服务"时，`backend` 不写 `service` 而写 `resource`，真正的目标由 annotation 给出：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: user
  namespace: default
  annotations:
    higress.io/destination: "user-center.DEFAULT-GROUP.public.nacos"
spec:
  ingressClassName: higress
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              resource:
                apiGroup: networking.higress.io
                kind: McpBridge
                name: default
```

> [!WARNING]
> 命名格式必须满足 **DNS 域名规范**，由此推出三条规则：① **所有下划线都要写成连字符**——Nacos 分组 `DEFAULT_GROUP` 在 destination 里写作 `DEFAULT-GROUP`，ZooKeeper 的 discovery root 若含下划线同理；② 命名空间**缺省写 `public`，不是留空**；③ Dubbo 服务名本身带冒号也照写（官方示例确实是 `providers:com.alibaba.nacos.example.dubbo.service.DemoService:1.0.0:dev.DEFAULT-GROUP.public.nacos`，这与其自述的 DNS 规范存在张力，但示例无误）。

各来源的格式：

| 来源 | `higress.io/destination` 格式 | 例子 |
| --- | --- | --- |
| Nacos | `服务名称.服务分组.命名空间ID.nacos` | `my-service.DEFAULT-GROUP.public.nacos`、`service-provider.DEFAULT-GROUP.d8ac64f3-xxxx.nacos`、自定义分组 `my-service.custom-group.d8ac64f3-xxxx.nacos` |
| ZooKeeper | `服务名称.服务注册根路径.zookeeper` | `my-service.services.zookeeper`；配了 `spring.cloud.zookeeper.discovery.root=my-services-root` 则是 `my-service.my-services-root.zookeeper` |
| Dubbo over Nacos | `providers:<接口>:<version>:<group>.<分组>.<命名空间>.nacos` | 见上方 WARNING |

`static` / `dns` / `consul` / `eureka` 四种来源的 destination 命名格式**文档未写**，本次未核实。

## Spring Cloud and Dubbo

Spring Cloud 有两条接入路径：**(a) Nacos 注册中心**——`type: nacos2` 加 `nacosGroups` / `nacosNamespaceId`，与 `spring.cloud.nacos.discovery.*` 一一对应，Spring Cloud 微服务无需改造即可接入；**(b) ZooKeeper 注册中心**——`type: zookeeper`，此时**必须配 `spring.cloud.zookeeper.discovery.preferIpAddress=true`**，否则注册进去的是主机名而非 IP，网关无法直连。

Dubbo 走 McpBridge 对接 Nacos 或 ZooKeeper 任一作为服务来源，"通过 McpBridge，我们可以直接从 Nacos 中发现 Dubbo 服务，并为其创建路由"。

这两条路只解决"发现"，不解决"协议"。Dubbo 的私有协议不能被 HTTP 请求直接命中，所以下一节。至于后端负载均衡算法与亲和（`load-balance`、`affinity`、`upstream-hash-by` 都属于"部分兼容"、`ewma` 会静默回退），写在 [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)。

## Http2Rpc

`Http2Rpc`（`apiVersion: networking.higress.io/v1`）解决的问题是：把 Dubbo 服务以 HTTP 接口暴露出来，"用户通过配置协议转换，可以将一个 Dubbo 服务以 HTTP 接口暴露出来，从而用 HTTP 请求实现对 Dubbo 接口的调用"。**页面通篇不要求改造 Dubbo 服务端**，只要求框架版本。

版本边界要逐字记住："Higress 目前支持的 Dubbo 框架的版本为 **2.x**。若您使用 Dubbo3.0，要求使用 dubbo 协议（**目前暂不支持 Triple 协议**。Triple 协议底层基于 gRPC，可以直接代理，无需做协议转化）"。所以 Triple 的正确姿势是**当 gRPC 直接代理**（`backend-protocol: GRPC`），Http2Rpc 只对 dubbo 协议有意义。

配置需要**两段手工对齐**：Ingress 用 `higress.io/destination` 指到 Dubbo 服务名，再用 `higress.io/rpc-destination-name` 给这次转换命名；`Http2Rpc` 的 `metadata.name` **必须等于那个值**（namespace 也要一致，示例都在 `higress-system`）。不是靠 label selector 或 ownerReference，对不上就静默不生效。

```yaml
apiVersion: networking.higress.io/v1
kind: Http2Rpc
metadata:
  name: httproute-http2rpc-demo
  namespace: higress-system
spec:
  dubbo:
    service: com.alibaba.nacos.example.dubbo.service.DemoService
    version: 1.0.0
    group: dev
    methods:
    - serviceMethod: sayName
      headersAttach: "*"          # 空=不透传；*=全透传；或逗号分隔 header-A,header-B
      httpMethods: ["GET"]
      httpPath: "/dubbo/hello"
      params:
      - paramKey: p
        paramSource: QUERY        # QUERY / HEADER / PATH / BODY
        paramType: "java.lang.String"
```

字段两级枚举：`httpMethods` 取 `GET` / `POST` / `PUT` / `DELETE` / `PATCH`；`paramSource` 取 `QUERY`（url param）/ `HEADER` / `PATH`（url path）/ `BODY`。`spec` 是 oneof，另一支是 `grpc`（`proto_descriptor_str` 或 `proto_descriptor_file_path` + `services`，见 CRD 的 proto 定义）。**`paramFromEntireBody` 与 `params` 同时配置时 `params` 被忽略**，且前者只适用于单参数方法。实测返回体形态是结果被包在 `result` 字段里：`{"result":"Service [name :demoService , port : 20880] sayName(\"abc\") : Hello,abc"}`。

## Consuming Discovery from Plugins

服务发现这套体系还有一层副作用值得单独指出：**Wasm 插件里发起的 HTTP / Redis 外调，寻址单位是 Envoy cluster 名，不是 URL**。各种来源生成的 cluster 名规则（`outbound|<Port>|<Version>|<FQDN>` 家族）与由此产生的限制，展开在 [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)。这条链解释了为什么限流插件的 Redis 必须先注册成服务来源、为什么 `redis.static` 不写端口会连到 80。

## Unverified

`eureka` 与 `nacos3` 的专有 / 必填字段与 YAML 示例（McpBridge 页里 `eureka` 只出现在枚举、`nacos3` 只在 `enableMCPServer` 备注里出现）；`static` / `dns` / `consul` / `eureka` 的 destination 命名格式；Higress 侧的服务健康检查机制与主动探活配置（文档未见对应页面，`global.defaultUpstreamConcurrencyThreshold` 是并发上限不是健康检查）；`consulServiceTag` 的过滤语义细节；`nacosRefreshInterval` 与 consul 同名参数的取值边界与生效方式。

## Links

- [Architecture](/docs/CS/Framework/Higress/Architecture.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [Mcp Bridge 配置说明](https://higress.ai/docs/latest/user/mcp-bridge/)
- [配置 Ingress 转发给注册在 Nacos 的服务](https://higress.ai/docs/latest/user/nacos-route/)
- [实现 SpringCloud 服务发现和路由](https://higress.ai/docs/latest/user/spring-cloud/)
- [Higress 对接 Dubbo 服务](https://higress.ai/docs/latest/user/dubbo/)
- [HTTP 转 Dubbo 配置说明](https://higress.ai/docs/latest/user/dubbo-http2rpc/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
