## Introduction

本篇讲 Elasticsearch 的分析（Analysis）体系：Analyzer 的组成、内置分词器清单、custom analyzer / normalizer 配置，以及中文分词的选型。

**版本基线：Elasticsearch 9.5.5**（Lucene 10.5.1）。结论均标注 `文件:行号`，可回源码反查。

> [!IMPORTANT]
> **先打破三个直觉**：① ES 的 `standard` analyzer **默认不带任何停用词**——「standard = standard tokenizer + lowercase + stop」的经典三段论在 ES 里是错的；② `[standard]` token filter 自 7.6.0 起**已移除**，老配置会直接报错；③ IK 分词器**不在 Elasticsearch 官方仓库**，官方中文方案是 `analysis-smartcn`（plugins 目录发布）。

事实来源：Elasticsearch 源码 v9.5.5（`elastic/elasticsearch` tag `v9.5.5`）。

## 概念澄清：Analyzer 与 Tokenizer

「分词器」一词在 ES 语境下同时指两个东西，必须分开：

- **Analyzer（分析器）**：完整的文本处理管线，输入字符串、输出词项（token）流；
- **Tokenizer（分词器）**：只管「按什么规则切词」，是 Analyzer 的一个组成部件。

Analyzer = `char_filter* → tokenizer → token_filter*`，三段职责（组装代码 `AnalyzerComponents.java:42-98`，应用顺序 `CustomAnalyzer.java:82-101`）：

| 部件 | 作用 | 例子 |
| ---- | ---- | ---- |
| Character Filter（0..n） | 切词前对原始字符串做预处理 | HTML 去标签（`html_strip`）、零宽字符 |
| Tokenizer（恰好 1 个） | 切词 | `standard`、`whitespace`、`keyword`、`ik_max_word` |
| Token Filter（0..n） | 对切出的词项流做变换 | `lowercase`、`stop`、`synonym`、`stemmer` |

索引时用 index analyzer，查询时用 search analyzer；同一个字段两者可以不同（生产常见做法：索引用小写+词干，查询更宽松）。

## 打假：standard analyzer 的停用词

`StandardAnalyzerProvider.java:22-29`：

```java
final CharArraySet defaultStopwords = CharArraySet.EMPTY_SET;
CharArraySet stopWords = Analysis.parseStopWords(env, settings, defaultStopwords);
int maxTokenLength = settings.getAsInt("max_token_length", StandardAnalyzer.DEFAULT_MAX_TOKEN_LENGTH);
standardAnalyzer = new StandardAnalyzer(stopWords);
```

ES 的 `standard` / `default` analyzer 是 Lucene `StandardAnalyzer` 的直接包装，而 **ES 侧传入的停用词默认是空集**。也就是说 Lucene jar 内部虽然存在 stop 组件，ES 默认配置下它不产生任何效果——「standard 会去掉 the/a/an」在 ES 里不成立，除非显式配 `stopwords`。

另一起移除事件：`[standard]` token filter 自 **7.6.0** 起被移除（`AnalysisModule.java:202-216`，配了直接抛 `The [standard] token filter has been removed.`），老索引 settings 会触发 BWC 警告。

## 内置 Analyzer 清单

注册机制：插件通过 `AnalysisPlugin` 的 `getAnalyzers` 等方法向 `AnalysisModule`（`AnalysisModule.java:251-279`）注册，索引级自定义组件由 `AnalysisRegistry` 从 `index.analysis.*` settings 解析。

- server 内置（`AnalysisModule.java:267-268`）：`default`、`standard`；
- `modules/analysis-common`（随发行版打包的 `CommonAnalysisPlugin.java:168-213`）：
  - 通用 7 个：`fingerprint`、`keyword`、`pattern`、`simple`、`snowball`、`stop`、`whitespace`
  - 语种 36 个：`arabic`、`armenian`、`basque`、`bengali`、`brazilian`、`bulgarian`、`catalan`、`chinese`、`cjk`、`czech`、`danish`、`dutch`、`english`、`estonian`、`finnish`、`french`、`galician`、`german`、`greek`、`hindi`、`hungarian`、`indonesian`、`irish`、`italian`、`latvian`、`lithuanian`、`norwegian`、`persian`、`portuguese`、`romanian`、`russian`、`serbian`、`sorani`、`spanish`、`swedish`、`turkish`、`thai`

char filter 无 Lucene 内置实现（`AnalysisModule.java:183-190` 注释明言），全部来自插件——`html_strip`、`mapping`、`pattern_replace` 等都在 `analysis-common`。

## Custom Analyzer 与 _analyze API

在索引 settings 里组装（`AnalysisRegistry.java:51,347,488`）：

```json
PUT /my_index
{
  "settings": {
    "analysis": {
      "char_filter": { "my_char": { "type": "html_strip" } },
      "tokenizer": { "my_tok": { "type": "standard", "max_token_length": 20 } },
      "filter": { "my_stop": { "type": "stop", "stopwords": ["the", "a"] } },
      "analyzer": {
        "my_analyzer": {
          "type": "custom",
          "char_filter": ["my_char"],
          "tokenizer": "my_tok",
          "filter": ["lowercase", "my_stop"]
        }
      }
    }
  }
}
```

用 `_analyze` 直接验证分词效果（入口 `RestAnalyzeAction.java:32-37`，请求体字段见 `AnalyzeAction.java:48-56`）：

```json
GET /my_index/_analyze
{ "analyzer": "my_analyzer", "text": "The <b>Quick</b> brown FOX." }
```

`tokenizer` 是必填项（`AnalyzerComponents.java:50-53`），漏配会在创建索引时直接报错。

## Normalizer：keyword 字段的分析器

`normalizer` 是 keyword 字段专用的 analyzer 变体（注册处 `AnalysisModule.java:274-279`，实现 `CustomNormalizerProvider.java:40-70`）：

- **不允许配 tokenizer**——底层固定用 keyword tokenizer（`AnalysisRegistry.java:754-759`），配了直接抛异常；
- char_filter 必须是 `NormalizingCharFilterFactory` 子类，filter 必须是 `NormalizingTokenFilterFactory` 子类（即只允许不改变词数量的变换）；
- 内置仅 `lowercase` 一个（`LowercaseNormalizerProvider.java:23-26`）。

典型用途：keyword 字段大小写不敏感匹配（如邮箱、状态码）。

```json
PUT /my_index
{
  "settings": { "analysis": { "normalizer": { "lower": { "type": "custom", "filter": ["lowercase"] } } } },
  "mappings": { "properties": { "email": { "type": "keyword", "normalizer": "lower" } } }
}
```

## search_analyzer 与默认回退

`TextParams.java:61-92` 定义的回退链：

- `search_analyzer` 未显式配置时：先找名为 `default_search` 的 analyzer（`AnalysisRegistry.java:55`），找不到就**回退到 index analyzer**；
- `search_quote_analyzer`：未配置时找 `default_search_quoted`，再回退到 search_analyzer。

即：**默认情况下查询用的就是索引时同一个 analyzer**；只有在 settings 里定义了 `index.analysis.analyzer.default_search`（或 `default_search_quoted`）才会分别生效——这是一个只在索引级 settings 里「按名字认领」的约定，没有额外开关。

## 中文分词选型

| 方案 | 位置 | 说明 |
| ---- | ---- | ---- |
| `standard` | server 内置 | Unicode 文本分段标准（UAX#29），对中文按单字/二元切，语义弱 |
| `cjk` | `analysis-common` | 对 CJK 按二元组（bigram）切，召回高但精度差 |
| `chinese`（smartcn） | `plugins/analysis-smartcn`（需安装） | 官方基于 HMM 的中文分词，开箱可用 |
| `analysis-icu` | `plugins/analysis-icu`（需安装） | ICU 分词 + 排序/归一化/繁简等工具集 |
| IK（`ik_max_word` / `ik_smart`） | **社区插件，不在官方仓库** | 国内最常用；`modules/`、`plugins/`、`x-pack/` 全树零命中确认非官方 |

> [!WARNING]
> 两个位置陷阱：① `analysis-icu` 在官方 `plugins/` 目录，**不在 `modules/`**——`modules/` 下只有一个 `analysis-common`；② IK 需从社区发行版安装，且版本与 ES 小版本强绑定，升级 ES 前先确认 IK 有对应构建。日志场景可考虑免分词：整行当 keyword 或用 `cjk` bigram 换召回。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| standard 会去掉英文停用词 | 默认停用词是**空集**（`CharArraySet.EMPTY_SET`），不做任何过滤 |
| 配 `[standard]` token filter | 7.6.0 起移除，配了直接抛异常 |
| custom analyzer 可以省略 tokenizer | 必填，缺失即创建索引失败 |
| normalizer 能配 tokenizer | 禁止，底层固定 keyword tokenizer |
| `analysis-icu` 在 modules 目录 | 在 `plugins/`；`modules/` 下 analysis 只有 `analysis-common` |
| IK 是 ES 官方分词器 | 官方仓库不存在，社区插件 |
| 中文分词默认够用 | standard 对中文只做粗切；要语义分词装 smartcn/ICU 或社区 IK |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Query DSL：查询两阶段与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)

## References

1. [Elasticsearch Reference - Analysis](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis.html)
2. [Elasticsearch Reference - Configuring normalizers](https://www.elastic.co/guide/en/elasticsearch/reference/current/normalizers.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
