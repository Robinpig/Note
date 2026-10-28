## Introduction

独立部署形态在文档里只有一段安装命令，但它其实是 Higress 最不寻常的一块工程：**在没有任何 Kubernetes 的机器上，自己实现一个 apiserver，让控制面以为自己还在监听 CRD**。基准是第二个仓 `higress-standalone`（`git describe` = **`aio-v2.2.5`**，HEAD `3688250`，2026-10-05），跨到主仓的结论标注主仓路径。

文档说"Standalone 用 5 个容器把 K8s 控制面重新演一遍（apiserver / controller / pilot / gateway / console）"——这五件套是对的，但省略了两个关键差异：**默认 profile 实际常驻约 10 个容器**，以及**持久层不是 etcd 而是 Nacos 配置项或本地文件**。

## The Fake apiserver

`src/apiserver` 是 **Kubernetes `sample-apiserver` 的直接 fork**：模块名 `github.com/alibaba/higress/api-server`（`src/apiserver/go.mod:1`），`k8s.io/{apiserver,apimachinery,client-go,component-base}` 全部 pin 在 **v0.31.2**，README 通篇是上游原文。它不是 k3s、不是 kine、不是 envtest，**没有 etcd、没有 kube-apiserver 二进制**。入口 `main.go` 把 RLIMIT_NOFILE 提到 65535，然后走 `server.NewCommandStartHigressServer`（`pkg/cmd/server/start.go`），并把 generic apiserver 的 `SkipOpenAPIInstallation` 设为 true。

对外它就是标准 REST + list/watch/discovery：compose 形态 TLS 端口 8443（`--secure-port 8443` + `--client-ca-file`，`compose/docker-compose.yml:65-72`）、健康检查 `https://127.0.0.1:8443/readyz`（`:96`）。controller / pilot / console 拿 precheck 生成的 **kubeconfig**（含 client 证书）连它——**这就是"控制面不改一行代码就能脱离 K8s"的机制**。认证只有一个 `--auth-enabled` 开关（默认 false），compose 形态根本没传，靠 TLS 客户端证书。

注册的资源约 21 类（`pkg/apiserver/apiserver.go`，generic server 名 `higress-apiserver:152`）：core/v1 的 configmaps / secrets / services / endpoints / pods / nodes / namespaces / endpointslices，apiextensions 的 customresourcedefinitions（`:182` 特判），admissionregistration 两个 webhook configuration，networking.k8s.io 的 ingresses（`:306`）与 ingressclasses（`:310`），Higress 三件套 **wasmplugins / mcpbridges / http2rpcs**，Gateway API 的 gatewayclasses / gateways / httproutes / referencegrants，以及 legacy istio group 的 `envoyfilters`（`:378-385`）。

**CRD 定义是静态内嵌、只读提供的**：`pkg/storage/customresourcedefinition.go:22` 把 `pkg/storage/crds/*.yaml` 解码成固定切片，Get 在 `:62`、List 在 `:83`，**不可增删改**。而这个目录里只有 5 个 YAML（gatewayclasses / gateways / httproutes / referencegrants / envoyfilters），**不含 wasmplugins 与 mcpbridges**——三件套的 storage 已注册但 CRD schema 不在此处，控制器与 console 怎么拿到它们的 schema 未从调用点证实（见 Unverified）。

## Storage Backends

CR 实例的持久层二选一（`pkg/apiserver/apiserver.go:188` NewFileREST / `:194` NewNacosREST；`pkg/options/options.go` 定义 `Storage_File="file"`、`Storage_Nacos="nacos"`，**默认 nacos**，填别的值直接报 "invalid storage mode"）：

- **file 后端**（`pkg/registry/file_rest.go`，704 行）：对象落盘成 `objRootPath/<resource小写>/<name>+extension`（`objectFileName:516-523`，**路径刻意忽略 namespace**，旁边还有被注释掉的分目录代码）；写盘是 `.tmp` + `os.Rename`（`:566`）；watch 靠 fsnotify（`startDirWatcher:122`、`notifyWatchers:225`）。根目录由 `--file-root-dir` 指定，默认 `./conf`。
- **Nacos 后端**（`pkg/registry/nacos_rest.go`，831 行）：用 nacos-sdk-go v2 的 config client，`dataId = <resource小写> + "." + names`（`:106`，分隔符常量在 `:42`），后台对"名单" dataId 做 `ListenConfig`（`watchNamesConfig:173`）再拉列表来模拟 watch；命名空间由 `--nacos-ns-id` 给定。相关默认：`NACOS_DISABLE_USE_SNAPSHOT=false`、`NACOS_LIST_REFRESH_INTERVAL_SECS=10`、`NACOS_CONFIG_SEARCH_PAGE_SIZE=50`。加密走 `--nacos-encryption-key-file`（compose 挂到 `/etc/api/nacos.key`，`docker-compose.yml:85-86`）配 `pkg/utils/encryption.go`。

⇒ 文档里"配置可以存独立 Nacos 或本地磁盘"这句话的真实含义是：**整个 K8s API 的对象存储被换成了 Nacos 配置项或一棵文件树**，Higress 主仓的 controller 只认 kubeconfig，不需要知道下面是什么。

## Compose Topology

唯一的编排文件是 `compose/docker-compose.yml`（444 行，网络 `higress-net`），**15 个服务**。`src/runner` 不是 supervisor 而是一个无代码的工具箱镜像（`FROM ubuntu` + curl / wget / openssl / xxd / jq / yq，`ENTRYPOINT ["/bin/bash"]`），被 initializer / precheck / prepare / postcheck 四个一次性服务复用，脚本从宿主机 `./scripts:/workspace` 挂载。

| 服务 | 镜像 | 宿主端口 | profile |
| --- | --- | --- | --- |
| nacos | `higress/nacos-server` | 8888→8080 控制台、8848、9848 | `nacos` |
| initializer / precheck / prepare / postcheck | `higress/runner` | — | 一次性 |
| apiserver | `higress/api-server` | 不映射（容器内 8443） | — |
| controller | 主仓 controller 镜像 | 不映射（健康 `:8888/ready`） | — |
| pilot | 主仓 pilot 镜像 | 不映射（健康 `:8080/ready`，`--monitoringAddr=:15014`） | — |
| gateway | 主仓 gateway 镜像 | 80、443、15020 | — |
| plugin-server | wasm 插件静态分发 | 不映射 | `plugin-server` |
| console | `higress/console` | **8080**→8080 | — |
| prometheus / promtail / loki / grafana | 观测四件套 | 均未映射宿主端口（Prometheus retention 6h） | — |

默认 `COMPOSE_PROFILES='nacos,plugin-server'`、`CONFIG_STORAGE='nacos'`，即默认真正常驻 ≈ **10 个容器**。启动顺序完全由 `depends_on` 条件串起来：precheck(`service_completed_successfully`) → apiserver(`service_healthy`) → prepare(completed) → controller(healthy) → pilot(healthy) → gateway + plugin-server → console(healthy) → prometheus / loki → grafana，postcheck 再等全链 healthy。

`compose/scripts/` 四个脚本的分工很能说明这套形态的性质：`precheck.sh`（64 行）用 **openssl 现生成 CA / server / client 三张证书**并写 kubeconfig；`init.sh`（238 行）登录 Nacos 取 accessToken、建命名空间；`prepare.sh`（774 行）**用 curl 直写 apiserver 来初始化 CR**——McpBridge、`nacos-auth-default` Secret、ConfigMap `higress-config`、GatewayClass / Gateway、prometheus.yaml；`postcheck.sh` 全文两行，echo 一句 "All good!"。controller 的启动参数也在这里可见：`serve --kubeconfig=... --gatewaySelectorKey=higress --gatewaySelectorValue=higress-system-higress-gateway --ingressClass= --enableAutomaticHttps=true`（`:125-133`）——注意 `--enableAutomaticHttps=true` 与主仓的 flag 默认值 false 相反（见 [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)）。

## All-in-One

`all-in-one/Dockerfile` 是多阶段构建，把主仓 release 的四个镜像（controller / pilot / gateway / plugin-server）**按 sha256 digest 烘焙进同一个容器**，ARG 记录 `CORE_VERSION=2.2.5`、`CONSOLE_VERSION=2.2.5`、`ENVOY_VERSION=2.2.5`、`APISERVER_VERSION=0.1.0`；另外 COPY 进 apiserver 二进制、console 的 `/app`、JDK、wasm 插件与 **supercronic**，apt 装 supervisor / logrotate / cron / nginx，`EXPOSE 8080 8443 8001`，入口是 `supervisord -c .../supervisord.conf`。

`all-in-one/supervisord/supervisord.conf`（127 行，`nodaemon=true`）编排 **10 个 program，按 priority 依次拉起**：apiserver(0) → plugin-server(50) → controller(100) → pilot(200) → gateway(300) → console(900) → prometheus(2000) / promtail(2100) / loki(2200) / grafana(3000)。每个 program 的 stdout 落到 **`/var/log/higress/<name>.log`**——文档说的容器内日志目录属实。

**all-in-one 与 compose 的本质差别是存储：只有 file 后端、没有 Nacos。** `all-in-one/scripts/start-apiserver.sh` 把 `/opt/data/defaultConfig` 拷进 `/data`，可选手工跑 `config-template/{ai-gateway,ai-proxy}.sh`，从 ConfigMap 抽数据到 `/etc/istio/config`，最后起 `apiserver --bind-address 127.0.0.1 --secure-port 18443 --storage file --file-root-dir /data`；kubeconfig 是**烘焙进镜像的静态文件**（`all-in-one/apiserver/config`，server 指向 `https://localhost:18443`、`insecure-skip-tls-verify: true`）。端口也不同：`start-controller.sh` 里 `GATEWAY_HTTP_PORT` 默认 **8080**、`GATEWAY_HTTPS_PORT` 默认 **8443**（compose 形态是 80 / 443），`USE_PLUGIN_SERVER=on` 时 MCP 插件地址指向 `http://localhost:8002/plugins/mcp-server/2.0.3/plugin.wasm`（plugin-server 的 nginx 监听 8002）。

## Configuration Tooling

`bin/base.sh` 探测 docker 并**明确拒绝 Compose v1**；`bin/startup.sh` 要求 `compose/.configured` 标记存在（由 configure 写入）后 `docker compose up -d`；`logs.sh` / `status.sh` / `shutdown.sh` / `restart.sh` / `reset.sh` 都是薄封装。核心是 `bin/configure.sh`（822 行），参数全集在 case 块 `:85-191`：

| 参数 | 存在性 | 默认 |
| --- | --- | --- |
| `--gateway-http-port` / `--gateway-https-port` / `--gateway-metrics-port` | 真实存在 | 80 / 443 / 15020（all-in-one 形态下 HTTP 默认改 8080） |
| `--console-port` | 真实存在 | 8080 |
| `-k, --data-enc-key` | 真实存在 | 未设则随机生成（记 `NACOS_USE_RANDOM_DATA_ENC_KEY`），**长度约束 32 字符**，集群部署必须显式设 |
| `-c, --config-url` | 真实存在 | 无默认；`nacos://host:8848` 或 `file:///opt/higress/conf` |
| `--use-builtin-nacos` | 真实存在（`:104`） | 关；置位则 profile 含 nacos（而 `.env` 默认就含） |
| `-r/--rerun`、`-a/--auto-start`、`-s/--storage`、`--nacos-ns`（默认 `higress-system`）、`--nacos-username/-password`、`--nacos-port/--nacos-console-port(8888)/--nacos-service-port(8848)`、`--use-plugin-server/--no-plugin-server` | 真实存在，**文档未列** | 见 `compose/.env` |

它的实际动作是：解析参数 → **整文件重写 `compose/.env`**（`:669` 起，含 COMPOSE_PROFILES / CONFIG_STORAGE / NACOS_* / 全部镜像 tag / `WASM_PLUGIN_URL_PATTERN` / `MCP_SERVER_WASM_URL` / 观测 tag / 四个端口）→ 跑 initializer 容器 → 写 `.configured` → `-a` 时调 `startup.sh`。开 plugin-server 时写入的是模板串 `http://plugin-server:8080/plugins/${name}/${version}/plugin.wasm`，与主仓侧的内置插件镜像地址替换是同一个占位符约定（见 [Plugin System](/docs/CS/Framework/Higress/Plugin.md)）。

一个容易混的点：本仓也有 `src/get-higress.sh`（279 行），但它与主仓的 `get-higress.sh` **同名不同物**——本仓的是安装器，只认 `-h` 与 `-u/--update`（`:38/:42`），VERSION 为空时去 GitHub releases 取最新 tag（`:179-185`）再下载 tar 包解包（`:193`），平台白名单 darwin / linux / windows × amd64 / arm64；**上面那串端口与凭据参数它全不吃**。文档若不区分两仓两个同名脚本，读者会把参数用到错的脚本上。

## Release Pinning

`release-provenance.json`（schemaVersion 1）是这套形态的可复现性凭据：`release{version: v2.2.5, commit: 4deae1dd…, releaseId: 403180124}`（**主仓 commit 就是 `Release v2.2.5` 的 HEAD**）、`snapshot{path: plugins/release/snapshots/2.2.5.json, sha256}`（各镜像共享同一 snapshot digest）、`mcpServerVersion: 2.0.3`、`standaloneBaseCommit`、`idempotencyKey`，以及 `images[]` 五组 digest（controller / gateway / pilot / plugin-server / console，各含 linux/amd64 + arm64，console 另有独立 commit 与 releaseId **403158311**）。

钉版机制是 `tools/render_release_pins.py`：`render()` 要求十个键（gatewayVersion / consoleVersion / pluginServerVersion / mcpServerVersion / snapshotSha256 / idempotencyKey / standaloneBaseCommit / gatewayImages / pluginServerRef / pluginServerDigest），**回写四个文件**——`all-in-one/Dockerfile`、`compose/.env`、`bin/configure.sh`、`all-in-one/scripts/start-controller.sh`——并生成本文说的 provenance 文件（配套 `tools/release_evidence.py` 与两个自测脚本）。本仓**不按 tag 去拉主仓的 crd.yaml**，CRD 是复制进 `src/apiserver/pkg/storage/crds/` 的快照。

顺带把版本线这件事收口：**console 有自己的 release 线**。本仓三处（Dockerfile 的 `CONSOLE_VERSION`、`compose/.env` 的 tag、provenance）一致是 **2.2.5**，而主仓 `DEP_VERSION` 写的是 `higress-console: v2.1.9`；`aio-v2.2.5` 这个 tag 也是本仓独立的前缀线。第三方组件只钉到 tag 不到 digest（nacos `v3.0.1`、prometheus `v2.40.7`、loki/promtail `2.9.4`、grafana `9.3.6`、runner `0.0.3`、api-server `0.1.0`），**只有主仓四件套 + console 钉到 digest**。

## Testing Reality

`test/` 只有 configure 一套：`configure-test.sh` 先 `bin/reset.sh` 再逐 case 跑 `configure-test-runner.sh`（对 external-nacos 类 case 会起一个真 Nacos 容器，pin `v2.2.3`，EXIT trap 清理），`cases/` 下 31 个 `.inc` 覆盖 `args-*`（builtin / external × full / console-port / data-enc-key / gateway-metrics-port / gateway-service-ports / nacos-ns / nacos-password / console-password）与 `input-*`（交互式输入等价类，含 Windows 路径用例）。**本质是"参数解析 → `.env` 产物"的冒烟与回归**，全仓没有任何打网关流量的 e2e。

至于 FAQ 说的"离线部署需要自行构建"：**仓内找不到这句 FAQ 文字**，能佐证的是每个组件都有可独立构建的 Makefile（`src/apiserver/`、`src/runner/`、`all-in-one/` 的 docker-build / docker-buildx-push），但镜像默认全量指向公网 ACR 且仓库不提供离线导入工具——方向成立，不构成文档承诺。

## Unverified

`EXPOSE 8001` 的确切角色（nginx 插件服务在 8002，README 的 docker run 映射 8001，未找到 8001 的监听方配置）；`MODE=full|gateway|console` 的进程裁剪逻辑（`all-in-one/scripts/base.sh` 未展开）；wasmplugins / mcpbridges 的 CRD schema 在不进 `pkg/storage/crds/` 的情况下如何被 controller 与 console 取得；本仓 5 个静态 CRD 与主仓 `helm/core/crds/` 的覆盖差异；`bin/update.sh`（110 行）的升级语义；`nacos_rest.go` 里对象序列化格式（flat / legacy）的细节；console 端 `HIGRESS_CONSOLE_ACCESS_TOKEN` 的签发与校验机制（只记变量名）。

## Links

- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)

## References

- [higress-standalone 仓库](https://github.com/higress-group/higress-standalone)
- [基于 Docker Compose 进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker-compose/)
- [基于 Docker 容器进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker/)
- [通过阿里云计算巢快速部署](https://higress.ai/docs/latest/ops/deploy-by-aliyun-computenest/)
- [查看日志](https://higress.ai/docs/latest/ops/how-tos/view-logs/)
