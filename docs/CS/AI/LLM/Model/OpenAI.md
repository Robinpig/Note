## Introduction

> **版本基线：2026-10-05 核实。** 型号、上下文与价格以 [OpenAI API 定价页](https://developers.openai.com/api/docs/pricing) 与各模型页为准；弃用时间以 [Deprecations 页](https://developers.openai.com/api/docs/deprecations) 为准。`developers.openai.com` 对部分地区与自动化请求返回 403，下文数据经官方页面快照与官方 changelog 交叉核对。

[OpenAI](https://openai.com) 的 API 产品线到 2026 年 10 月已经是「一个旗舰 + 两个廉价档 + 一条前代线 + 一堆专用模型」的形状。旗舰是 **GPT-6 Astra**，往下是 2026-09-22 发布的 **GPT-6 Sol** 与 **GPT-6 Luna**，2026-09-29 又补了 **GPT-6.1 Sol**——一个把 Astra 级能力压到 Sol 价格的修订版。三代 GPT-6 的技术包络完全一致（1.05M上下文、128K 最大输出、文本+图像输入），**差异全在价格与推理档位**。

和 DeepSeek 的对比见 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)，横向选型见 [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)，Claude 侧见 [Claude](/docs/CS/AI/LLM/Model/Claude.md)。

## GPT-6 家族

| 模型 | API ID | 发布 | 输入 | 缓存输入 | 缓存写入 | 输出 | 知识截止 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| GPT-6 Astra | `gpt-6-astra` | 2026-09-03 | $10 | $1 | $12.50 | $50 | 2026-04-30 |
| GPT-6.1 Sol | `gpt-6.1-sol` | 2026-09-29 | $2 | $0.10 | $2.50 | $10 | 2026-04-30 |
| GPT-6 Sol | `gpt-6-sol` | 2026-09-22 | $2 | $0.20 | $2.50 | $10 | 2026-04-20 |
| GPT-6 Luna | `gpt-6-luna` | 2026-09-22 | $0.10 | $0.01 | $0.125 | $0.50 | 2026-05-18 |

单位均为美元／百万 token，均为 ≤272K 短上下文的标准档。

几个容易踩的点：

- **GPT-6.1 Sol 不是 GPT-6 Sol 的别名，而是同价不同缓存价的独立模型**。两者输入与输出同价（$2／$10），但 6.1 的缓存输入是 $0.10，比 Sol 的 $0.20 **便宜一半**。`gpt-6-sol` 的模型页现在直接写着「See GPT-6.1 Sol for the newer Sol model」——新项目没理由再用Sol。
- **`gpt-6-astra` 只有一个快照**，模型页的 Snapshots 列表里别名与快照同名。写死版本号不会帮你锁到任何东西。
- **Astra 不支持 `reasoning.effort: "none"`**，Sol 与 Luna 支持（默认 `medium`）。这是从 Sol 迁到 Astra 时最容易踩的一个 400。推理档位都是 `none / low / medium / high / xhigh / max` 这一套，只是 Astra 少一档。
- **Chat Completions 上要用内置工具必须把 `reasoning_effort` 设成 `none`**；工具调用（web search、file search、code interpreter、computer use、MCP、hosted shell）都只在Responses API 上可用。
- **GPT-6 Luna 的知识截止（2026-05-18）比 Astra（2026-04-30）还新**。这不是笔误——三个 GPT-6 模型的截止日期各不相同，做 RAG 时别按旗舰的截止日期推断全系。

**GPT-6.1 Sol 是 2026-09-29 DevDay 的头条**，OpenAI 定位为「near-Astra performance at one-fifth cost」，并首次支持 **Multi-agent（beta）**：在一次 Responses API 请求里让模型把工作委派给子智能体。发布材料给出的口径是：DeepSWE v1.1 上追平 Astra，在更低 effort 下比 GPT-6 Sol 的最佳成绩高 6.4 个百分点；GDP.pdf 上任务成本不到 Claude Opus 5.5 的一半而结果更好；AutomationBench（medium effort）比 Opus 5.5 高 2.2 个百分点、成本约其三分之一；OSWorld 2.0（离线，max effort）比 GPT-6 Sol 高 7 个百分点、成本不足其一半。这些都是 OpenAI 自报数。

## 长上下文是台阶不是斜坡

这是 OpenAI 定价里最容易被漏掉的一条：

> **单个请求的 input 超过 272K token，整个请求按长上下文价计费**——input 与缓存费率×2，输出 ×1.5。缓存写入同样按2 倍算。

Astra 因此变成 $20／$2／$25／$75，Sol 与 Luna 同理翻倍。这个 272K 线不是 GPT-6 新增的，GPT-5.6 Sol 就有同样的线，但 Astra 把线后面的数字抬高了一倍。

算一下就知道台阶的杀伤力：一次 900K token 的 prompt 在 Astra 上，光输入就$18，模型还没吐出第一个字符；同样的 prompt 发给 GPT-6 Sol 是 $7.20。**做仓库级审计、全量文档喂入、长对话 agent 这类天然越过 272K 的负载，模型选型比缓存优化更重要**；反过来，RAG 与分类抽取这类短 prompt 负载，台阶永远踩不到，可以完全忽略这一节。

缓存的杠杆在这一档更值钱：Astra 缓存输入 $1 是标准 input 的十分之一，缓存写入 $12.50 是未缓存 input 的 1.25 倍。**稳定前缀复用率超过78% 才回本**——因为写一次要 1.25 倍，读多次才 0.1 倍。用一次的 prefix 去缓存是纯亏。

## 服务层级 Batch Flex Fast Ultrafast

同一批模型有四档计费方式，倍率是叠加在标准价上的：

| 层级 | Astra 输入 | Sol / 6.1 输入 | Luna 输入 | 说明 |
| :--- | :---: | :---: | :---: | :--- |
| Standard | $10 | $2 | $0.10 | 基准 |
| Batch | $5 | $1 | $0.05 | 半价，异步 |
| Flex | $5 | $1 | $0.05 | 半价，灵活时窗 |
| Fast mode | $20 | $4 | $0.20 | 双倍，最快约 2.5× |

- **`service_tier: "priority"` 在 2026-07-30 被改名为 `service_tier: "fast"`**，两个值都仍被 API 接受。但API 响应、用量报表与账单里，这一档仍显示为 `priority`——只有 GPT-5.6 之后发布的模型才会显示新名字。所以看到账单写 priority 不要以为配置没生效。
- **Fast mode 于 2026-08-05 起支持长上下文**（>272K 的请求也能走 Fast mode），此前不支持。
- **2026-09-29 新增 `service_tier: "ultrafast"`**，目前只对 `gpt-6-astra` 开放，用于压缩输出 token 之间的间隔。仅支持全球处理与美国数据驻留，**不支持 EU 等区域推理驻留**。对应的 ChatGPT 侧是 $500/月 的 Pro 500 计划。
- **Batch 与 Flex 同为半价且可与缓存折扣叠加**。延迟不敏感的离线任务（批量分类、打标、摘要）应该默认走Batch。

## 区域处理与数据驻留

> **对2026-03-05 及之后发布、且符合数据驻留条件的模型，区域处理（data residency）端点加价10%。**

这条只影响 GPT-6 全系与 GPT-5.6 全系，老模型不在政策口径内。加价是乘数，会同时放大 input、缓存读写与 output 各项费率。

两个容易误读的点：

- **「存储在区域内」不等于「在区域内推理」**。OpenAI 的区域表里只有美国与欧洲（EEA+瑞士）同时提供存储与区域处理；澳大利亚、加拿大、日本、印度、新加坡、韩国、英国都只提供存储，处理仍在境外。合规文档里写「数据留在澳大利亚」是半真。
- **GPT-6 Astra / Sol / Luna 的 EU 数据驻留只在 Standard 层级可用**，Fast mode 与 Flex 的 EU 区域处理不支持。如果既要EU 驻留又要低延迟，只能接受 Standard 费率。

OpenAI 模型在 AWS Bedrock 上通过 AWS 计费，商用区域价格与 OpenAI 直连一致；Azure 上是另一套部署形态（Global／Data Zone／Regional），不适用本页任何数字。

## o 系列的退场

o 系列（o1、o1-pro、o3-mini、o4-mini）**已经在退场倒计时中，且功能上被GPT-5.6／GPT-6 的 `reasoning.effort` 完全取代**——不再有独立的「推理模型」这条产品线。

| 型号 | 关停日期 | OpenAI 给的替代 |
| :--- | :--- | :--- |
| `o1`、`o1-2024-12-17` | 2026-10-23 | `gpt-5.6-sol` |
| `o1-pro`、`o1-pro-2025-03-19` | 2026-10-23 | `gpt-5.6-sol`（`reasoning.mode: pro`） |
| `o3-mini`、`o3-mini-2025-01-31` | 2026-10-23 | `gpt-5.6-sol` |
| `o4-mini`、`o4-mini-2025-04-16` | 2026-10-23 | `gpt-5.6-terra` |
| `ft-o4-mini-2025-04-16` | 2026-10-23 | `gpt-5.6-terra` |
| `o3`、`o3-pro` | 2026-12-11 | `gpt-5.6-sol` |

`o3` 已于 2026-08-26 从 ChatGPT 下线，`o4-mini` 与 GPT-4o 全系、GPT-4.1 nano、GPT-4 Turbo、原始 GPT-4、GPT-3.5 Turbo 同批在 2026-10-23 关停。**用 o3-mini / o4-mini / GPT-4o 之类快照名做细粒度锁定的代码会直接失效**，官方替代全部指向 GPT-5.6 家族。同一批关停的还有基于这些底座的微调版本（`ft-gpt-3.5-turbo`、`ft-gpt-4`、`ft-gpt-4.1-nano`、`ft-babbage-002`、`ft-davinci-002`）。

## 前代 GPT-5.6

GPT-5.6 家族（2026-06-26 预览，2026-07-09 全面可用）现在仍在售，且**GPT-5.6 家族里没有 GPT-6 Terra** —— GPT-6 换掉了 Sol 与 Luna 的位置，Terra 这一档没有后继。

| 模型 | 输入 | 缓存输入 | 输出 | 上下文 | 知识截止 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `gpt-5.6-sol`（别名 `gpt-5.6`） | $4 | $0.40 | $20 | 1.05M | 2026-02-16 |
| `gpt-5.6-terra` | $2 | $0.20 | $12 | 1.05M | 2026-02-16 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $1.20 | 1.05M | 2026-02-16 |

- **`gpt-5.6-sol` 的 $4／$20 是促销价**，官方脚注写「至少持续到 2026-11-21」。原始挂牌价是 $5／$30。这句话的写法意味着没人承诺 11 月 22 日之后是什么价——**做预算别把促销价当常态**。
- Terra 与 Luna 的 2026-07-30 降价（分别 20% 与 80%）**没有标注结束日期**。
- 三者上下文同样是 1.05M / 128K 输出 / 272K 长上下文台阶。
- GPT-5.6 引入的能力在 GPT-6 上继续可用：程序化工具调用、显式缓存断点、持久化推理（persisted reasoning）、`max` effort、Pro mode、Responses API 的多智能体编排（beta）。

## 专用模型

GPT-6 之外，OpenAI 的模型目录按用途分了几块：

- **Daybreak 网络安全线**。`gpt-5.6-cyber` 是首个在 OpenAI Preparedness Framework 下达到「High」网络安全能力阈值的模型，$12.50／$1.25／$75，400K 上下文，仅通过 **Daybreak Red**（授权漏洞研究与安全测试）发放，只走 Responses API。`gpt-5.6-sol` 同样列在 Daybreak 表内（$4／$0.40），对应 **Daybreak Blue**——带防御性网络安全防护的通用旗舰，供普通用户使用。Astra 本身是 OpenAI 首个被定为 **Critical** 网络安全能力等级的模型。
- **图像**。当前是 `gpt-image-2.5-sunburst` 与 `gpt-image-2.5-flare`（图像输入 $8，文本输入 $5，缓存 $1.25），`gpt-image-2` 为 $4／$2.50／$0.625。`gpt-image-1` 在 2026-10-23 关停。
- **实时语音**。`gpt-realtime-2.1`（音频输入 $32／文本输入 $4／图像输入 $5）与蒸馏版 `gpt-realtime-2.1-mini`（$10／$0.60／$0.80）；`gpt-live-1` 会话按 $0.05／分钟计。
- **视频**。⚠️ `sora-2`、`sora-2-pro` 与整个 Videos API **已于 2026-09-24 从 API 移除**（2026-03-24 通知）。写文档时如果还在列Sora 2，那是过期的。

**GPT-oss 开放权重线**独立于 API 体系：`gpt-oss-120b`（117B 总参数／5.1B激活，MoE，单张 80GB GPU 可跑）与 `gpt-oss-20b`（21B／3.6B 激活，约 16GB 内存），2025-08-05 发布，**Apache 2.0**，上下文 131k，知识截止 2024-06。另有 `gpt-oss-safeguard-20b/120b` 两个安全分类专用微调。**这四个模型都不通过 OpenAI API 提供**，API 价格与速率限制对它们不适用，自部署的成本结构完全是另一笔账。

## 基准与横向位置

OpenAI 与 Anthropic 各自选了自己有利的评测集，effort 设定与 harness 也不一致，所以下面的数字只能当作定位参考，不是受控对比。Terminal-Bench 4.0 的标准误约 ±2.6，Terminal-Bench-Science 0.1 约 ±3.5～5——**小于这些幅度的差距不要当信号**。

| 基准 | GPT-6 Astra | GPT-6 Sol | Claude Opus 5.5 | 备注 |
| :--- | :---: | :---: | :---: | :--- |
| Terminal-Bench 4.0 | 57.9%（high） | 未公布 | **66.4%**（xhigh） | SE ±2.6 |
| FrontierCode v1.1 Main | 53.3%（max） | 49.3%（max） | 54.4%（max） | 差距在噪声内 |
| GDPval-AA v2.1（Elo） | 1542 | 未公布 | **1846** | 差 304 |
| Humanity's Last Exam（带工具） | 57.2% | — | **67.7%** | |
| OSWorld 2.0（partial） | 72.6% | 64.4%（离线集） | 81.8% | 评分方式不同 |
| AutomationBench | **41.4%**（max） | 33.2%（xhigh） | 40.0%（max） | |
| Terminal-Bench-Science 0.1 | **64.6%** | 未公布 | 58.7% | |
| DeepSWE v1.1 | 未公布 | 68.8%（max） | 74.2% | Opus 分数来自系统卡 |
| FrontierMath Tier 4 (v2) | 97.6% | — | 未公布 | |
| ExploitBench | 100%（污染受控子集 39.0%） | — | 未公布 | |

值得单独记的是 **ARC-AGI-3**：OpenAI 报 99.9%，但 ARC Prize 组织自己用标准 harness 测出的数字是 **62.7%**——99.9% 是通过专门适配的 harness 跑出来的（跨轮保留推理、持续管理上下文），单次完整评测成本在数万美元量级。**同一权重、两个 harness、62.7 个点的差距**，这个数字本身比任何单个分数都更能说明问题。

整体格局：**Opus 5.5 在 agentic coding 与知识工作上领先，Astra 在科学推理、前沿数学与科研 agent 上领先**，两边都没有全面压制。成本上 Astra（$10／$50）是 Opus 5.5（$4／$20）的 2.5 倍，而 **GPT-6.1 Sol 用 Sol 的价格去打Astra 的位置**，这才是 2026-10 之后 agentic coding 选型里真正的新变量。Gemini 侧另见 [Gemini](/docs/CS/AI/LLM/Model/Gemini.md)。

## 模型选择建议

- **日常主力用 `gpt-6.1-sol`**，不是 `gpt-6-sol`——同价、缓存输入半价、能力更强，唯一理由不选它是 Astra 独占的 `none` 档位以外没有差异。
- **只有「Astra 明显不够」才上 `gpt-6-astra`**。它的 2.5 倍价差要靠「更少的 token 数」和「更少返工」摊回来，这依赖你的负载形状，必须自己测。
- **大规模抽取、分类、路由、日志归类走 `gpt-6-luna`**（$0.10／$0.50）。这个档位的输入价已经低于 [DeepSeek V4.1-Flash](/docs/CS/AI/LLM/Model/DeepSeek.md) 的 0.15 美元／输出 0.60 美元同一量级，但上下文大得多。
- **别把 Fast mode 当默认**。它只买延迟，不买质量，价钱是双倍。
- **Agent 与编码工具的接入方式**见 [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md)。

## Links

- [Qwen](/docs/CS/AI/LLM/Model/Qwen.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Pricing | OpenAI API](https://developers.openai.com/api/docs/pricing)
- [Models | OpenAI Developers](https://developers.openai.com/api/docs/models)
- [GPT-6 Sol | OpenAI Developers](https://developers.openai.com/api/docs/models/gpt-6-sol)
- [GPT-6 Luna | OpenAI Developers](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [GPT-6 Astra | OpenAI Developers](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Changelog | OpenAI API](https://developers.openai.com/api/docs/changelog)
- [Deprecations | OpenAI API](https://developers.openai.com/api/docs/deprecations)
- [Data controls in the OpenAI platform](https://developers.openai.com/api/docs/guides/your-data)
- [Fast mode for API Customers | OpenAI](https://openai.com/api-fast-mode)
- [Introducing GPT-6.1 Sol（Release Notes, 2026-09-29）](https://openai.com/products/release-notes/)
- [OpenAI 開放權重模型(gpt-oss)](https://help.openai.com/en/articles/11870455-open-weight-models-gpt-oss)