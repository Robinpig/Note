## Introduction

> **版本基线：2026-10-05 核实。** 型号、上下文与价格以 [Claude 定价页](https://claude.com/pricing) 与各模型页为准；发布日期与安全变更以 [Anthropic 官方发布页](https://www.anthropic.com/) 为准。`docs.claude.com` 在部分区域会被重定向拦截，本文数据经官方定价页、模型页、发布说明与 AWS Bedrock / Google Cloud Vertex AI 模型卡交叉核对。

[Anthropic](https://www.anthropic.com) 的 Claude 家族在 2026 年下半年**几乎换了一遍**：Fable 5.1（09-01）、Opus 5.5（09-22）、Sonnet 5.5（09-28）三款在 20 天内连发，前一代 Opus 5（07-24）与 Sonnet 5（06-30）已经退居legacy。Anthropic 的档位命名是 **Fable（最贵）／Opus（旗舰）／Sonnet（主力）／Haiku（最快最便宜）**，价格与定位一一对应，**没有中间的空档**——这是与 OpenAI 三档 GPT-6 最明显的结构差异。

Claude Code 这个命令行工具另有专篇 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)。本文只记模型本身。

## Current Lineup

| 模型 | API ID | 发布 | 上下文 | 最大输出 | 输入 | 输出 | 知识截止 |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| Claude Fable 5.1 | `claude-fable-5-1` | 2026-09-01 | 1M | 128K | $10 | $50 | 2026-06 |
| **Claude Opus 5.5** | `claude-opus-5-5` | 2026-09-22 | 1M | 128K | $4 | $20 | 2026-06 |
| **Claude Sonnet 5.5** | `claude-sonnet-5-5` | 2026-09-28 | 1M | 128K | $2 | $10 | 2026-06 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 2025-10-15 | 200K | 64K | $1 | $5 | 2025-02 |

**Haiku 5.5 已被官方点名但截至 2026-10-05 仍未发布。** 2026-09-22 的 Opus 5.5 发布页说 Sonnet 5.5 与 Haiku 5.5 会在「未来几周」加入 5.5 家族——Sonnet 5.5 已兑现，Haiku 5.5 没有：定价页无条目、模型文档无条目、模型 ID 查无此模型，日期与价格均未公布。Haiku 4.5 因此仍是当前最小档，且它已经**在位343 天**，同期的 Sonnet 走过了 4.5、4.6、5 三代。

同平台还有 **Claude Mythos 5.1**：与 Fable 5.1 **同一个底层模型、不同 safeguards**，只通过 trusted access programs（Project Glasswing）向经过审核的网络安全与生命科学机构开放，不在公开定价页里。

## Capability Tiers and effort

Claude 的推理控制是 **effort 参数**，取值 `low / medium / high / xhigh / max`，配合 **adaptive thinking**——始终开启且**无法关闭**。

| 模型 | thinking 模式 | 默认 effort | 相对延迟 |
| :--- | :--- | :--- | :--- |
| Fable 5.1 | adaptive，始终开 | high | 慢 |
| Opus 5.5 | adaptive，始终开 | **medium** | 中|
| Sonnet 5.5 | adaptive | high（Claude Platform）／medium（Claude Code 与客户端） | 快 |
| Haiku 4.5 | extended thinking，手动 `budget_tokens` | 不支持 effort 参数 | 最快 |

几个必须知道的迁移陷阱：

- **thinking 关不掉了。** Opus 5.5 与 Fable 5.1 上带 `thinking: {"type": "disabled"}` 的请求返回 400。Opus 5.5 的深度旋钮只剩 effort，默认是 **medium**——比 Opus 5 的默认更保守，这意味着不显式设 effort 的迁移会**悄悄变便宜也变弱**。而且**已保存的 effort 设置不迁移到新模型**，Opus 5.5 一律从自己的 medium 起步。
- **Haiku 4.5 不认 effort 参数**（返回 400），它用手动 extended thinking 加 `budget_tokens`，默认关闭。它也是唯一没有 adaptive thinking 的当前模型。
- **工具调用也变了**：强制工具使用（`tool_choice` 为 `any` 或指定 `tool`）在 Opus 5.5 与 Fable 5.1 上直接报错；旧的 `computer_20251124` computer use 工具在 Claude API 与 Google Cloud 上不再接受，需改用 `computer_toolset_20260801`。
- **另一个不报错但会静默改变响应形状的改动**：工具调用之间的文本现在放在 thinking block 里，默认 display 设置下这些 block 的 text 为空。**把这段文本当进度更新流式推给用户的应用，在两次工具调用之间会突然安静下来**，直到显式设置一个能返回该文本的 display 值。

## Pricing and Caching

| 模型 | 输入 | 5 分钟缓存写入 | 1 小时缓存写入 | 缓存读取 | 相对缓存倍率 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Fable 5.1 / Mythos 5.1 | $10 | $12.50 | $20 | $0.25 | **0.025×** |
| Opus 5.5 | $4 | $5 | $8 | $0.20 | **0.05×** |
| Sonnet 5.5 | $2 | $2.50 | $4 | $0.20 | 0.1× |
| Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | 0.1× |

单位美元／百万 token。**Batch API 全系五折，且与缓存折扣叠加。**

缓存倍率不再统一，这是 2026 年 Anthropic 定价里最容易被忽略的变化：

- **Fable 5.1 把缓存读取砍到 $0.25（0.025×）**，比 Fable 5 的 $1.00（0.1×）**便宜 75%**，而标价仍是 $10／$50 不变。Anthropic 估算典型负载总账单降约 25%，高度 agentic 的负载降约 45%。**如果你的 Fable 账单大头是缓存读取，换5.1 是纯赚。**
- **Opus 5.5 的缓存读取是 0.05×（$0.20）**，比标准 0.1× 档再便宜一半，与 Sonnet 5.5 读缓存同价。Anthropic 明确说「缓存读取构成 agentic 与编码工作成本的主体」，所以旗舰与主力档在这条线上只差 input／output。
- **缓存写入最低可缓存长度**：Opus 5.5 与 Sonnet 5.5 是 **512 token**（Sonnet 5.5 从 Sonnet 5 的 1024降了下来），**Haiku 4.5 仍是 4096 token**——短系统提示在 Haiku 上根本不进缓存。
- **1M 上下文不加价**。Claude 4.6 及之后的模型整个 1M 窗口按标准价计费，**没有 OpenAI 那种 272K 长上下文台阶**。这是两家定价结构上最大的差异：同样把一个 900K token 的仓库丢进去，Anthropic 按 $4/$20 算，OpenAI 按 $20/$75 算。
- **fast mode 目前只有 Opus 5.5 有**，价格 2 倍标准价（$8／$40），宣称最高约 2.5× 速度。Sonnet 5.5 没有 fast mode。
- **US-only inference 单价1.1×**（输入与输出），与 OpenAI 的区域处理加价幅度一致。Bedrock 上按区域定价，见下方多平台一节。

## Parameter Count: Not Disclosed

**Anthropic 从未官方公开过任何 Claude 模型的参数量。** Opus 5.5 与 Sonnet 5.5 的官方模型页与系统卡都只描述训练方法（「在大型多样化数据集上预训练，之后进行大量后训练以对齐 Claude 宪法」），**不给参数量、不给权重规模、不给 dense 还是 MoE、不给层数与专家数**。

网上流传的「Opus 5T／Sonnet 1T」等数字来源是马斯克在讨论 xAI Colossus 2 算力时的一句比较（说 Grok 是Sonnet 的一半、Opus 的十分之一），以及各类二手推算，**都不是 Anthropic 的披露**。这类数字连对应哪一版模型都不确定，不要写进技术方案。官方唯一给出的规模相关表述是「Opus 5.5 服务所需的算力低于 Opus 5」——这是计算效率声明，不能反推参数。

## Sonnet 5.5 Security Changes

Sonnet 5.5 是这一代最容易被低估的模型，它带了两项**其他 Sonnet 没有的**机制：

- **首个带防推理提取安全分类器的 Sonnet 模型**。针对的是 distillation attack（蒸馏攻击）——用成千上万个假账号在工业规模上套取模型能力。Sonnet 5.5 因为能力显著强于 Sonnet 5，发布时即配备阻止推理提取的分类器。
- **preserved thinking 扩展**：Claude 的 thinking **不能再与其创建它的账号解耦**。多数开发者察觉不到，但**在 Claude Code 会话中途切换账号、或把会话在账号之间迁移**，就会受影响。
- **迁移必须切`between_tools` 设置**：如果你原来跑的是 thinking 关闭的 Sonnet，切到 Sonnet 5.5 前需要改用新的 `between_tools` 设置（它保持 up-front thinking 关闭）。沿用旧的关闭方式会失败。
- **网络安全防护与 Opus 5.5 同级**，高风险网络安全请求会可见地回落到 Sonnet 5；生物学防护沿用 Sonnet 5 的那一套。

##型号演进与管制事件

Claude 的型号历史比 OpenAI 更连续，但2026 年 6 月发生了一件值得记住的事：

| 日期 | 事件 |
| :--- | :--- |
| 2026-06-09 | Fable 5 与 Mythos 5 发布，同底层模型，Fable 带强防护面向大众，Mythos 少防护仅供 Glasswing 防御性用途 |
| 2026-06-12 | **美国政府对两者施加出口管制**，要求限制外国国民访问；因无法实时核验国籍，Anthropic 对**全部用户**暂停 |
| 2026-06-26 | 美国政府批准，Mythos 5 先恢复给一部分美国机构 |
| 2026-06-30 | 出口管制解除 |
| 2026-07-01 | Fable 5 全球恢复（Claude Platform、Claude.ai、Claude Code、Claude Cowork） |

起因是 Amazon 研究人员报告了一种绕过 Fable 5 防护的方法：提示模型识别软件漏洞，并在一例中产出了演示如何利用该漏洞的代码。Anthropic 与多方复测发现**能力更弱的模型（Opus 4.8、GPT-5.5、Kimi K2.7、Haiku 4.5、Sonnet 4.6 等）都能产出同样的利用演示**，该技术并未暴露 Mythos 级别的独占能力。此后 Anthropic 训练了新的安全分类器，官方称可阻断该报告所述技术 **99% 以上**的情形；请求被拦时会转交给 Opus 4.8。

**这次事件对架构设计的教训是具体的**：把关键工作流押在单一模型上，等于把监管介入当成可用性风险来 budgeting。Anthropic 自己也在事后与 AWS、Microsoft、Google 等 Glasswing 伙伴一起推动「jailbreak 严重度分级」的公共框架。**Fable 5.1 的防护也比 Fable 5 更精准**：Claude Code 用户每会话的安全防护干预次数减少约 60%。

其他版本节点：Opus 4.6 → 4.7 → 4.8 → Opus 5（2026-07-24，接近 Fable 5 智能水平、价格减半）→ Opus 5.5。Opus 5.5 单位价格比 Opus 5 低 20%（$5→$4、$25→$20），缓存读取低 60%，Anthropic 称综合token 用量下降后典型负载**总成本降约 40%**——**这是复合降价，不是单价降价**，两个因子都会动。Opus 5 与 4.6／4.8 同价（$5／$25）、Sonnet 4.6（$3／$15）也更贵，**当前每一档里最新的型号都是最便宜的或并列最便宜的**。

## Benchmarks

厂商自报，且两家选的评测集不同、effort 设定与 harness 不同，**不是受控对比**。

| 基准 | Opus 5.5 | Sonnet 5.5 | Fable 5.1 | GPT-6 Astra | GPT-6 Sol |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Terminal-Bench 4.0 | 66.4%（xhigh） | **70.6%** | 55.8% | 57.9%（high） | 未公布 |
| FrontierCode v1.1 Main | 54.4%（max） | — | 50.3% | 53.3%（max） | 49.3%（max） |
| GDPval-AA v2.1（Elo） | **1846** | 1844 | 1735 | 1542 | 1487 |
| CursorBench 4.0 | 57.8%（max） | — | 51.8% | 未公布 | 未公布 |
| Humanity's Last Exam（带工具） | **67.7%** | — | 65.6% | 57.2% | — |
| OSWorld 2.0 | 81.8%（partial） | — | 77.9%（partial） | 72.6% | 64.4%（离线集） |
| Terminal-Bench-Science 0.1 | 58.7%（max） | — | 52.6% | 64.6% | 未公布 |
| AutomationBench | 40.0%（max） | — | 31.4% | 41.4%（max） | 33.2%（xhigh） |
| DeepSWE v1.1 | 74.2% | — | — | 未公布 | 68.8%（max） |

注意几件事：

- **Sonnet 5.5 在 Terminal-Bench 4.0 上（70.6%）高于 Opus 5.5（66.4%）**，但 Anthropic 自己指出 Opus 5.5 在需要持续判断的开放式复杂工作上仍明显更强。Terminal-Bench 的标准误约 ±2.6。
- **GDPval-AA 上 Sonnet 5.5 与 Opus 5.5 只差 2 分Elo**（1844 vs 1846），而价格差 2 倍。该分数由 Artificial Analysis 在一个**预发布部署**上跑，那个版本有个会影响结构化输出请求的 bug，已修，Anthropic 认为影响小但可能**低估**了 Sonnet 5.5。
- **FrontierCode v1.1 会惩罚越界改动**，即使改动本身质量高。Sonnet 5.5 在 max effort 下得分反而低于 xhigh，因为更常调用 Claude Code 的 code-review skill（把评审拆给多个子智能体），两次出现超时或超范围编辑。**这个基准对「爱干净」的模型有系统性偏差**。
- Sonnet 5.5 的 GDPval-AA 与 AA-Briefcase 由 Artificial Analysis 跑，Chartography 来自 Surge AI；OpenAI 同期修复了 GPT-6 Sol 图像理解的 bug，公开数字可能未反映。

## Multi-Platform

同一批模型在五个平台上架，价格一致：

| 平台 | 模型 ID 形式 |
| :--- | :--- |
| Claude API | `claude-opus-5-5` |
| Amazon Bedrock | `anthropic.claude-opus-5-5` |
| Google Cloud Vertex AI | `claude-opus-5-5` |
| Microsoft Foundry | `claude-opus-5-5` |
| Claude Platform on AWS | `claude-opus-5-5` |

**AWS Bedrock 上 Claude 的区域定价与美国区一致**（同一模型在 us-east-1 与 eu-central-1 同价），不存在 OpenAI 那种区域加价。但 Bedrock 有自己的一套服务层级命名：`default` / `priority` / `flex` / `reserved`，与 Anthropic API 的 fast mode 不是同一套东西，跨平台迁移时别直接映射。

`claude-opus-5-5` 这类**不带日期后缀的名字是便利别名**，会解析到固定快照（Haiku 4.5 是 `claude-haiku-4-5` → `claude-haiku-4-5-20251001`）。要真正锁死行为就用带日期的快照。

## Model Selection Recommendations

- **不确定就用 `claude-opus-5-5`**。Anthropic 自己在每个模型页都写这句：Opus 5.5 在多数工作上达到 Fable 5.1 的水平，价格只有 Fable 5.1 的 40%。只有当你在更高 effort 下自建评测仍然不够时，才需要为 Fable 5.1 的 2.5 倍溢价买单。
- **主力编码与知识工作用 `claude-sonnet-5-5`**。与 Sonnet 5 同价（$2／$10），但更快 30%+、每任务 token 数更少，**Anthropic 估算每任务成本最多降 30%**——省的是 token 量不是费率，这与 2026 年多数「价格不变但推理 token 暴涨」的升级方向相反，值得在自己流量上验证。Sonnet 5.5 也是 Claude Code 生态里的默认档。
- **Haiku 5.5 发布前，批量负载只能靠 Haiku 4.5**，注意它200K 上下文、4096 token 缓存下限、不支持 effort，以及 **2025-02 的知识截止**（比其他型号早了一年多）。
- **不要用 ChatGPT 式的一次性自动路由思维**。Claude 的档位是明确的能力台阶，路由策略应该自己做：Sonnet 优先，失败或低置信度时升级到 Opus。
- **Claude 4.7 起的 tokenizer 对同样文本会产生约多 30% 的 token**。从 Opus 4.6 及更早版本迁移过来的负载，**token 用量会自然上涨**，这部分涨幅不是行为退化造成的，别误判成模型变啰嗦。
- 完整的模型路由与成本对比见 [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)，与国产模型的横向位置见 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md) 与 [Qwen](/docs/CS/AI/LLM/Model/Qwen.md)，OpenAI 侧见 [OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)。

## Links

- [Gemini](/docs/CS/AI/LLM/Model/Gemini.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Claude 定价页（官方）](https://claude.com/pricing)
- [Introducing Opus 5.5（2026-09-22）](https://www.anthropic.com/claude-opus-5-5)
- [Introducing Sonnet 5.5（2026-09-28）](https://www.anthropic.com/claude-sonnet-5-5)
- [Introducing Fable 5.1 and Mythos 5.1（2026-09-01）](https://www.anthropic.com/claude-fable-and-mythos-5-1)
- [Redeploying Claude Fable 5（2026-07-01）](https://www.anthropic.com/news/redeploying-fable-5)
- [Anthropic's Transparency Hub（系统卡与安全评估）](https://www.anthropic.com/transparency)
- [Models overview | Claude Platform](https://docs.anthropic.com/en/docs/about-claude/models/overview)
- [Release notes | Anthropic Help Center](https://docs.anthropic.com/en/release-notes/claude-apps)
- [Claude Opus 5.5 — Amazon Bedrock 模型卡](https://docs.aws.eu/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)
- [Claude Haiku 4.5 — Amazon Bedrock 模型卡](https://docs.aws.amazon.com/us_en/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html)