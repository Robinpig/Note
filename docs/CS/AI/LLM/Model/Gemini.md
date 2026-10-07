## Introduction

> **版本基线：2026-10-05 核实。** 型号、上下文与价格以 [Gemini Developer API 定价页](https://ai.google.dev/gemini-api/docs/pricing) 与 [退役页](https://ai.google.dev/gemini-api/docs/deprecations) 为准，知识截止与基准以 [DeepMind 模型卡](https://deepmind.google/models/model-cards/) 为准，Agent Platform 能力以 [Google Cloud 文档](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes) 为准。**本次核实说明**：`ai.google.dev` 与 `cloud.google.com` 的直接抓取在本机全部失败，价格数据通过搜索引擎返回的官方页面快照（`ai.google.dev/gemini-api/docs/pricing?hl=zh-cn` 成功返回官方定价表原文）加上多个二手源交叉核对得出，下文会逐处标明来源等级；标「二手源」的条目表示只找到转述而非官方页面原文。

[Google DeepMind](https://deepmind.google) 的 Gemini 是 2026 年 10 月**唯一同时握有「2M 上下文」与「2M 输出上限」两个第一**的厂商，前者是 Gemini 3.1 Pro，后者在 2026-09-30 发布的 Gemini 4 Argon 上——而后者**至今不公开发售**，只通过 Fairwind Program 定向提供给经审核的网络安全防守方。所以「Google 的旗舰」这件事在 2026-10 有两层答案：能直接调用的旗舰是 3.1 Pro（仍是 Preview），真正的技术旗舰 Argon 拿不到。

Google 的档位命名是 **Pro／Flash／Flash-Lite** 三档，与 OpenAI 的四档、Anthropic 的四档都不同，**价格阶梯也是三家里最陡的**：经济档的 Flash 比旗舰 Pro 便宜 2.7 倍输入、4 倍输出，而同一家把最贵模型的缓存存储价定到 Flash 的 9 倍——同一套缓存机制在两个模型上的经济性完全不同。

## Current Models

| 模型 | API ID | 发布 | 状态 | 上下文 | 最大输出 | 知识截止 |
| :--- | :--- | :--- | :--- | :---: | ---: | :--- |
| Gemini 4 Argon | 未公开 | 2026-09-30 | ⚠️ Fairwind 定向 | 未公布 | **1M** | 未查到 |
| **Gemini 3.1 Pro** | `gemini-3.1-pro-preview` | 2026-02-19 | Preview | **2M** | 64K | 未查到（来源冲突） |
| **Gemini 3.8 Flash** | `gemini-3.8-flash` | 2026-09-02 | GA | 1M（1,048,576） | 64K（65,536） | **2026-03** |
| Gemini 3.7 Flash | `gemini-3.7-flash` | 2026-08-13 | GA | 1M | 64K | 2026-03 |
| Gemini 3.6 Flash | `gemini-3.6-flash` | 2026-07-21 | GA | 1M | 64K | 2026-03 |
| Gemini 3.5 Flash | `gemini-3.5-flash` | 2026-05-19 | GA | 1M | 64K | 未查到 |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | 2026-07-21 | GA | 1M | 64K | 未查到 |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | 2026-05-07 | GA | 1M | 64K | 未查到 |
| Gemini 3 Flash Preview | `gemini-3-flash-preview` | 2025-12-17 | Preview | 1M | 64K | 未查到 |
| Gemma 4 | 见下文 | 2026-03-31 起 | GA 权重 | 128K～256K | — | 未查到 |

几点必须先讲清楚：

- **3.8 Flash 不是新基础模型。** DeepMind [模型卡原文](https://deepmind.google/models/model-cards/gemini-3-8-flash/) 明写「Gemini 3.8 Flash is based on Gemini 3.7 Flash」，架构、训练数据、硬件、评测方法全部沿用 3.7 Flash。Google 对这次升级的描述是行为差异而非能力架构差异：**在难任务上走更小的推理步、沿途自我验证、迭代调用工具**。代价是每任务 token 数上升，Artificial Analysis 测到输出 token 比 3.7 Flash 多约 30%。
- **知识截止只有 3.8 Flash 有官方数字：2026-03。** 模型卡同时给了一个必须知道的附加条件——**部分领域仍停留在 2025-01**（「in others they may experience the model's knowledge is limited to January 2025」）。3.1 Pro 的知识截止**未查到官方数字**，第三方源给出 2025-01-31 与 2026-03 三种互相冲突的说法，不要按任一数字做设计假设。
- **`gemini-3.1-pro-preview` 挂了半年仍是 Preview。** 前身 `gemini-3-pro-preview` 已于 2026-03-09 关停，官方推荐的迁移目标就是它自己。旗舰长期停在 Preview 意味着定价与可用性都可能变。
- **3.1 Pro 不支持 Computer Use。** 想用 computer use 只能走 `gemini-3.7-flash`（官方在预览文档里明确指向 3.7 Flash），而 3.8 Flash 的 computer use 标注为 Preview。一个旗舰模型的能力空缺，值得记一笔。
- **旧的 Gemini 2.5 全家正在退场，且日期比一般公告更紧。** `gemini-2.5-pro`、`gemini-2.5-flash`、`gemini-2.5-flash-lite` 在 Gemini Developer API 的关停日是 **2026-10-16**，在 Agent Platform Gemini API（原 Vertex AI）是 **2026-10-20**（[Firebase 官方文档](https://firebase.google.cn/docs/ai-logic/faq-and-troubleshooting)）。两个平台日期不同，只有同时用两边才看得出差别。退役前一个月会封锁新访问，关停后请求返回 404。官方把退役日定义为「最早可能日」，只可能推迟不会提前。

## Gemini 4 Argon Frontier Tier

2026-09-30 Google 公布 Gemini 4 家族首个型号 [Argon](https://blog.google/intl/en-mena/company-news/technology/gemini-4-argon-our-next-era-of-frontier-intelligence/)，这是本库写作时点 Google 最新的前沿模型，也是 Google 首次把输出上限从 64K 提到 **1M token**。

**能拿到的部分有限**：Argon 仅通过 **Fairwind Program** 向经审核的网络安全防守方、政府与关键基础设施机构开放，Google 同时参与美国政府的自愿预发布模型访问流程。官方说会分阶段扩大访问，先面向付费 API 客户与 AI Ultra 订阅者，但**未给出日期**。所以它现在进不了任何技术方案——但它定义了两件事：Google 的定价会往 ($2/$10) 这个档走，以及输出上限会成为新的竞争维度。

公布的价格与几个自报基准（价格来自官方博客原文，基准为 Google 自报）：

| 项目 | 数值 | 备注 |
| :--- | :--- | :--- |
| 输入 | $2／输出 $10（促销） | 促销期后 $4／$20，二手源一致 |
| 缓存读 | 输入价的 5% | 即 $0.10 |
| 输出上限 | 1M token | 前代 64K |
| DeepSWE v1.1 | 77.9% | 高于 Opus 5.5 的 74.2% 与 GPT-6 Astra 的 74.1% |
| CWE-bench v1 | 68% | 与 GPT-6 Astra 并列 |
| Terminal-Bench 4.0 | 未领先 | 低于部分竞品（港媒据 Google 数据报道） |

内部用例里最具体的一个是 Argon agent 修改 Google 的 `libgav1`：替换 3.2 万行 SIMD 代码，产出与原视频输出逐位一致、**比原 Rust 移植版快 2.7 倍**的安全 Rust 实现。这类数字是厂商自报，不可作受控对比，但可作为「长周期软件工程」这条能力线的存在性证据。

## Pricing: Four Tiers of Service and Tiered Markup

价格单位为美元／百万 token，全部为付费层（Paid tier）数据。

| 模型 | 输入 | 输出（含思考） | 缓存读 | 缓存存储／小时 | 上下文 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Gemini 3.8 Flash / 3.7 Flash | $0.75 ** | $3.75 ** | $0.075 ** | $0.50 ** | 1M，无加价 |
| Gemini 3.6 Flash | $0.75 ** | $3.75 ** | $0.075 ** | 未查到 | 1M，无加价 |
| Gemini 3.5 Flash | $1.50 | $9.00 | $0.15 | $1.00 | 1M，无加价 |
| **Gemini 3.1 Pro**（≤200K） | $2.00 | $12.00 | $0.20 | **$4.50** | 2M |
| **Gemini 3.1 Pro**（>200K） | **$4.00** | **$18.00** | 未查到 | $4.50 | 同上 |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | $0.03 | $1.00 | 1M |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 | $0.025 | $1.00 | 1M |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | — | — | ⚠️ 2026-10-16 关停 |

** 标记的是促销价，2026-12-31 到期**，见下一节。

同一个模型在四个服务档位上的价格关系是固定的：**Batch 与 Flex 均为标准档的 50%，Priority 为标准档的 1.8 倍**。以 3.8 Flash 的 2026 年价格为例：

| 档位 | 输入 | 输出 | 缓存读 |
| :--- | ---: | ---: | ---: |
| Standard | $0.75 | $3.75 | $0.075 |
| Batch（异步，SLA 约 24h） | $0.375 | $1.875 | $0.0375 |
| Flex（可接受降级与延迟） | $0.375 | $1.875 | $0.0375 |
| Priority（1.8×） | $1.35 | $6.75 | $0.135 |

3.1 Pro 同结构：Batch／Flex 为 $1.00／$6.00（≤200K）与 $2.00／$9.00（>200K），Priority 为 $3.60／$21.60 与 $7.20／$32.40。

⚠️ **缓存存储费在所有档位都是同一个数，不参与折扣**——这是最容易漏算的一条。以 3.8 Flash 为例，Batch／Flex 的缓存读是半价，但存储仍是 $0.50／百万 token／小时。

**Batch 与 Flex 价格相同但语义不同**：Batch 是异步接口，Flex 是同步接口、只是降级延迟与可用性。两者同价时按「能不能等」选，而不是按价选。Priority 买的是服务等级，不是更高的输出质量，不要因为「表格里有」就选它。

## Pitfall One: Promo Price Expires 2026-12-31

Google 在发布时就同时公示了两套价，`gemini-3.6-flash`、`gemini-3.7-flash`、`gemini-3.8-flash` 共享同一张时间表：

| 计费项 | 至 2026-12-31 | 自 2027-01-01 | 倍率 |
| :--- | ---: | ---: | ---: |
| 输入 | $0.75 | $1.50 | 2.0× |
| 输出（含思考） | $3.75 | $7.50 | 2.0× |
| 缓存读 | $0.075 | $0.15 | 2.0× |
| 缓存存储／小时 | $0.50 | $1.00 | 2.0× |
| Batch 输入／输出 | $0.375／$1.875 | $0.75／$3.75 | 2.0× |
| Priority 输入／输出 | $1.35／$6.75 | $2.70／$13.50 | 2.0× |

**每一个 2027 年的数字都精确是 2026 年的 2.0 倍**，包括缓存存储。做 2027 年预算必须用右列；用左列做的模型在 2027-01-01 当天账单翻倍，用量一点都不用变。

一个反直觉的推论：**3.5 Flash 不在促销名单上**，当前标价 $1.50／$9.00 已经是长期价（官方页面快照确认）。也就是说 3.5 Flash 的输入价与 3.8 Flash 2027 年的输入价相同、输出价还高 20%，而 3.8 Flash 能力更强——**留在 3.5 Flash 上没有任何价格理由**。

> 来源等级说明：3.8／3.7／3.6 Flash 的促销价与 2027 倍率由多个二手源一致给出并与本库既有的 Overview.md 记录一致；官方定价页的 zh-cn 快照本次返回的范围覆盖 3.6／3.5／3.1 各档但未截到 3.8 与 3.7 两行，故此三行标注为二手源。缓存存储的 $0.50→$1.00 只找到二手源，官方页面快照中 3.5／3.1 各档显示的是 $1.00。

## Pitfall Two: thinking token Billed at Output Price

**这是三家里最激进的计费口径。** 官方定价表里每一行的输出价都标注「含思考 token」（官方页原文：「输出价格（包括思考 token）」），也就是说 `total_thought_tokens` 与 `candidatesTokenCount` 一起按输出单价计费。

后果链条是这样的：

1. **100 词的答案可能带几千个不可见 thinking token**，账单按后者算。
2. **Pro 模型 think 更多**，所以**最贵的模型账最容易超预估**——这是一个反直觉的反向关系：旗舰不只是单价高，实际超支幅度也更大。
3. **thinking 升级会同时抬高延迟与账单**，且 3.8 Flash 的档位设计就是要它「更用力」——官方模型卡明写「At times, the model might use more tokens to maximize performance, especially at higher effort levels」。

按 token 预算是安全的，按任务预算是危险的。**在 usage 里读 thinking token，不要只读可见输出**：

| 字段（原生 `generateContent`） | 含义 |
| :--- | :--- |
| `usageMetadata.promptTokenCount` | 输入 token |
| `usageMetadata.cachedContentTokenCount` | 命中缓存的输入部分 |
| `usageMetadata.candidatesTokenCount` | **可见输出** |
| `usageMetadata.thoughtsTokenCount` | **思考 token，按输出价计费** |

一个粗算例（2026 促销价，Standard，未缓存）：20 万输入 + 2 万思考 + 5 千可见输出 = `0.2×0.75 + 0.025×3.75 = $0.24375`。若只把 5 千可见输出计入，就少算了 2 万思考 token 的钱。

## Pitfall Three: Cache Has Two Billing Tables

Gemini 的上下文缓存（context caching）**同时产生两笔费用**，只算读价一定算错：

| 计费项 | 单价 | 计费对象 |
| :--- | ---: | :--- |
| 缓存读 | 输入价的 0.1× | 被复用命中的 token |
| 缓存存储 | 每百万 token 每小时 | 缓存驻留的时长 × token 数 |

由此有两条硬推论：

> ⚠️ **只写不读的缓存是净亏。** 存储费按小时累加而无最低使用要求。判断标准很简单：把「小时存储成本」与「命中一次省下的读价差」放在同一小时里比。以 3.8 Flash 2026 价格为例，1M token 缓存驻留一小时是 $0.50，而命中一次只省 $0.75 − $0.0375 ≈ $0.71。也就是说同一小时内至少要命中约 **0.7 次**才不亏——超过一小时没被读到就是纯支出。

> ⚠️ **Pro 的存储价 $4.50／百万 token／小时是 Flash 的 9 倍，而缓存读价只差 2.7 倍。** 存储成本的差距远大于读价优惠的差距，所以同一套机制在 3.1 Pro 上的经济性远差于在 3.8 Flash：Pro 上一百万 token 缓存一小时要 $4.50，而读价优惠只有 $2−$0.20=$1.80，**要命中 2.5 次以上才不亏**（Flash 只需约 0.7 次）。**结论是缓存策略要按模型设计，不能把 Flash 的结论套到 Pro 上。**

缓存的折扣力度本身在 Google 是全行业最深的之一——缓存读只有标准输入价的 **0.1×**（Anthropic 的 Fable 5.1 是 0.025×、Opus 5.5 是 0.05×，但它们的无台阶结构另有优势）。长系统提示、重复前缀的负载在这里收益最直接。

## Pitfall Four: 200K Step Triggers Whole-Order Recompute

**Gemini 3.1 Pro 是三家里唯一有「公开的旗舰长上下文加价台阶」的模型**，且它加的幅度比 OpenAI 更狠：

| 区间 | 输入 | 输出 | 变化 |
| :--- | ---: | ---: | :--- |
| prompt ≤ 200K | $2.00 | $12.00 | 基准 |
| prompt > 200K | $4.00 | $18.00 | 输入 **2.0×**，输出 **1.5×** |

关键在计费口径：**越过 200K 之后，整个请求按长上下文价重算，不是只对超出的部分**。也就是说 200K 与 200,001 两个 prompt 的单价一样——**把一个刚过 200K 的 prompt 砍到 200K，账单直接减半**。这与 OpenAI 的 272K 台阶是同一类问题（见 [OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)），但 Google 恰好把台阶放在很多典型代码库会话会碰到的位置。

**Flash 系没有这个问题**：3.1～3.8 Flash 的官方定价表**没有长上下文 token 档**，官方快照明确写「Its published Gemini Developer API table does not add a separate long-context token tier」。大 prompt 贵只是因为 token 更多，不是单价跳档。

## Grounding and Tool Billing

**Grounding（接地）把「一次 API 调用」变成「一次调用 + N 次搜索」，N 不可控**，这是 agentic 负载里第二个账单黑洞。

| 项目 | 免费额度 | 之后 |
| :--- | --- | ---: |
| 依托 Google 搜索接地 | 每月 **5,000 次免费搜索请求**（Gemini 3.x 共享） | $14／1,000 次 |
| 依托 Google 地图接地 | 每月 **5,000 条提示**（Gemini 3 中共享） | $14／1,000 次搜索查询 |

免费额度是**账号级共享而非模型级**——3.6、3.7、3.8 Flash 以及 3.1 Pro 共用这 5,000 次，跨模型不会各给一份。**免费层完全不提供 Grounding**（官方页面对应行标注「不可用」）。

官方在同一页给出了一句必须一起读的话：**一次发给 Gemini 的请求可能触发一次或多次 Google 搜索查询，每次查询都单独计费。** 所以「我开了缓存所以搜索不要钱」和「我只发了一个请求」都不成立——**做预算时 Grounding 的成本与 prompt 长度无关，与 agent 循环的迭代次数有关**。

其他按量工具（代码执行等）同样独立计费，不含在 token 价里。

## Free Tier and Paid Tier

官方定价页把三个层级并排列出，差异不只是价格：

| 维度 | 免费 | 付费 | 企业（Agent Platform 提供） |
| :--- | :--- | :--- | :--- |
| 模型访问 | ⚠️ 仅部分模型 | 全部先进模型 | 付费层全部 |
| 输入／输出 token | 免费（限额内） | 按标价计费 | 按标价计费 |
| 上下文缓存 | 不可用 | ✅ | ✅ |
| Batch API | 不可用 | ✅ 5 折 | ✅ |
| Grounding | 不可用 | ✅ 含每月 5,000 次 | ✅ |
| **内容是否用于改进 Google 产品** | ⚠️ **是** | ✅ **否** | ✅ 否 |
| 专属支持渠道 | ❌ | ❌ | ✅ |
| 高级安全与合规 | ❌ | ❌ | ✅ |
| 预配吞吐量 | ❌ | ❌ | ✅ |
| 阶梯折扣（基于用量） | ❌ | ❌ | ✅ |
| MLOps、Model Garden | ❌ | ❌ | ✅ |

> ⚠️ **免费层最该记住的不是限额，是数据条款：免费层 Google 可能用你的请求内容改进产品，付费层不会。** 官方定价页把这一行写成「用于改进 Google 产品：免费层 是／付费层 否」。处理企业代码、客户数据或任何敏感文档时，「先在免费层把 prompt 调通」这个习惯是有代价的——那些内容已经出去了。

**免费层 Pro 已于 2026-04-01 移出**（`gemini-3.1-pro-preview`、`gemini-3-pro-preview`、`gemini-2.5-pro` 全部改为仅付费），Flash 与 Flash-Lite 保留免费但日配额收紧。注意这一改动**没有单独的 changelog 公告**，是通过 API 报错「This model requires a billing-enabled project」发现的——Google 只更新了定价文档。另外付费层自 2026-04-01 起新增了 Flex 与 Priority 两个按需档。

## Thinking Control thinking_level

Gemini 的推理旋钮是 `thinking_level`（3.x）或 `thinking_budget`（2.5），通过 OpenAI 兼容层则映射为 `reasoning_effort`。官方给出的完整映射表：

| `reasoning_effort`（OpenAI） | 3.1 Pro | 3.1 Flash-Lite | 3 Flash | 2.5 系（`thinking_budget`） |
| :--- | :--- | :--- | :--- | ---: |
| `minimal` | low | minimal | minimal | 1,024 |
| `low` | low | low | low | 1,024 |
| `medium` | medium | medium | medium | 8,192 |
| `high` | high | high | high | 24,576 |

不指定 `reasoning_effort` 就用模型默认值。三个必须注意的点：

- **`minimal` 在 Gemini 3.8 Flash 上会返回校验错误**，而不是静默降级到 `low`。而官方映射表里 3.1 Pro 与 3 Flash 都支持 `minimal`——同一个参数在同一家不同模型上行为不同，接入时需要按型号分别验证。
- **3.8 Flash 的默认 thinking level 是 `medium`，而 Gemini 3 Pro 的默认是 `high`。**在 Pro 上调好的 prompt 迁到 Flash 之后推理量会自动变少，除非显式设 level。
- **thinking 关不掉。** 官方原文：设 `reasoning_effort="none"` 只对 **2.5 系非Pro 模型**有效；**Gemini 2.5 Pro 与全部 3 系模型的 reasoning 无法关闭**。这与 Anthropic 的 adaptive thinking 不可关是同一类锁定，但方向相反——Anthropic 是没有关闭开关，Google 是有开关但新一代没有。

## Benchmarks

厂商自报，且各家评测集、effort 设定与 harness 都不同，**不是受控对比**。Terminal-Bench 在不同厂商那里甚至不是同一版本（Claude／OpenAI 用 4.0，Google 的 3.8 Flash 被记录的是 2.1），**跨厂商比这个分数是错的**。

| 基准 | Gemini 3.8 Flash | 备注 |
| :--- | :---: | :--- |
| HLE-Verified | 54.9% | Google 自报；3.7 Flash 为 53.6%，GPT-5.6 Sol 54.5%，Opus 5 54.4% |
| Vals Finance Agent V2 | **61.4%** | 3.7 Flash 59.0%、Opus 5 58.6% |
| Harvey Legal Agent Benchmark | **10.0%** | 3.7 Flash 8.8%、Opus 5 6.7% |
| DeepSWE v1.1 | 73.8% | ⚠️ 二手源；官方模型卡未在摘要中列出此数字 |
| ARC-AGI-1 | 98.5%（thinking high） | 二手源 |
| Terminal-Bench 2.1 | 89.4%（thinking 带工具） | ⚠️ 版本与 Claude／OpenAI 的 4.0 不可比 |
| Computer Use | 支持（Preview） | 3.1 Pro 不支持 |

Gemini 侧真正值得注意的不是绝对分数，是两个第三方定位：**Artificial Analysis Intelligence Index v4.3 给 3.8 Flash 41 分（high effort），是 Google 在该指数上的最高分**，而同一份评测把 GPT-6 Astra 与 3.8 Flash 放在同一档（v4.1.1 时 AA 给两者同为 59）。这说明**在第三方看来 3.8 Flash 已经站在前沿线**，这也是 Google 敢给促销价的原因。

第三方也记录了一个成本侧的平衡点：**AA 测到 3.8 Flash 在长周期文档工作流上完成的任务数是 3.7 Flash 的三倍以上**。按任务计价时，Flash 内部换代的收益比标价看起来大得多。

## Protocol Compatibility

**Gemini API 官方支持 OpenAI SDK 与 OpenAI REST 兼容层**，这一点三家都有，但 Google 的实现细节值得写清。

改三行即可（官方 [OpenAI compatibility](https://ai.google.dev/api/compatibility) 原文）：

```python
from openai import OpenAI

client = OpenAI(
    api_key="GEMINI_API_KEY",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
response = client.chat.completions.create(
    model="gemini-3.8-flash",
    messages=[{"role": "user", "content": "Explain to me how AI works"}],
)
```

Agent Platform 侧的 base URL 完全不同，且**只支持 Google Cloud Auth**，模型 ID 需要加 `google/` 前缀：

```
base_url = f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/endpoints/openapi"
api_key  = credentials.token          # ADC / service account，不是 API key
model    = "google/gemini-3.5-flash"
```

> ⚠️ **官方自己给的第一条建议就是不要用兼容层**：官方文档明确写「如果你还没有在用 OpenAI 库，我们建议你直接调用 Gemini API」。原因在兼容层之外的部分——**原生 `Interactions API` 已经 GA 并被官方推荐**（`generateContent` 仍可用但页面顶部有横幅引导迁移），新特性先到原生 API，兼容层滞后。兼容层的价值是**换厂商时少改代码**，不是长期方案。

**Gemini API 不提供 Anthropic SDK 兼容 Base URL。** 这与 DeepSeek 不同——DeepSeek 提供 `https://api.deepseek.com/anthropic`，让 Claude Code／Claude Agent SDK 零改动接入。Google 侧的做法是通过 OpenAI 兼容层间接接入，且 thinking 控制的参数名不同（见上一节的映射表），迁移代码时不能想当然地沿用 `thinking: {type: ...}`。

## AI Studio and Gemini Enterprise Agent Platform

⚠️ **Vertex AI 已于 2026-04-22（Cloud Next）改名 Gemini Enterprise Agent Platform**，旧名 Vertex AI 在文档与控制台里会与新名共存一段时间。这是一次品牌重构而非新产品，底层服务名不变（`aiplatform.googleapis.com`）。迁移期的命名对照里最容易踩的几个：

| 旧名（Vertex AI） | 新名（Agent Platform） |
| :--- | :--- |
| Vertex AI Studio | Agent Studio |
| Vertex AI API | Agent Platform API |
| Vertex AI Agent Engine | Agent Runtime |
| Vertex AI Model Garden | Model Garden |
| Vertex AI Agent Builder | Agent Studio（低代码） |
| Vertex AI Vector Search | Vector Search |

改动最实质的三项能力：**Agent Runtime**（支持最长 7 天的长时运行、亚秒级冷启动、准备时间低于 1 分钟、支持自带自定义容器）、**Memory Bank**（跨会话长期记忆 + Memory Profiles，支持自动记忆生成与不可变的版本历史）、**Agent Sandbox**（隔离执行模型生成的代码，支持 browser computer use）。**这些能力只在 Agent Platform 上发布**，独立 Vertex AI 上不会有。

两个平台的功能差异，按企业选型的实际权重排序：

| 维度 | AI Studio／Gemini Developer API | Agent Platform（原 Vertex AI） |
| :--- | :--- | :--- |
| 鉴权 | API key | Service Account／ADC，**代码里不出现密钥** |
| 网络隔离 | 公网 | VPC Service Controls、Private Service Connect |
| 加密密钥 | Google 托管 | Google 托管或 **CMEK** |
| 区域数据驻留 | 有限 | 完整（`europe-west1`、`us-east4` 等） |
| SLA | 无 | 99.9% |
| **预配吞吐量** | ❌ | ✅（Provisioned Throughput） |
| 阶梯折扣 | ❌ | ✅ |
| 预训练 API／付费方式 | 仅按 token | 预配吞吐量／按需 |
| 内容用于训练 | ⚠️ 免费层会 | 不会 |
| 身份治理 | API key | 完整 IAM（另有新的 IAM 治理策略在 Private Preview） |

**token 标价本身是一样的**（AI Studio 与 Agent Platform 的全球端点同价），差别在采购与账务方式：

> ⚠️ **只有把推理指定到特定区域时（通常是法遵要求），输入与输出各多出约 10%。** 这个加价幅度与 Anthropic 的 US-only inference 1.1× 一致，但与 OpenAI 的区域加价是两套独立规则，跨厂商迁移时不要沿用上一家的估算。

来源等级：10% 加价只找到二手源（精英云中文页，与 Overview.md 记录的Anthropic／OpenAI 加价幅度一致），**未能确认 2026-07-01 这个生效日期**，官方页面未取到。

## Gemma Open-Weight Series

**Gemma 4 于 2026-03-31 至 04-02 发布，是 Gemma 家族第一次采用 Apache 2.0**——此前 Gemma 3 用的是带限制的 Gemma Terms of Use。如果你在 2026-04 之前因为许可问题排除了 Gemma，这个理由现在不成立了。

[官方博客](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/) 称其为「与 Gemini 3 同一套世界级研究和技术」的开源家族，共**五个尺寸**：

| 型号 | 参数 | 架构 | 上下文 | 模态 |
| :--- | :--- | :--- | ---: | :--- |
| Gemma 4 E2B | 2.3B effective（含 embedding 5.1B） | Dense + PLE | 128K | 文／图／音频 |
| Gemma 4 E4B | 4.5B effective（含 embedding 8B） | Dense + PLE | 128K | 文／图／音频 |
| Gemma 4 12B Unified | 11.95B dense | **encoder-free** | 256K | 文／图／音频 |
| Gemma 4 26B A4B | 26B 总／**激活约 3.8B** | MoE | 256K | 文／图／视频 |
| Gemma 4 31B | 30.7B dense | Dense | 256K | 文／图／视频 |

几个部署上必须记住的点（来自 [官方 Gemma 4 概览](https://ai.google.dev/gemma/docs/core)）：

- **「E」是 effective 参数，不是总参数。** E2B／E4B 用 **Per-Layer Embeddings（PLE）**——每个 decoder 层都有自己的小embedding 表用于快速查表。这些表很大但不按比例增加推理成本，所以**加载静态权重需要的内存远高于 effective 数字**：E2B BF16 需11.4GB，而 2.3B 有效参数对应的直觉值要低得多。做内存规划时看官方表，不要按参数量自己推。
- **MoE 的 26B 不会因为只激活 4B 就省内存**——26B 权重必须全部加载以维持快速路由，其基线内存接近 dense 26B。官方给的是 57.7GB（BF16）／14.4GB（Q4_0）。
- **12B Unified 是本代架构上的新东西**：它丢掉独立的视觉与音频编码器，把图像 patch 与音频波形**直接线性投影进 LLM 的 embedding 空间**。接近 26B MoE 的质量，内存不到一半，16GB 笔记本可跑。
- **全部五个尺寸都带 Multi-Token Prediction（MTP）草稿模型**，可做 self-speculative decoding，无需单独的 draft 模型。26B 与 31B 的 BF16 权重可放进单张 80GB H100。
- 家族累计下载已过 **9 亿次**，是 HuggingFace 与 Kaggle 上下载最多的开源模型家族。**权重免费，甚至可通过 Gemini API 免费调用**，本地部署只需付算力。

定位上，Gemma 4 31B 在 Arena AI 文本榜是开源模型第 3，26B A4B 第 6；官方给的对比数字是 Gemma 4 31B 在 Arena 文本估计 1452、26B MoE 1441（4B 激活）。

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

1. [Gemini Developer API 定价（官方）](https://ai.google.dev/gemini-api/docs/pricing) — 抓取失败，价格以官方页快照与多源交叉核对
2. [Gemini deprecations（官方，型号发布与关停表）](https://ai.google.dev/gemini-api/docs/deprecations)
3. [OpenAI compatibility | Gemini API（官方）](https://ai.google.dev/api/compatibility)
4. [Gemini 3.8 Flash Model Card（DeepMind 官方）](https://deepmind.google/models/model-cards/gemini-3-8-flash/)
5. [Gemma 4: Byte for byte, the most capable open models（Google 官方博客）](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/)
6. [Gemma 4 model overview（官方文档，含显存表）](https://ai.google.dev/gemma/docs/core)
7. [Gemini 4 Argon: our next era of frontier intelligence（Google 官方博客）](https://blog.google/intl/en-mena/company-news/technology/gemini-4-argon-our-next-era-of-frontier-intelligence/)
8. [Gemini Enterprise Agent Platform release notes（改名对照表）](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes)
9. [Model versions and lifecycle | Agent Platform（官方退役表）](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)
10. [OpenAI compatibility | Gemini Enterprise Agent Platform（官方，含 Agent Platform 侧 base_url）](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/openai)
11. [Firebase AI Logic 常见问题（官方，2.5 系列双平台关停日）](https://firebase.google.cn/docs/ai-logic/faq-and-troubleshooting)
