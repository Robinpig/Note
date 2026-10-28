## Introduction

filter 是 Logstash 的重心：input 只负责把字节搬进来，output 只负责写出去，所有解析、富化、字段规整、条件路由都发生在 filter 阶段，逐事件执行。执行时序与批处理参数见 [Logstash_Pipeline](/docs/CS/Framework/ES/Logstash_Pipeline.md)，本篇讲事件模型与常用 filter 插件。

> [!IMPORTANT]
> **版本基线：Logstash 9.5.5**。以下默认值与行为以 9.5.5 官方文档为准。

## Event Model

filter 操作的对象是一个类哈希的**事件（event）**：

- 元信息字段：`@timestamp`（事件时间，默认是 Logstash 收到的时间，`date` filter 负责修正）、`@version`、`host`、`tags`（数组）、`type`。
- 解析产出字段：grok 等插件捕获的具名字段，以及 `fields` 子哈希里的自定义键值对。
- **字段引用**：`[field]`、`[nested][sub]`；sprintf 格式 `%{field}`（如 `index => "app-%{+YYYY.MM.dd}"`）；比较时 `[tags][0] == "foo"`。
- **失败标记**：解析失败通常往 `tags` 追加专用标记（`_grokparsefailure`、`_dateparsefailure`、`_jsonparsefailure`），据此把坏数据分流到死信或旁路，见 [Logstash_Pipeline](/docs/CS/Framework/ES/Logstash_Pipeline.md) 的 DLQ。

**ECS（Elastic Common Schema）**：Elastic 推出的字段命名规范（`log.level`、`service.name`、`host.ip` 这类点分层级），目的是让不同来源的日志在 Kibana 里可联合检索。8.x 起 Filebeat 默认按 ECS 输出；Logstash 侧由 `pipeline.ecs_compatibility`（默认 `disabled`，`v1`/`v8` 为 beta）与各插件的 ecs_compatibility 选项控制。新链路建议直接对齐 ECS，避免后期回填。

## Grok

grok 用**带名字的正则模式**把非结构化文本拆成字段，是日志解析的核心：

```ruby
filter {
  grok {
    match => { "message" => "%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level} %{GREEDYDATA:msg}" }
  }
}
```

- 内置模式库覆盖常见模式（`TIMESTAMP_ISO8601`、`LOGLEVEL`、`IP`、`DATA`、`NUMBER`、`GREEDYDATA`…）；自定义模式放 `patterns_dir` 指定的目录。
- 关键选项：`break_on_match`（默认 `true`，首个匹配的模式即停）；`named_captures_only`（默认 `true`，只保留具名捕获）；`tag_on_failure`（默认 `["_grokparsefailure"]`）。
- 调试：Kibana 的 **Grok Debugger** 可以直接拿真实日志行在线试模式，比改完重启管道快一个数量级。

## Dissect

dissect 用**分隔符**切分，不跑正则：

```ruby
filter {
  dissect {
    mapping => { "message" => "%{ts} %{level} %{thread} %{msg}" }
  }
}
```

`%{+field}` 表示把分隔段追加进已存在的同名字段（跳过分隔符），适合 key=value 类格式。结构固定的日志优先用 dissect——比 grok 快一个量级；失败时打 `_dissectfailure`。

## Date

把字符串时间解析成事件的 `@timestamp`，否则 `@timestamp` 停留在"Logstash 收到这条数据"的时间，Kibana 时间线会整体失真：

```ruby
filter {
  date {
    match => ["ts", "ISO8601", "UNIX", "UNIX_MS"]
    target => "@timestamp"
  }
}
```

`match` 是数组，按序尝试；可配 `timezone`（源日志时区）与 `locale`。解析失败打 `_dateparsefailure`。

## Mutate

字段操作的螺丝刀，无解析能力但几乎每条管道都离不开：

```ruby
filter {
  mutate {
    rename  => { "src_ip" => "client.ip" }
    convert => { "port" => "integer", "bytes" => "integer" }
    add_field => { "service" => "gateway" }
    remove_field => ["message", "agent.ephemeral_id"]
    gsub => ["message", "\r", ""]
  }
}
```

覆盖 `rename`/`update`/`replace`/`convert`/`uppercase`/`lowercase`/`strip`/`split`/`join`/`gsub`/`merge`/`add_field`/`remove_field`。`convert` 决定字段进 ES 的映射类型（string vs integer 冲突是 mapping 报错的常见来源）。

## JSON

`json` filter 解析 JSON 日志行（JSON lines 场景），区别于 input 上的 `codec => json`——filter 只处理指定字段，可与其它 filter 组合：

```ruby
filter {
  json { source => "message" target => "parsed" }
}
```

解析失败打 `_jsonparsefailure`。

## GeoIP

按 IP 补地理位置字段，依赖 MaxMind GeoLite2 数据库（需自行定期更新）：

```ruby
filter {
  geoip { source => "client.ip" target => "geoip" }
}
```

产出 `geoip.city_name`、`geoip.country_iso_code`、`geoip.location`（经纬度）等字段，可直接用于 Kibana 地图。ECS 兼容模式下字段名以插件版本为准。

## Ruby

内嵌 Ruby 做插件表达不了的复杂逻辑：

```ruby
filter {
  ruby {
    code => "event.set('env', 'prod') if event.get('host.name') =~ /^web-/"
  }
}
```

能用 mutate/grok 解决的就不要用 ruby——每条事件一次 Ruby 求值的 CPU 与稳定性代价都很高，是吞吐问题的常见嫌疑人。

## Conditionals

`if/else if/else` 做条件路由，是"一条管道分流多类日志"的基础：

```ruby
filter {
  if [level] == "ERROR" or "error" in [tags] {
    mutate { add_tag => ["alert"] }
  } else if [type] == "access" {
    drop { }
  } else {
    mutate { remove_field => ["debug_payload"] }
  }
}
```

支持 `==` `!=` `<` `>` `<=` `>=` `=~` `!~`（正则）与 `and`/`or`/`not`/`xor`，数组成员判断用 `in`/`not in`。条件表达式出错（如字符串与整数比较）会把事件送进 DLQ。

## Performance Notes

filter 阶段的经验排序：

1. **先便宜后昂贵**：`include_lines`/`mutate remove_field` 这类尽早减负，grok/geoip/ruby 放后面，让不该进管道的日志提前 drop。
2. **能用 dissect 不用 grok**：固定分隔符场景性能差一个量级。
3. **grok 模式求精**：`GREEDYDATA` 一把梭省事但回溯昂贵；锚定行首行尾、避免嵌套量词。
4. **date 只配一次**：多管道重复解析同一时间字段是纯浪费。
5. **删字段即省带宽与存储**：`remove_field` 掉的字段不会进 ES，直接降低索引体积。
6. **重解析下沉**：单文件场景的解析优先放 Filebeat `parsers` 或 ES ingest pipeline，少一层 JVM 进程；Logstash 留给跨源汇聚与复杂路由。

## Links

- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)

## References

1. [Filter plugins](https://www.elastic.co/guide/en/logstash/current/filter-plugins.html)
2. [Grok filter plugin](https://www.elastic.co/guide/en/logstash/current/plugins-filters-grok.html)
3. [Dissect filter plugin](https://www.elastic.co/guide/en/logstash/current/plugins-filters-dissect.html)
4. [Date filter plugin](https://www.elastic.co/guide/en/logstash/current/plugins-filters-date.html)
5. [Mutate filter plugin](https://www.elastic.co/guide/en/logstash/current/plugins-filters-mutate.html)
6. [Elastic Common Schema (ECS)](https://www.elastic.co/guide/en/ecs/current/ecs-reference.html)
