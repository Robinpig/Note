## Introduction

Logstash 的配置分三层：`logstash.yml`（进程级设置：队列、路径、日志、JVM 之外的一切）、`pipelines.yml`（一条进程跑几条管道）、`*.conf`（pipeline 本身的 input/filter/output）。执行模型与队列语义见 [Logstash_Pipeline](/docs/CS/Framework/ES/Logstash_Pipeline.md)，本篇讲配置项、目录布局、部署与调试。

> [!IMPORTANT]
> **版本基线：Logstash 9.5.5**（2026-10-06 发布）。以下默认值以 9.5.5 官方文档为准。

## logstash.yml

| 设置 | 默认值 | 说明 |
| ---- | ---- | ---- |
| `pipeline.workers` | CPU 核数 | filter+output 的 worker 线程数 |
| `pipeline.batch.size` | `125` | 单批最大事件数 |
| `pipeline.batch.delay` | `50`（ms） | 不满批时的等待上限 |
| `pipeline.ordered` | `auto` | workers=1 自动保序，多 worker 不保序 |
| `queue.type` | `memory` | `persisted` 启用持久化队列（PQ） |
| `path.settings` | 安装相关 | `logstash.yml`/`jvm.options` 所在目录 |
| `path.data` | `LOGSTASH_HOME/data` | PQ、DLQ 等持久化数据根目录 |
| `path.queue` | `path.data/queue` | PQ 数据文件目录 |
| `path.logs` | `LOGSTASH_HOME/logs` | 日志目录 |
| `config.reload.automatic` | `false` | 自动重载管道配置 |
| `config.reload.interval` | `3s` | 自动重载的检查间隔 |
| `log.level` | `info` | `fatal`/`error`/`warn`/`info`/`debug`/`trace` |
| `api.http.port` | `9600` | 监控 API 端口，需 `api.enabled: true` 才监听 |

PQ 与 DLQ 的细项（`queue.page_capacity`、`queue.checkpoint.*`、`dead_letter_queue.*`）见 [Logstash_Pipeline](/docs/CS/Framework/ES/Logstash_Pipeline.md)。

## Directory Layout

| 类型 | settings（yml/jvm.options） | pipeline 配置 | data | logs |
| ---- | ---- | ---- | ---- | ---- |
| tar/zip 自包含 | `{extract.path}/config` | `path.config` 指定 | `{extract.path}/data` | `{extract.path}/logs` |
| deb/rpm | `/etc/logstash` | `/etc/logstash/conf.d/*.conf` | `/var/lib/logstash` | `/var/log/logstash` |
| Docker | `/usr/share/logstash/config` | `/usr/share/logstash/pipeline` | `/usr/share/logstash/data` | 不落盘，输出 stdout |

deb/rpm 的 conf.d 读取顺序由 `pipelines.yml` 里的 `path.config`（目录或通配符）决定，同目录下按**文件名字母序**拼接，拆分配置文件时注意命名。

## Running on Docker

参考官方 [Running Logstash on Docker](https://www.elastic.co/guide/en/logstash/current/docker.html)：

```shell
docker run --rm -it --net elastic \
  -v /path/logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml \
  -v /path/logstash/config/logstash.conf:/usr/share/logstash/pipeline/logstash.conf \
  docker.elastic.co/logstash/logstash:9.5.5
```

关键点：`logstash.conf` 里 ES 的地址**不能用 `localhost`**——容器内的 localhost 指向 Logstash 容器自身，而不是宿主机或 ES 容器；应使用同一 docker 网络中的服务名（如 `http://elasticsearch:9200`）。镜像版本与 ES/Kibana 大版本对齐（9.5.x 内部互通，跨大版本有索引兼容下限）。另注意 **Docker 容器默认不写日志文件**，日志直接进 stdout，排障用 `docker logs`。

## JVM Heap

Logstash 跑在 JVM 上，堆在 `jvm.options`（或容器里的 `LS_JAVA_OPTS`）里配，打包默认 `-Xms1g -Xmx1g`：

- 常驻事件量约等于 `pipeline.workers × pipeline.batch.size`，大管道调大 batch 时堆要同步给，否则 GC 死亡螺旋；
- 生产建议 `-Xms` 与 `-Xmx` 相等，避免运行时扩堆的停顿；
- 容器内堆不要超过 cgroup 内存上限，JVM 默认按宿主机内存 sizing，在 limit 严格的容器里会被 OOM kill。

## Debugging

- 开发期把 output 临时设为 `stdout { codec => rubydebug }`，控制台逐条打印事件全字段，验证 grok 是否拆对；
- 上线前自检配置语法：`bin/logstash --config.test_and_exit -f logstash.conf`；
- 需要细节时 `--log.level debug`（或 `log.level: debug`），管道级指标用监控 API：`curl localhost:9600/_node/stats/pipelines?pretty`；
- grok 模式在线调试用 Kibana 的 **Grok Debugger**，见 [Kibana](/docs/CS/Framework/ES/Kibana.md)。

## Links

- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [logstash.yml Settings](https://www.elastic.co/guide/en/logstash/current/logstash-settings-file.html)
2. [Logstash Directory Layout](https://www.elastic.co/guide/en/logstash/current/dir-layout.html)
3. [Running Logstash on Docker](https://www.elastic.co/guide/en/logstash/current/docker.html)
