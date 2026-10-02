## Introduction

Kibana 是 Elastic Stack 的**可视化与交互前端**，为存储在 [Elasticsearch](/docs/CS/Framework/ES/ES.md) 中的数据提供查询、检索、图表、仪表盘与运维管理界面。它本身不存数据，所有查询最终都翻译成对 ES 的 REST 请求；也常被当作 ES 的“图形化管理控制台”使用。

在典型日志链路 `Beats/Logstash -> ES -> Kibana` 中，Kibana 是数据被人消费和分析的终点。它与 ES 版本**强绑定**，大版本通常需要与 ES 对齐（如都用 8.15.x），否则可能不兼容。

## Core Apps

| 模块 | 作用 |
| ---- | ---- |
| Discover | 交互式检索与浏览文档，选择 data view、写查询、看 `_source`、按时间过滤、看文档上下文 |
| Dashboard | 把多个可视化面板组合成仪表盘，支持筛选、 drill-down、分享 |
| Visualize / Lens | 构建折线/柱状/饼/指标/数据表等图表；Lens 提供拖拽式可视化 |
| Maps | 地理空间数据可视化（geo_point / geo_shape） |
| Canvas | 报告式、像素级排版的数据展示页 |
| Dev Tools | **Console** 直接写 DSL/REST 请求调试 ES；还有 Profiler、Grok Debugger |
| Stack Management | 索引策略、快照、ingest pipeline、用户角色（RBAC）、data view、saved objects |
| Alerting / Rules | 基于查询或指标阈值配置告警与连接器（发邮件/Webhook/钉钉等） |
| APM / Uptime / Security / Observability | 对接 APM、Heartbeat、安全事件等专项解决方案的应用 |

## Data View and Querying

- **Data View（旧称 Index Pattern）**：先用通配模式（如 `filebeat-*`、`orders-*`）告诉 Kibana 要分析哪些索引，并指定时间字段；它是 Discover/Visualize 的数据入口。
- 查询语言默认是 **KQL（Kibana Query Language）**，语法简单，如 `status: >=500 and service: order`；也可切换为 [Lucene](/docs/CS/Framework/ES/Lucene.md) 查询语法。KQL 只在 Kibana 搜索框使用，真正的请求体仍可下钻为 ES Query DSL。
- 顶部全局时间选择器 + 自动刷新，是实时日志/监控看板的常用操作。

## Install

Kibana 需要连接一个可达的 Elasticsearch，通过 `kibana.yml` 的 `elasticsearch.hosts` 指向 ES（8.x 默认开启安全，需配 `elasticsearch.serviceAccountToken` 或用户名密码）。

Docker 启动（与主笔记 ES 8.x 单节点、关闭安全的开发环境配套）：

```shell
docker run -d --name kibana \
  -p 5601:5601 \
  -e ELASTICSEARCH_HOSTS=http://elasticsearch:9200 \
  docker.elastic.co/kibana/kibana:8.15.3
```

```yaml
# config/kibana.yml
server.port: 5601
server.host: "0.0.0.0"
elasticsearch.hosts: ["http://elasticsearch:9200"]
# ES 开启安全时：
# elasticsearch.username: "kibana_system"
# elasticsearch.password: "xxxx"
```

启动后访问 `http://localhost:5601`。注意 Kibana 与 ES 大版本应保持一致；ES 侧 `xpack.security.enabled=false` 时 Kibana 无需登录。

## Tips

- 调试 DSL 首选 **Dev Tools → Console**，自带自动补全和格式化，比手写 curl 高效。
- Grok/正则解析可用 **Grok Debugger** 在线验证，配合 [Logstash](/docs/CS/Framework/ES/Logstash.md) / ingest pipeline 使用。
- 大量历史索引用 **Index Lifecycle Management（ILM）** 做滚动与冷热分层，避免在 Kibana 看板上查无限增长的索引（主笔记提到的“缩短调用链保存时间降数据量”即此类治理）。
- Saved Objects（看板/可视化/查询）支持导出导入做备份与环境迁移；Spaces 用于多团队隔离。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Beats](/docs/CS/Framework/ES/Beats.md)
- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Lucene](/docs/CS/Framework/ES/Lucene.md)
- [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md)

## References

1. [Kibana Guide](https://www.elastic.co/guide/en/kibana/current/index.html)
2. [Kibana Query Language (KQL)](https://www.elastic.co/guide/en/kibana/current/kuery-query.html)
3. [Kibana Docker Quick Start](https://www.elastic.co/guide/en/kibana/current/docker.html)
