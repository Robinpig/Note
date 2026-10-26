## Introduction

> **版本基线：2026-10-05 核实。** 本页是对本目录各家笔记的**横向汇总页**，不重复展开细节——每家的完整型号表、定价、架构要点与陷阱请看各自的专页。价格一律为美元／百万 token 的标准档（不含 Batch、Flex 等折扣），上下文长度取厂商标称值。

2026 年 10 月的大模型市场有一个反复出现的现象：**「同档位模型的输入价格正在收敛，但输出、缓存与长上下文的定价结构差异极大」**。三个月前还能靠标价分辨厂商，现在不行了——真正决定账单的是四件事：缓存命中价、长上下文是否加价、thinking token 算输入还是输出、以及能不能错峰。

本页的组织方式也说明了另一件事：**模型名不能代表能力顺序**。OpenAI 用 Astra／Sol／Terra／Luna，Anthropic 用 Fable／Opus／Sonnet／Haiku，Google 用 Pro／Flash／Flash-Lite，DeepSeek 直接用 Flash／Pro——四套命名体系里只有「越贵越强」这个方向是一致的。所以下面的排序一律**按能力档位**而不是按名字。

## How to Read This Table

先说清楚三个维度，否则表格会被误读：

- **输入／输出**是标准档短上下文价格。所有厂商的输出都比输入贵 4~5 倍，**账单的主要构成通常在输出侧**，尤其是开了 thinking 的模型。
- **缓存**一栏是缓存**读取**价相对输入价的倍率。倍率越低，重复前缀多的负载（如固定系统提示、多轮对话）越省。这一栏的差距比标价差距大得多。
- **长上下文加价**是「标称上下文」能否按标价算完。OpenAI 有 272K 台阶，Anthropic 与 DeepSeek 没有，这个差异比任何价格数字都重要。

## Closed-Source Three: Horizontal Review

| 档位 | 模型 | 输入 | 输出 | 缓存读 | 上下文 | 长上下文 |
| :--- | :--- | ---: | ---: | ---: | :---: | :--- |
| 顶配 | Gemini 4 Argon | $2 | $10 | **$0.10（0.05×）** | 未公布 | — |
| 顶配 | GPT-6 Astra | $10 | $50 | $1（0.1×） | 1.05M | ⚠️ >272K 翻倍 |
| 顶配 | Claude Fable 5.1 | $10 | $50 | **$0.25（0.025×）** | 1M | ✅ 不加价 |
| 旗舰 | Claude Opus 5.5 | $4 | $20 | $0.20（0.05×） | 1M | ✅ 不加价 |
| 旗舰 | GPT-6.1 Sol | $2 | $10 | **$0.10（0.05×）** | 1.05M | ⚠️ >272K 翻倍 |
| 主力 | Claude Sonnet 5.5 | $2 | $10 | $0.20（0.1×） | 1M | ✅ 不加价 |
| 经济 | GPT-6 Luna | $0.10 | $0.50 | $0.01（0.1×） | 1.05M | ⚠️ >272K 翻倍 |
| 经济 | Claude Haiku 4.5 | $1 | $5 | $0.10（0.1×） | 200K | ✅ |
| 主力 | Gemini 3.1 Pro | $2 | $12 | $0.20 | **2M** | ⚠️ >200K 翻倍 |
| 经济 | Gemini 3.8 Flash | $0.75 | $3.75 | $0.075 | 1.05M | ✅ |

> ⚠️ **Gemini 4 Argon 名字里的 "4" 不是换代而是代际跳跃**：它 2026-09-30 发布，是 Gemini 3 系列（2025-11）之后的第一款旗舰，也是目前唯一有 **1M token 输出上限**的模型（前代 Gemini 是 64K）。但它**只在 Fairwind Program 定向开放**（约 650 家经审核的国防/医疗/电信/安全研究机构），公开可用日期未公布——所以它在本页只作参照，**当前能真正接入的 Gemini 最强档位仍是 3.1 Pro**。

> ⚠️ **三个必须单独记住的定价陷阱**：
> ① **OpenAI 的 272K 是台阶不是斜坡**——越过 272K 后**整个请求**按长上下文价重算，不是只对超出部分。11% 更长的上下文会让账单涨约 74%。
> ② **Gemini 的 thinking token 按输出价计费**。100 词的答案可能带几千个不可见 thinking token，且 Pro 模型 think 更多，所以**最贵的模型账最容易超预估**。
> ③ **Anthropic 1M 上下文不加价**是三家里独一份。同样把 900K token 的仓库丢进去，Anthropic 按 $4/$20 算，OpenAI 按 $20/$75 算。
> ④ **Gemini 的缓存有第二个计费表**：除读价外还收每小时存储费，且 Pro 的存储价（$4.50/百万 token/小时）是 Flash（$0.50）的 9 倍——**只写不读的缓存是净亏**，Pro 上尤其如此。

**能力与价格的三点判断**：

- **最贵的不一定最划算**。GPT-6.1 Sol 在 DeepSWE v1.1 上追平 Astra，价格只有五分之一（$2/$10 vs $10/$50），缓存读取还便宜一半。**新项目默认选 Sol 而不是 Astra**，除非任务确实是 frontier 级。
- **Anthropic 的缓存策略最激进**。Fable 5.1 的缓存读取砍到 0.025×、Opus 5.5 是 0.05×，而 OpenAI 与 Google 的旗舰都还在 0.1×。Anthropic 自己的说法是「缓存读取构成 agentic 与编码工作成本的主体」——如果你的负载是高缓存命中的 agent 循环，**Anthropic 的实际账单优势远大于标价显示的**。
- **Google 的 2M 上下文仍是当前可公开调用模型里独一份**（Gemini 3.1 Pro；Argon 的 1M 是输出上限而非上下文，其上下文长度未公布），适合超长文档单体处理（整本手册、整个代码库一次性喂入）。代价是 200K 就开始加价，且 thinking token 计费口径最激进、缓存还要另收按小时的存储费。

厂商名的自有细节见 [OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)、[Claude](/docs/CS/AI/LLM/Model/Claude.md)、[Gemini](/docs/CS/AI/LLM/Model/Gemini.md)。

## Chinese Model Comparison

这一组的共同点是**权重开源**，但「开源」的成色差别极大，必须逐个看协议：

| 厂商 | 当前型号 | 权重 | 协议 | 上下文 | API 定价 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| DeepSeek | V4.1-Flash / V4-Pro | ✅ | 开源（研究许可） | **1M** | ✅ **$0.15／$0.60 起，峰谷分时** |
| Qwen | Qwen3.8-27B / 2.4T-A95B | ✅ | 27B Apache-2.0；2.4T 自定义 | 262K～1M | 托管为主 |
| 智谱 GLM | GLM-5.3 | ✅ | ⚠️ 旗舰转自定义 | **1M** | 有 |
| 月之暗面 | Kimi K3（2.8T） | ✅ 仅权重 | 自定义 | **1M** | 有 |
| MiniMax | MiniMax-M2 | ✅ | ⚠️ Modified MIT | — | 有 |
| 阶跃星辰 | **Step 5 Preview**（600B/27B） | ✅ 2026-10-15 开源 | ⚠️ StepFun Model License 1.0 | **1M** | ✅ **¥7／¥20（约 $1／$2.70）** |
| 讯飞星火 | X2.5 | ⚠️ 仅端侧 4B/1.7B | — | 256K | — |

**五个最容易记错的点**：

- **「国产模型都开源」不成立**。星火只开源了端侧小模型，293B 基座不开源；Kimi K3 **只开权重，训练代码与数据不开源**，严格说是 open-weight 不是 open source。
- **协议正在集体收紧**。Qwen 的旗舰 MoE 从 Apache-2.0 换成自定义协议；GLM 旗舰 GLM-5.3 从 MIT 转自定义；MiniMax-M2 是 Modified MIT 而非 Apache-2.0；Step 5 Preview 的 StepFun Model License 1.0 自称 Apache-2.0-style，却加了署名、硬件厂商单独授权与 MaaS 营收门槛。**只有 Llama 系与 Qwen 的部分 dense 型号还留在宽松协议上**，而且 Llama 那份见下条。
- **Llama 4 的开源标签是误传**。它是 `Llama 4 Community License Agreement`，**允许商用**，真正的限制是 7 亿 MAU 门槛、欧盟多模态禁令、署名义务与竞品训练禁令。而 Meta 在 2026-08 转向了 Apache-2.0 的 Muse Glimmer，所以**今天真正「宽松开源」的 Meta 模型反而是新的那个**。
- **国产算力已能跑前沿模型训练**。GLM-5 被官方描述为首个全流程在非 NVIDIA 算力上训练的前沿模型，SGLang 官方硬件页把昇腾 NPU 与摩尔线程 MUSA 列为原生支持平台。瓶颈在 MoE 的 all-to-all 通信（约为国际旗舰的 50–65%）。
- **Step 5 Preview 的缓存价在 2026-10-14 翻倍，且只对新用户生效**。缓存命中输入从 0.35 调到 0.70 元／百万 tokens，首次调用在调价前的用户保留旧价——按 10-14 前的旧教程估 Agent 循环成本会低估一半，而这类负载的输入 token 约 96% 命中缓存，差额全在缓存价上。

各家详情见 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)、[Qwen](/docs/CS/AI/LLM/Model/Qwen.md)、[StepFun](/docs/CS/AI/LLM/Model/StepFun.md)、[开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)。

## Three Real Selection Logics

看完上面的表，容易得出「按价格挑最便宜的」这个结论，但实际选型要复杂一些。真正起作用的是这三条：

**第一条：按任务分档，不按品牌分档。** 抽取、分类、客服、批处理这类任务在 GPT-6 Luna 或 Gemini 3.8 Flash 这个档位就够，用旗舰模型是纯浪费。反过来，复杂 agentic coding 才值得上 Sol／Opus 这档。中间大部分业务其实应该停在经济档——Anthropic 自己的分档建议是 Sonnet 默认、Haiku 处理高吞吐负载，只有最难的任务才动 Opus。

**第二条：算成本要把缓存与 thinking 算进去。** 标价只影响输入输出两项，实际账单里经常藏着两块：缓存命中率与 thinking token。一段 10 万 token 的系统提示在 90% 缓存命中下跑一万次，0.025× 与 0.1× 的差距就是数十倍；而开了 extended thinking 的模型，推理 token 按输出价计费，可能比可见回答长一个数量级。**这两个参数不设对，省钱的空间比换厂商大得多**。

**第三条：长上下文负载必须先确认加价规则。** 这是最容易被「上下文窗口都标 1M 以上」这句话掩盖的差异——OpenAI 272K 台阶、Google 200K 台阶，都是整单重算而非按量分段。如果你就是要把整个代码库或超长文档一次性塞进去，Anthropic 与 DeepSeek 的无台阶结构是结构性优势，会随单请求 token 数增长持续拉开差距。

**什么时候该多供应商**：当能力档位接近时（$2/$10 这个价位已经有 Sol、Sonnet 5.5、Gemini 3.1 Pro 三家），把「用哪家」变成一个按实时价格与可用性做的路由决策，而不是冻在两季度前写下的 SDK import 里。DeepSeek 的峰谷定价尤其适合做这件事——把批处理与夜间跑批路由到空闲时段，账单直接砍半。

## A Different Class: Decision Models

上面所有价格与档位比的都是同一类东西——**会生成文本的模型**。但 Agent Harness 里有一大批调用根本不需要文本：意图路由、风险门控、严重度打分。这类「输入自由文本加一条判断标准、输出必须被代码直接消费」的任务，用旗舰模型写 Prompt 太慢且格式偶发不稳，自训一个 BERT 级分类器又快又准但零迁移。2026 年 9 月出现的**决策模型（System One model）**是第三条路：TypeSafe 的 [Jev](/docs/CS/AI/LLM/Model/Jev.md) 把生成能力整个砍掉，只返回类型化判断（Choice / Score / Noul）与**校准过的置信度**，输入 $0.042/MTok、**输出免费**，端到端 70~500 ms。

它的价值不来自「更聪明」，而来自**概率可信**：RLHF 之后的 LLM 会系统性过度自信，所以 `if confidence > 0.9` 这种写法在生成模型上一直没有统计意义，而决策模型把校准本身当训练目标（原因见 [Jev](/docs/CS/AI/LLM/Model/Jev.md?id=calibrated-probabilities-and-confidence)）。选型判据因此不是能力档位而是**答案空间是否封闭**：封闭选项、等级与是非判断可以切过去，要生成、要解释、要多跳推理的仍回到上面那张表。下表按「闭源托管 / 开权重自托管 / training-free」把这一格的玩家列全：

| 形态 | 模型 | 厂商/作者 | 底座 | 许可 | 接口兼容 | 一句话定位 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 闭源托管 | **Jev** | TypeSafe AI | —（未公开） | 闭源 API | 事实标准 | 品类开创者，RLCD 校准 |
| 闭源托管 | **OpenAI Decisions API** | OpenAI | GPT-6 Luna | 托管 | 自研 | 接受**图像**输入，Jev 仅文本 |
| 开权重自托管 | **Clef / Clef-flash / Clef-omni** | Cloudflare | 冻结 Qwen3.8/3.5 + LoRA | Apache-2.0 | Jev-API 兼容 | omni 多模态，flash 压价低于 Jev |
| 开权重自托管 | **AWS Strands Decider 2B** | AWS | 自托管 | Apache-2.0 | Jev-API 兼容 | 2B，vLLM 部署 |
| 开权重自托管 | **Laya** | Convai Innovations | ModernBERT-large 421M + mmBERT 322M | Apache-2.0 | laya-serve 兼容 | CPU 友好、100+ 语言，需微调 |
| 开权重自托管 | **Kev** | Jared Palmer | Qwen3.5（0.8B/4B/9B）+ Qwen3.8（27B）LoRA | Apache-2.0 | TypeSafe SDK 零改动 | System One Score **第一**，最可替换 |
| training-free | **SemIf** | TheoLeeCJ | 冻结 Qwen3.5-4B（或 MiniCPM5 2B） | MIT | 自研（读 logits） | 不训练、单张 3090 跑 4B |

能被换掉的实现说明品类成立，也说明这一格没有护城河——判断口径、语义差异与阈值迁移陷阱见 [Jev](/docs/CS/AI/LLM/Model/Jev.md?id=the-interface-won-jev-compatible-decision-models)；各家完整型号表、定价与架构见 [Kev](/docs/CS/AI/LLM/Model/Kev.md) 与 [SemIf](/docs/CS/AI/LLM/Model/SemIf.md)。

## Local Deployment: A Parallel Path

上面所有价格都是云端 API。但只要负载够稳定，自托管就从成本题变成能力题：把「每百万 token 多少钱」换成「一张卡跑多久」，高频固定负载下自建几乎总是更便宜，且**数据不出内网**这个合规收益往往比省钱更关键。

2026 年的现实是三条路径各有位置：**Ollama** 零配置、是本地体验的默认入口；**vLLM** 高吞吐生产级服务；**SGLang** 在 agentic 场景与国产卡支持上最现实；**llama.cpp** 是 CPU 与边缘设备之王。量化格式已无单一主流，按硬件分层是共识——FP8 是数据中心默认，GGUF 是 CPU 与 Apple Silicon 的甜点，AWQ/GPTQ 仍是常规 GPU 服务的主力。

细节见 [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)、[开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)。

## Convergence at the Architecture Level

最后一件值得跨厂商记住的事：**2026 年出现了多路独立的架构收敛**——**混合线性注意力 + MoE**。Kimi KDA、Qwen3.5 Gated DeltaNet、GLM-5 DeepSeek Sparse Attention、GLM-5.3-Flash 的线性与稀疏混合，走的是同一个方向。这条收敛的直接后果是**长上下文场景的 KV cache 成本在快速下降**，DeepSeek V4.1-Flash 的 cache 在 HBM 缩小 4 倍、SSD 缩小 8 倍是同一趋势的极端案例。

这也解释了为什么各家的上下文标称值都在往 1M 冲而成本没有失控——底层已经不是纯 attention 的 O(n²) 了。架构细节见 [Transformer](/docs/CS/AI/Transformer.md) 与各模型专页。

## Links

- [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)
- [OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)
- [Claude](/docs/CS/AI/LLM/Model/Claude.md)
- [Gemini](/docs/CS/AI/LLM/Model/Gemini.md)
- [Qwen](/docs/CS/AI/LLM/Model/Qwen.md)
- [开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [Post-Training：模型是怎么造出来的](/docs/CS/AI/LLM/Model/Post_Training.md)
- [Jev](/docs/CS/AI/LLM/Model/Jev.md)
- [StepFun](/docs/CS/AI/LLM/Model/StepFun.md)
- [Kev](/docs/CS/AI/LLM/Model/Kev.md)
- [SemIf](/docs/CS/AI/LLM/Model/SemIf.md)

## References

- [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI DevDay 2026 Recap](https://openai.com/index/devday-2026-recap)
- [DeepSeek API Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Introducing Claude Sonnet 5.5](https://www.anthropic.com/news/claude-sonnet-5-5)
- [Introducing Muse Glimmer: An Open Agentic Model That Runs on Your Device](https://research.meta.ai/blog/introducing-muse-glimmer-open-agentic-model)
- [Qwen3.8 GitHub](https://github.com/QwenLM/Qwen3.8)
- [Kimi K3 GitHub](https://github.com/MoonshotAI/Kimi-K3)