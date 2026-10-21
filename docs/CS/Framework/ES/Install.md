## Introduction

本篇覆盖 Elasticsearch 的安装、目录结构、JVM 与堆、启动配置、节点角色、集群形成与插件管理。

**版本基线：Elasticsearch 9.5.5**（2026-10-06 发布，内置 Lucene 10.5.1）。本文所有默认值均标注 `文件:行号`，可回到源码反查。

> [!IMPORTANT]
> **先打破三个直觉**：① 9.x 自带的是 **OpenJDK 27**，不是 8.x 时代的 17，也不是广为流传的「最低 21」——21 只是外部 JDK 的门槛；② `http.port` 的默认值不是单个 `9200`，而是端口范围 `9200-9300`；③ `xpack.security.enabled` 在 8.x 起默认就是 `true`，「关掉安全才能跑」是老教程的过时做法。

事实来源：Elasticsearch 源码 v9.5.5（`elastic/elasticsearch` 仓库 tag `v9.5.5`）。

## 安装与目录结构

解压 tar/zip 即得（源码依据 `distribution/archives/build.gradle:17-86`）：

| 目录 | 内容 |
| ---- | ---- |
| `bin/` | `elasticsearch`（主入口，Linux 上 exec 原生 launcher）、`elasticsearch-plugin`、`elasticsearch-cli`、`elasticsearch-keystore`、`elasticsearch-node`、`elasticsearch-shard`、`elasticsearch-env` 等 |
| `config/` | `elasticsearch.yml`、`jvm.options`、空的 `jvm.options.d/` |
| `jdk/` | 自带 JDK（macOS 为 `jdk.app`），`bin/elasticsearch` 默认使用它 |
| `lib/` | jar 与 `lib/tools/`（server-cli、plugin-cli、keystore-cli、security-cli、java-version-checker 等 CLI 工具） |
| `logs/`、`plugins/` | 初始为空 |
| `modules/` | 33 个随发行版打包的内置模块（见「插件与模块」） |
| `data/` | **安装包里没有**，运行时创建于 `$ES_HOME/data`（`server/.../env/Environment.java:102`） |

### Bundled JDK：27

`build-tools-internal/version.properties:5`：

```properties
bundled_jdk_vendor = openjdk
bundled_jdk = 27+35@55ce5470a6294008af0057ff4626d0e5
```

只有在显式设置 `ES_JAVA_HOME` 时才会校验外部 JDK 版本，门槛是 **21**（`distribution/tools/java-version-checker/.../JavaVersionChecker.java:28` `MIN_VERSION = 21`）。`JAVA_HOME` 会被**显式忽略并告警**，应用 `ES_JAVA_HOME`（`distribution/src/bin/elasticsearch-env:36-46,71-73`）。

## JVM 与堆

### jvm.options 与 ES_JAVA_OPTS

9.x 仍同时支持两种定制方式（`distribution/src/config/jvm.options`、`distribution/tools/server-cli/.../JvmOptionsParser.java:195-200`）：

- `config/jvm.options` + `config/jvm.options.d/`（把片段文件丢进该目录即可，优先级高于主文件）；
- 环境变量 `ES_JAVA_OPTS`，内容**追加**到最终 JVM 参数（`JvmOptionsParser.java:98,144-146`）。

`JAVA_TOOL_OPTIONS` / `_JAVA_OPTIONS` / `JAVA_OPTS` 均被忽略（`elasticsearch-env:61-79`），这是为了避免与 JVM 自身机制叠加导致参数打架。

### 堆：自动配置，上限 31GB

9.x 的 `jvm.options` **不再写死 `-Xms/-Xmx`**，改由启动器按机器内存自动计算（`distribution/tools/server-cli/.../MachineDependent.java`）：

- DATA 节点：机器内存 > 1GB 时取 **50%**，但封顶 **31GB**（`MachineDependentHeap.java:37` `MAX_HEAP_SIZE = GB * 31`，`:128-143`）；
- MASTER_ONLY 节点：60%，同样封顶 31GB。

**31GB 这个数字不是 32GB**：JVM 压缩普通对象指针（compressed oops）在堆超过约 32GB 时失效，留 1GB 余量保证指针压缩始终开启。运行时是否启用压缩指针可在 `GET /_nodes/filtered` 的 `using_compressed_ordinary_object_pointers` 看到（`server/.../monitor/jvm/JvmInfo.java:429`）。

> [!TIP]
> 「堆给到 32GB」是过时建议。9.x 自动配置下根本不需要手动设 `-Xmx`；确需覆盖时用 `ES_JAVA_OPTS="-Xms31g -Xmx31g"`。

## 启动配置默认值

以下默认值全部来自源码 Setting 定义（相对路径 `server/src/main/java/`）：

| 配置项 | 默认值 | 定义处 |
| ---- | ---- | ---- |
| `cluster.name` | `elasticsearch` | `org/elasticsearch/cluster/ClusterName.java:24` |
| `node.name` | 无默认；缺省取 `HOSTNAME` 环境变量 | `org/elasticsearch/node/Node.java:122`、`org/elasticsearch/common/cli/EnvironmentAwareCommand.java:110` |
| `http.port` | `9200-9300`（端口范围，取区间内第一个空闲端口） | `org/elasticsearch/http/HttpTransportSettings.java:78-80` |
| `transport.port` | `9300-9399` | `org/elasticsearch/transport/TransportSettings.java:57` |
| `discovery.type` | `multi-node`（合法值仅 `multi-node` / `single-node`） | `org/elasticsearch/discovery/DiscoveryModule.java:68-75` |
| `network.host` | 无默认；未设置时绑定 `_local_`（loopback） | `org/elasticsearch/common/network/NetworkService.java:28-30` |
| `path.data` / `path.logs` | 无 Setting 默认；运行时 `$ES_HOME/data`、`$ES_HOME/logs` | `org/elasticsearch/env/Environment.java:42-43,102,123` |
| `discovery.seed_hosts` | 未设置时为本机默认地址（文档记载 `127.0.0.1`、`[::1]`） | `org/elasticsearch/discovery/SettingsBasedSeedHostsProvider.java:34-47` |
| `xpack.security.enabled` | `true` | `x-pack/plugin/core/.../XPackSettings.java:59-60` |

### 单机开发配置

```yaml
# config/elasticsearch.yml
cluster.name: es
node.name: node0
discovery.type: single-node   # 禁止与 cluster.initial_master_nodes 同用
xpack.security.enabled: false # 仅开发环境；生产保持默认 true
```

`discovery.type: single-node` 下**不允许**再配 `cluster.initial_master_nodes`（`org/elasticsearch/cluster/coordination/ClusterBootstrapService.java:82-93`）。首次启动会自动生成 Kibana 系统账号等内置账号的密码并打印到日志（`auto_security_configuration` 相关输出）。

### 多机集群启动

```shell
bin/elasticsearch -E cluster.name=es -E node.name=node0 -E path.data=node0_data
bin/elasticsearch -E cluster.name=es -E node.name=node1 -E path.data=node1_data
bin/elasticsearch -E cluster.name=es -E node.name=node2 -E path.data=node2_data
```

**必须有主节点选举意识**：前两个节点会各自等待对方形成法定人数，可能出现「等一会儿才加入集群」的现象，属正常 bootstrap 流程而非故障。

## 节点角色

9.5.5 的合法角色定义在 `org/elasticsearch/cluster/node/DiscoveryNodeRole.java:145-271`，共 14 个：

| 角色 | 缩写 | 存数据 | 默认启用 |
| ---- | ---- | ---- | ---- |
| `master` | m | 否 | 是 |
| `data` | d | 是 | 是（非 stateless 模式） |
| `data_content` / `data_hot` / `data_warm` / `data_cold` / `data_frozen` | s/h/w/c/f | 是 | 随 `data` 角色连带启用 |
| `ingest` | i | 否 | 是 |
| `ml` | l | 否 | 是 |
| `transform` | t | 否 | 是 |
| `remote_cluster_client` | r | 否 | 是 |
| `voting_only` | v | 否 | **否**（须同时为 master-eligible） |
| `index` | I | 是 | 仅 stateless 模式 |
| `search` | S | 是 | **否** |

默认角色集合由 `org/elasticsearch/node/NodeRoleSettings.java:20-35` 决定 = 所有 `isEnabledByDefault` 为 true 的角色，即默认节点是「master + data（全套 data_*）+ ingest + ml + transform + remote_cluster_client」的合体。

> [!WARNING]
> **`node.master: true` / `node.data: false` / `node.ingest` / `node.ml` 这些布尔配置在 9.x 已被移除**（`server/src/main` 对这些字符串零命中，唯一 `node.data` 是 `_cat` API 的列别名）。角色裁剪统一走 `node.roles: [master, ingest]` 列表。7.9 之前的老教程整段作废。

## 集群形成与主节点选举

9.x 的选举实现位于 `org/elasticsearch/cluster/coordination`（`Coordinator.java`、`PreVoteCollector.java`、`Reconfigurator.java`），已无 Zen1 的任何痕迹：

- `cluster.initial_master_nodes`：引导投票配置（`ClusterBootstrapService.java:49-52,242-255`），仅在「发现节点数 × 2 > 需求数」时才真正触发 bootstrap（`:198-200`）；
- `cluster.auto_shrink_voting_configuration`：默认 **true**，自动收缩投票配置保持至少 3 个可投票节点、容忍 1 节点离线（`Reconfigurator.java:49-54`）；
- `discovery.unconfigured_bootstrap_timeout`：默认 **3s**，未配置 seed 时尽力 bootstrap 的等待上限（`ClusterBootstrapService.java:54-59`）。

> [!WARNING]
> **`discovery.zen.minimum_master_nodes`（`minimum_master_nodes`）已从源码中移除**：全仓唯一命中是客户端 sniffer 的测试 fixture，无 Setting 定义、无消费方。防脑裂由投票配置（法定人数）自动保证，**不再需要（也不能）手动配置最小主节点数**——所有还在教你配 `minimum_master_nodes` 的资料都是 7.x 以前的。

## 插件与模块

安装官方插件走 `bin/elasticsearch-plugin`，仓库地址硬编码在 `distribution/tools/plugin-cli/.../InstallPluginAction.java:398`（`https://artifacts.elastic.co/downloads/elasticsearch-plugins/%s`）：

```shell
bin/elasticsearch-plugin list
bin/elasticsearch-plugin install analysis-icu   # 中文/ICU 分词
bin/elasticsearch-plugin remove analysis-icu
```

`modules/` 与 `plugins/` 是两个不同层级：**modules 随发行版打包**（9.5.5 共 33 个，含 `analysis-common`、`lang-painless`、`reindex`、`ingest-common`、`mapper-extras`、`parent-join`、`repository-s3/gcs/azure`、`data-streams`、`streams` 等），**plugins 需单独安装**（`analysis-icu`、`analysis-smartcn` 等在官方 `plugins/` 目录发布）。matrix-stats 聚合在 `modules/aggregations` 内，不存在独立的 `aggs-matrix-stats` 模块。

## 版本与升级基线

- `Version.CURRENT = V_9_5_5`（`server/.../Version.java:294`）；
- **8.19.0 是 9.x 的最低互通版本**：`server/src/main/resources/transport/constants/minimum_compatible.csv:1` 为 `8841000`，即 9.5.5 节点可与 8.19.0+ 节点组成集群做滚动升级；
- 索引兼容基线为 8.0.0：`server/.../index/IndexVersions.java:325` `MINIMUM_COMPATIBLE = V_8_0_0`，7.x 及更早创建的索引不能直接被 9.x 打开；
- 9.5.5 源码中**未查到** 10.x 分支的任何证据（最新 GA 线即 9.5.x）。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 「ES 自带 JDK 17，最低要求 21」 | bundled JDK 是 **OpenJDK 27**；21 仅是 `ES_JAVA_HOME` 指定外部 JDK 时的最低门槛 |
| `http.port` 默认 9200、`transport.port` 默认 9300 | 默认是**范围** `9200-9300` 与 `9300-9399`，取区间内第一个空闲端口 |
| `-Xmx32g` 官方推荐 | 自动堆计算封顶 **31GB**（`MachineDependentHeap.java:37`），为压缩指针留余量 |
| `node.master` / `node.data` 布尔配置 | 已移除，用 `node.roles` 列表 |
| `minimum_master_nodes: 2` 防脑裂 | 已移除，投票配置自动保证法定人数 |
| `bin/elasticsearch-users` / `elasticsearch-certutil` / `elasticsearch-setup-passwords` | 9.5.5 的 `bin/` 下**没有这些脚本**（官方文档目录仍留着滞后描述，实际产物里不存在） |
| 装完就有 `data/` 目录 | 安装包不含 `data/`，运行时创建 |
| 用 `JAVA_HOME` 指定 JDK | 被忽略并告警，应用 `ES_JAVA_HOME` |
| 8.x 老配置直接升 9.x | 至少 8.19 才能与 9.x 互通；索引兼容下限 8.0.0 |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Cluster：集群、选举与查询两阶段](/docs/CS/Framework/ES/Cluster.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Troubleshooting：熔断器、OOM 与分片未分配](/docs/CS/Framework/ES/Troubleshooting.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)
- [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md)

## References

1. [Elasticsearch Reference - Setup](https://www.elastic.co/guide/en/elasticsearch/reference/current/setup.html)
2. [Elasticsearch Reference - Bootstrap Checks / Heap](https://www.elastic.co/guide/en/elasticsearch/reference/current/important-settings.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
