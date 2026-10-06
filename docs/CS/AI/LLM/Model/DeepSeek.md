## Introduction

> **版本基线：2026-10-05 核实。** API 型号与价格以 [官方定价页](https://api-docs.deepseek.com/quick_start/pricing) 为准；架构与参数以 [HuggingFace 组织页](https://huggingface.co/deepseek-ai) 与技术报告为准。

[DeepSeek](https://www.deepseek.com) 是杭州深度求索人工智能基础技术研究有限公司的产品。它最早因「开源权重 + 极低定价」成名，而到 2026 年 10 月，它的 API 已是全球最便宜的前沿模型之一——同能力档位下比 OpenAI 与 Anthropic 低一到两个数量级，这条价格优势来自它独特的 **峰谷分时定价**，而不是阶段性补贴。

本文只记模型与 API 事实。Agent 侧的 [DeepSeek Harness（dsh）](/docs/CS/AI/LLM/Agent/Product/DSH.md) 另有一篇。

## API 型号

DeepSeek API 现在只有**两个**在售模型，都同时提供 OpenAI 兼容格式（`https://api.deepseek.com`）与 Anthropic 兼容格式（`https://api.deepseek.com/anthropic`）两个 Base URL。

| 模型名（API） | 版本 | 上下文 | 最大输出 | 视觉 |
| :--- | :--- | :--- | :--- | :--- |
| `deepseek-flash` | DeepSeek-V4.1-Flash | 1M | 384K | ✅ 原生 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro-0813 | 1M | 384K | ❌ |

几个容易踩的点：

- **`deepseek-flash` 就是 V4.1-Flash**。V4.1-Flash 于 2026-09-09 正式 GA，替代了此前的 V4-Flash。
- **旧型号名仍能被接受，但背后已是新模型**：`deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp` 这两个名字仍然解析成功，请求会由 V4.1-Flash 处理并按 Flash 价计费。旧名能调通不代表你在用旧模型。
- **`deepseek-chat` 与 `deepseek-reasoner` 已于 2026-07-24 彻底下线**，不可访问。这两个是早期把「对话模型」与「推理模型」拆成两个名字的产物，现在统一为单模型 + thinking 开关。
- **`deepseek-v4-pro` 正在退场**：自 2026-09-14 04:00 UTC 起，其流量被路由到 V4.1-Flash 并按 V4.1 费率计费，除非显式要求保留 V4-Pro 服务。

## Thinking 模式

两个模型都支持 non-thinking 与 thinking 双模式，**默认是 thinking**。这与「Ollama 之类本地推理默认不思考」的直觉相反，接入时若发现输出带一大段推理过程而调用方没要求，先检查这个默认值。

另外两个 Beta 能力只存在于 **non-thinking 模式**：`Chat Prefix Completion` 与 `FIM Completion`（代码补全）。依赖这两个能力的代码补全工具，如果切到 thinking 模式会失效。

功能支持矩阵：两模型都支持 Json Output、Tool Calls、**Responses API**、**Anthropic API**。后者意味着 Claude Code、Claude Agent SDK 这类按 Anthropic 协议写的工具可以直接指向 DeepSeek，无需改代码——这是 DeepSeek 相比其他国产厂商比较实用的一点。

## 架构演进

DeepSeek 的模型演进不是靠堆参数，而是靠改架构。几个关键节点：

| 代次 | 关键变化 |
| :--- | :--- |
| V2 | 引入 MLA（Multi-head Latent Attention），把 KV cache 压到传统 MHA 的一小部分 |
| V3 | MoE + FP8 训练，激活参数极低使成本大幅下降；DeepSeekMoE 提出更细粒度的专家专精 |
| R1 | 推理模型，通过强化学习激发推理能力，对标当时的 o1，让「会思考」成为独立产品线 |
| V4.1-Flash | **Causal Encoder–Decoder 架构** + 原生视觉 |

V4.1-Flash 的架构细节值得单独说：

- **552B 总参数，MoE**，但**输入侧激活约 8B、输出侧约 16B**。这是一个不对称的 Encoder–Decoder 设计：读输入（长文档、检索上下文、代码库）走便宜的编码器路径，只有真正要生成的 token 才走更贵的解码器路径。**Prompt 越重的负载越划算**，这正好命中 RAG 与代码库场景。
- **KV cache 在 HBM 中缩小 4 倍、SSD 中缩小 8 倍**。自部署开源权重时这个数字直接决定单卡能塞多少并发长上下文会话，是比参数量更值得先看的指标。
- **视觉能力内联进模型**，所以此前独立的实验版视觉型号 `deepseek-v4-flash-vision-exp` 被下线——不是砍功能，是把能力搬进了主模型。

DeepSeek 权重与各代技术报告一贯发布在 HuggingFace，与此前版本一致。

## 定价 峰谷分时

这是 DeepSeek 目前最有辨识度的机制，也是「为什么这么便宜」的答案。

**空闲时段价格是高峰时段的一半**，按 UTC 时间划分：

- **高峰**：周一至周五 01:00–04:00 与 06:00–10:00 UTC（不含中国法定节假日），对应北京时间 09:00–12:00 与 14:00–18:00
- **空闲**：其余全部时段，含周末与节假日

168 小时里只有 35 小时是高峰，所以负载均匀分布的工作负载实际只比空闲价贵约 21%。

> ⚠️ **这不是「夜间更便宜」的促销，而是反向的**：中国白天（业务高峰）最贵，欧美夜间最便宜。做成本估算时如果按全天均值算，会低估约 20%；但如果业务能主动错峰调度到空闲时段，账单能实打实砍半。批量任务、夜间跑批天然落在空闲侧。

价格表（美元／百万 token，2026-10-05 官方页面）：

| 模型 | 时段 | 输入（缓存命中） | 输入（未命中） | 输出 |
| :--- | :--- | :--- | :--- | :--- |
| `deepseek-flash` | 空闲 | $0.003 | $0.15 | $0.60 |
| `deepseek-flash` | 高峰 | $0.006 | $0.30 | $1.20 |
| `deepseek-v4-pro` | 空闲 | $0.022 | $0.66 | $1.98 |
| `deepseek-v4-pro` | 高峰 | $0.044 | $1.32 | $3.96 |

中文定价页给出同样结构的人民币价：Flash 空闲 0.02／1／4 元，Pro 空闲 0.15／4.5／13.5 元（顺序为缓存命中输入／未命中输入／输出，每百万 token）。

**缓存命中价只占未命中价的 1/50 到 1/66**，这是全场最悬殊的一档。所以对 DeepSeek 而言，稳定系统提示词的收益比在别家更大——缓存命中率从 50% 提到 80%，输入成本直接降到四分之一。

并发限制**按账号计**而非按 API key：Flash 2500、Pro 500。超额返回 HTTP 429，可申请扩容（免费）。另有 `user_id` 参数可隔离 KV cache、调度与内容安全处理，适合在一个账号内服务多个终端用户。

## 定价演进

V4-Pro 的价格在 2026 年内经历了多次调整，写文档时必须带日期，否则很快就是错的：

| 生效时间 | 模型 | 输入未命中 | 输出 |
| :--- | :--- | :--- | :--- |
| 2026-04-24 | V4-Pro 预览 | $1.74 | $3.48 |
| 2026-04-25 | V4-Pro 折扣 75%（原定至 05-05） | — | — |
| 2026-05-22 | 折扣转为永久 | $0.435 | $0.87 |
| 2026-08-17 | 引入峰谷定价 | — | — |
| 2026-09-09 | V4-Pro 调至现价 | $0.66 | $1.98 |

长期流传的旧价格表（比如 V4-Flash 输入 $0.14／输出 $0.28）都是 2026-08-16 之前的平价时代产物，已完全失效。

## 中国模型横向位置

把 DeepSeek 放进整个市场看，它的位置很清楚——**不是最强的模型，是最便宜的开源前沿模型**：

- 能力档位低于 OpenAI GPT-6 Astra 与 Claude Opus 5.5 这一档（官方称 V4.1-Flash 基准高于此前的 V4-Pro，但与顶级闭源旗舰仍有差距）
- 价格低一到两个数量级：Flash 的 $0.15／$0.60 对 GPT-6 Luna 的 $0.10／$0.50 与 Claude Sonnet 5.5 的 $2／$10
- 权重开源，可自部署
- 1M 上下文 + 384K 最大输出，在国产模型里属第一梯队

对绝大多数应用负载（客服、抽取、分类、批处理、代码补全），用 Flash 这个档位就够，真正的成本压力根本不该出现在这一层。需要在 DeepSeek 与 OpenAI／Anthropic 之间做路由的策略见 [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)。

## 与国产同门的差异

| 维度 | DeepSeek | Qwen | GLM | Kimi |
| :--- | :--- | :--- | :--- | :--- |
| 权重开源 | ✅ | ✅（27B 为 Apache-2.0） | ✅（旗舰转自定义协议） | ✅（仅权重，训练代码与数据不开源） |
| API 定价 | 最低档（峰谷分时） | 不提供公有 API 主线 | 有 | 有 |
| 特色能力 | encoder–decoder MoE，KV cache 极小 | 混合线性注意力，长上下文 | 首个全流程非 NVIDIA 算力训练 | 2.8T 级最大开放权重模型 |
| 协议兼容 | OpenAI + **Anthropic 双格式** | OpenAI 兼容 | OpenAI 兼容 | OpenAI 兼容 |

DeepSeek 是少数直接提供 **Anthropic 兼容 Base URL** 的国产厂商，这让 Claude Code／Claude Agent SDK 生态的工具可以零改动接入，在国产模型里是独特优势。

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [DeepSeek Harness（dsh）](/docs/CS/AI/LLM/Agent/Product/DSH.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [DeepSeek API 定价（官方）](https://api-docs.deepseek.com/quick_start/pricing)
- [DeepSeek API 文档](https://api-docs.deepseek.com/)
- [DeepSeek HuggingFace 组织页](https://huggingface.co/deepseek-ai)
- [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)