## Introduction

> **版本基线：2026-10-05 核实。** 型号参数与许可证以 HuggingFace / ModelScope 的 `config.json`、`LICENSE` 原文为准；发布日期取官方博客与模型仓库 News 条目；基准分数为厂商自报，除标注外未经第三方复现。

「开源模型」这个说法在 2026 年已经不能当技术判据用了。**open-weight（开放权重）** 与 **open source（开源）** 已经是两件不同的事：前者只给权重，后者还要给训练数据与训练代码。当前能真正称为开源的只有少数（Qwen3.8-27B 的Apache-2.0、GLM-5/5.1/5.2/5.3-Flash 的 MIT、Muse Glimmer 30B 的 Apache-2.0），而参数规模最大的那批模型（Kimi K3、GLM-5.3、Qwen3.8-2.4T）全部是自定义协议或只开权重。

本文覆盖 Llama、GLM、Kimi、MiniMax、Mistral、星火六家国产外阵营。各家单篇细节见 [Qwen](/docs/CS/AI/LLM/Model/Qwen.md) 与 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)，部署侧见 [Inference](/docs/CS/AI/LLM/Model/Inference.md)。

## Current Landscape

| 阵营 | 最新开放权重 | 发布 | 参数 | 上下文 | 许可证 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Meta | ⚠️ **Muse Glimmer 30B**（非 Llama 系） | 2026-08-10 | 约 30B dense（含 1.8B视觉编码器） | 131,072 | **Apache-2.0** |
| Meta（旧） | Llama 4 Maverick / Scout | 2025-04-05 | 400B / 109B 总，17B 激活 | 1M / 10M | Llama 4 Community License |
| 智谱 GLM | ⚠️ **GLM-5.3**（旗舰转协议） | 2026-08-14 | 744B / 40B 激活 | **1M** |⚠️ GLM-5.3 License |
| 智谱 GLM（Flash） | GLM-5.3-Flash | 2026-08-26 | 320B / 18B 激活，多模态 | 未查到 | **MIT** |
| 月之暗面 | **Kimi K3** | 2026-07-16 | **2.8T / 104B 激活** | 1M | ⚠️ Kimi K3 License（只开权重） |
| MiniMax | MiniMax-M2 | 2025-10-26 | 230B / 10B 激活 | 未查到 |⚠️ Modified MIT |
| Mistral | Mistral Medium 3.5 | 2026-04-28 | **128B dense**（非 MoE） | 256K |⚠️ Modified MIT |
| 讯飞星火 | ⚠️ 仅端侧 X2.5-4B / 1.7B | 2026-09-01 | 4B / 1.7B | 1M | 未查到 |

## Meta Llama 4 Is Not the Latest — This Is Most Easily Misunderstood

**截至 2026-10-05，仍未查到 Llama 5。** Llama 4（2025-04-05）仍是 Llama 品牌下的最新权重，这一点用户给的信息正确。但更关键的是：**Llama 4 已经不是 Meta 最新的开放权重模型了。**

2026-08-10，Meta Superintelligence Labs 发布 **Muse Glimmer 30B**，走的是完全不同的路线：

- **许可证是 Apache-2.0**，这是 Meta **第一个**采用标准 OSI 批准许可证的语言模型，摆脱了 Llama Community License 沿用至今的限制
- 约 30B dense（29.6B，含约 1.8B ViT-G/14 视觉编码器），131,072 上下文
- 从闭源的 **Muse Spark**蒸馏而来，定位是本地 agentic 工作流：工具调用、多步任务、失败重试
- 厂商自报 MCP-Atlas 75.5、AIME 2026 94.7、GPQA Diamond 83.5、SWE-Bench Pro 51.2
- 4-bit 量化后语言模型部分 <20 GB，24GB 或 32GB 机器可跑；官方提供全精度权重、两套 GGUF 与 ExecuTorch 打包
- 随附 **DFlash** 投机解码草稿模型，RTX 5090 上从 74.9 tok/s 提到 233.4 tok/s（3.1×，厂商数据）
- 权重挂在 HuggingFace 的 `meta-models` 组织下（不是 `meta-llama`），官方 GGUF 要求 llama.cpp **b10353 或更新**

> ⚠️ **所以「Llama 4 是 Meta 最新模型」这句话在 2026 年已经错了。** 准确说法是：Llama 4 是 Llama 品牌最新，Muse Glimmer 30B 是 Meta 开放权重最新。而且 Llama 4 的 17B 激活 + 400B 总参数意味着最小可用档位就是 400B 级别，**Llama 4 家族里没有能塞进单张消费级显卡的型号**——Llama 4 最小的是 Scout 109B总参。Meta 补上这个空档的方式不是 Llama 5，而是换了品牌的 Muse Glimmer。

## Open Source License: True Rating

这是本篇最有价值的部分。协议决定能不能商用，法务比性能更早成为决策瓶颈。

### Llama 4 Permits Commercial Use

> ⚠️ **「Llama 4 非商用」是常见误传。** Llama 4 Community License Agreement（2025-04-05 生效）**允许商业使用**，是一份自定义的、有条件限制的商用许可。它**不是** OSI 批准的开源许可证，所以准确定级是 **open-weight（开放权重）／source-available，不是 open source**。把它当「非商用」会白白放弃一个可商用的选项；把它当「开源」则会在合规审查上被否。

四类实质限制，按实际踩坑频率排序：

1. **月活 7 亿门槛（Section 2）**：在某个 Llama 4 版本发布日，若被许可方**或其关联方**的产品与服务在此前一个自然月的月活超过 **7 亿**，须另行向 Meta 申请授权，且 Meta 可自行决定是否授予。在获授权前不得行使本协议下的任何权利。**注意这条约束的是整个法律实体（含子公司）**，集团口径的 MAU 计算容易踩线。
2. **欧盟境内多模态限制**：这条**不在 License 正文里，而在 Acceptable Use Policy 末段**。原文：多模态模型部分，Llama 4 Community License Agreement 第 1(a) 条授予的权利，**不授予给个人住所位于欧盟、或主要营业地在欧盟的公司**。同时原文明确「This restriction does not apply to end users of a product or service that incorporates any such multimodal models」。所以：**限制对象是被许可方，不是下游用户**；且**只针对多模态能力，纯文本不受此限**。中国公司在欧盟设实体做产品要用 Llama 4 视觉能力，会踩到这条。
3. **署名与命名（Section 1.b.i）**：分发或提供 Llama 4 材料、衍生作品，或含其输出的产品/服务时，须(a) 附上协议副本、(b) 在相关网站、UI、博客、关于页或产品文档中**显著展示 "Built with Llama"**。若用 Llama 4 材料或其输出创建、训练、微调或改进一个对外分发的 AI 模型，**该模型名必须以 "Llama" 开头**。另须在 Notice 文件中保留 Meta 的著作权声明。
4. **不得用 Llama 4 输出训练与 Meta 竞争的基座模型**：AUP 与品牌条款共同约束这一点。**这不是 Llama 4 才有的条款**，从 Llama 2 时代就在，被认为主要针对 Meta 的最大竞争对手。

> ⚠️ **OSI 早在 2025-02-18 就对 Llama 4 下了判定**（Llama 4 发布前），公开表态「Llama 4 is still not #opensource and Europeans are excluded. Stop calling it Open Source AI.」，并指出 Llama 违反自由 0（任何用途均可使用）、OSD 第 5 条（不得歧视特定领域使用者）与第 6 条（不得对使用者施加限制）。OSI 社区负责人 Nick Vidal 进一步明确「openness is binary」——带限制就不是开源，不存在「更open」的程度问题。Meta 的回应是不接受这套定义（"There is no single open source AI definition"），并在官方公告里把 Llama 4 谨慎地称作 open-weight，但 Zuckerberg 在 Instagram 帖子里仍称其为 open source。**引用时建议用 OSI 与许可证原文，不要引 Meta 的宣传话术。**

### GLM-5.3 Is a Protocol Fork, Not Overall Degradation

智谱在这一家上出现了**同一系列两种许可证**的情况，ModelScope 实测字段：

| 型号 | 上线 | 参数量 | 许可证 |
| :--- | :--- | :--- | :--- |
| GLM-5.3 | 2026-08-27 | 744B / 40B 激活 | ⚠️ `other`（GLM-5.3 License） |
| GLM-5.3-Flash | 2026-08-26 | 320B / 18B 激活，多模态 | **MIT** |
| GLM-5.2 | 2026-06-16 | 744B / 40B 激活 | **MIT** |
| GLM-5.1 | 2026-04-04 | 744B / 40B 激活 | **MIT** |
| GLM-4.7 | 2025-12-22 | — | **MIT** |

> ⚠️ **旗舰转协议，但中小型号仍是 MIT。** 上一代 GLM-5（2026-02-11）用的是 MIT，旗舰 GLM-5.3 换成了自定义 **GLM-5.3 License**。条款本身比 Qwen 宽松得多：只有一条约束——被许可方**或其关联方**运营 MaaS 业务且连续 12 个月累计收入超过 **100 亿美元**，须在商业使用前通过 **Z.AI 的安全审查**（范围与方式由 Z.AI 合理确定）。**没有营收署名条款，没有 UI 展示要求。** 也就是说 100 亿美元以下（含绝大多数企业）与内部部署都仍是自由商用。许可证是中英双语正文，联系邮箱 `glmlicense@z.ai`。

**一个容易忽略的技术事实：GLM-5.3 与 GLM-5.2 共用同一个基座模型**，模型卡原文「GLM-5.3 uses the same base model as GLM-5.2 — every gain comes from post-training」。GLM-5.3 的提升全部来自后训练：官方称在自研 Z.ai Code Bench 上比 GLM-5.2 提升 50%，并在 Terminal Bench 3.0（28.3 对 4.6）与 Agents' Last Exam 上取得开源 SOTA。**这意味着想省事可以直接拿 GLM-5.2**，能力差距主要在 agentic 与代码后训练上。

GLM-5.3 的 `max_position_embeddings` 是 **1048576（1M 原生）**，而 GLM-5 是 202752（约 200K）——上下文从 5 代到 5.3 有五倍跳跃，写长文档方案时要注意这个代差。

### Kimi K3 Opens Weights Only

> ⚠️ **「全球首个开放 3T 级模型」的准确含义是：首个开放 3T 级权重，不是首个开源 3T 级模型。** Kimi K3 协议全名 **Kimi K3 License**，但**只开权重，不开训练数据，训练代码也不完整**——GitHub `MoonshotAI/Kimi-K3` 仓库只有四个文件：`LICENSE`、`README.md`、`assets/`、`k3_tech_report.pdf`。没有训练脚本、没有数据管线。许可证正文把「inference and training code」写进了 Software 的定义里，但仓库里并没有提供可用的训练代码。**所以准确定级是 open-weight，不是 open source。**

Kimi K3 License 的实质约束有两条，比 Qwen 与 GLM 都更严：

- **MaaS 营收门槛 2000 万美元**：被许可方及其关联方运营 MaaS 业务且连续 12 个月累计收入超过 **2000 万美元**，须与 Moonshot AI 签订单独协议后才能商业使用。**这个门槛是四家里最低的**，比 Qwen3.8 的 5000 万、GLM-5.3 的 100 亿低得多。
- **署名条款**：商业产品/服务月活超 **1 亿**或月收入超 **2000 万美元**，须在 UI 显著展示 "Kimi K3"（Qwen 是 2000 万月收入、1 亿月活，数值相同但模型名不同）。
- **豁免**：内部使用（不向第三方提供软件、输出或底层能力）不适用以上两条；通过 Moonshot AI 官方产品或认证推理伙伴访问的也不适用。

参数量上Kimi K3 是当前最大的开放权重模型：2.8T 总 / 104B 激活，93 层，896 个专家选 16（另有 2 个共享专家），1M 上下文，**原生 MXFP4 权重 + MXFP8 激活（量化感知训练）**，视觉编码器 MoonViT-V2（401M）。注意力结构是 **69层 KDA（Kimi Delta Attention）+ 24 层 Gated MLA** 混排，1 层 dense。官方称 2.8T / 104B 这个激活比例相比 K2 带来约 2.5× 的整体扩展效率提升。模型卡措辞是 "open-weight, native multimodal agentic model" 与 "world's first open 3T-class model"。

**MXFP4 值得单独注意**：这是首个把微缩放浮点量化（MXFP4）作为**出厂默认格式**发布的前沿模型，意味着不需要自己量化，权重拿下来就是4-bit 分辨率。

前代谱系：K2.5（2026-01）→ K2.6（2026-04）→ K2.7 Code（2026-06）均为 1T 总 / 32B 激活、Modified MIT。另有一条独立的长上下文效率路线 **Kimi Linear**（48B-A3B，Kimi Delta Attention，1M 上下文）。

### MiniMax-M2 Is Modified MIT, Not Apache-2.0

> ⚠️ **MiniMax-M2 不是 Apache-2.0。** ModelScope 的 `license` 字段是 `other`，`license_name: modified-mit`，实际许可证文件是 MIT 的一个修改版，正文里写明「Our only modification is that...」：若用于月活超**1 亿**或年度经常性收入超 **3000 万美元**的商业产品或服务，须在该产品界面显著展示 "MiniMax M2"。除此之外与 MIT 完全一致。

参数：230B 总 / 10B 激活 MoE，2025-10-26 上线。10B 激活的定位是端到端工具使用与 agentic 任务。**未查到 M3 的官方发布**。

### Mistral Merged Three Product Lines

Mistral Medium 3.5（2026-04-28 发布，权重 04-29，05-22 GA）最值得记的不是参数而是产品策略：**它把三条产品线合并成单权重**——退役 Mistral Medium 3.1（通用）、Magistral（推理）、Devstral 2（编码），统一为一个权重 + 逐请求 `reasoning_effort` 参数（`none` 走快答，`high` 走长思维链）。从「三个 checkpoint 常驻」变成「一个 checkpoint + 一个参数」。

规格上有个反直觉点：**128B dense，不是 MoE**。256K 上下文，视觉编码器从头训练（原生支持可变图像尺寸与宽高比），厂商自报 SWE-Bench Verified 77.6%、τ³-Telecom 91.4%、BrowseComp 48.6。许可证同样是 **Modified MIT**（含大营收企业的营收条款），不是干净的 Apache-2.0。API 定价 $1.50 输入 / $7.50 输出（每百万 token）。

本地部署的算术要提前算：128B dense 在 Q4_K_M 下约 72 GB 磁盘占用加 KV cache，实际门槛是 4×24GB 或 96GB+ 统一内存。**单卡 24–32GB 机器直接跳过这个型号。**

## iFlytek Spark Opens Source Only the On-Device Side

> ⚠️ **星火 293B 基座没有开源。** 讯飞星火 X2.5 于 2026-09-07 发布，293B-A30B MoE、256K 上下文，但**只在开放平台上线，未开放基座权重**。开源的只有两个端侧小模型：**星火 X2.5-4B 与 X2.5-1.7B（2026-09-01 开源，1M 上下文）**。

所以星火在这份清单里是特殊的一类：**它的开源部分是端侧模型，云端旗舰不开源**，与其他家「开放旗舰权重」的模式相反。

它的价值另在别处——**全流程全国产算力训练与推理**的代表。官方表述是「基于全国产算力完成全流程训练及推理」，且端侧模型同时支持英伟达、华为、海光、后摩。科大讯飞 2019 年已被列入美国商务部实体清单，这个国产化定位有明确的合规动因。选型时要看清：如果你的需求是本地端侧小模型，星火 4B/1.7B 值得看；如果要 293B 旗舰，只能走 API。

## Architecture Convergence: Signals in 2026

抛开各家宣传，2026 年最实质的技术变化是**多路独立收敛到同一个架构组合：混合线性注意力 + MoE**。四家各自的命名不同，但解决的是同一个问题——全注意力在长上下文上的计算与 KV cache 成本：

| 家族 | 线性/稀疏注意力 | MoE 配置 |
| :--- | :--- | :--- |
| Kimi K3 | KDA（Kimi Delta Attention）+ Gated MLA，69:24 混排 | 896 专家选 16，2.8T/104B |
| Qwen3.5/3.8 | Gated DeltaNet + Gated Attention，3:1 混排 | 512 专家选 10+1，2.4T/95B |
| GLM-5/5.2/5.3 | DeepSeek Sparse Attention（DSA） | 256 专家选 8，744B/40B |
| GLM-5.3-Flash | 线性 + 稀疏混合（`glm5_next`） | 320B/18B |

这个收敛意味着**过去两年「谁用 MLA / 谁用 DSA / 谁用线性注意力」的路线之争基本结束了**，现在的问题是「混合比例调多少、每多少层插一次全注意力」。对做推理部署的人，直接影响是：KV cache 的形状和计算模式在各家趋同，量化与缓存优化的通用方案更容易跨模型复用。DeepSeek 那篇的 V4.1-Flash 用的 causal encoder–decoder 是另一条独立路线，见 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)。

## Selection Quick Reference

按约束条件选，而不是按榜单选：

- **要Apache-2.0 且要多模态** → `Qwen3.8-27B`（27B dense，256K 可扩1M）。这是目前最省事的一档。
- **要 MIT 且要多模态** → `GLM-5.3-Flash`（320B/18B，MIT）
- **要单卡消费级显卡跑 agent** → `Muse Glimmer 30B`（Apache-2.0，30B，24GB 起步，附 DFlash 草稿模型）
- **要最大开放权重、且营收低于 2000 万美元** → `Kimi K3`（2.8T，1M，MXFP4 出厂）。过了这条线要谈单独协议。
- **要一个权重同时做对话/推理/编码** → `Mistral Medium 3.5`（128B dense）。但要 4 卡或 96GB 统一内存。
- **只做内部部署、不对外提供服务** → Qwen 与 GLM 的营收门槛都不触发，随便选。
- **必须国产算力 + 端侧小模型** → 星火 X2.5-4B / 1.7B
- **不要选**：235B-A22B（上一代，已被同代更小型号超越）、Qwen 480B（查不到此规格）、Llama 4（最小109B 总参，单卡跑不了，且欧盟实体用不了多模态）

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)
- [OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)
- [Claude](/docs/CS/AI/LLM/Model/Claude.md)
- [Transformer](/docs/CS/AI/Transformer.md)

## References

- [Llama 4 Community License Agreement（官方全文）](https://www.llama.com/llama4/license/)
- [Llama 4 Acceptable Use Policy（欧盟多模态条款在此）](https://www.llama.com/llama4/use-policy/)
- [llama4 MODEL_CARD.md（Scout / Maverick 参数与许可）](https://github.com/meta-llama/llama-models/blob/main/models/llama4/MODEL_CARD.md)
- [Introducing Muse Glimmer（Meta 官方博客，Apache-2.0）](https://research.meta.ai/blog/introducing-muse-glimmer-open-agentic-model)
- [GLM-5 技术博客（744B/40B、28.5T tokens）](https://z.ai/blog/glm-5)
- [GLM-5.3 模型卡（与 5.2 共用基座）](https://modelscope.cn/models/ZhipuAI/GLM-5.3)
- [GLM-5.3 License（ModelScope 仓库内 LICENSE）](https://modelscope.cn/models/ZhipuAI/GLM-5.3)
- [Kimi K3 模型卡（2.8T/104B、KDA、MXFP4）](https://modelscope.cn/models/moonshotai/Kimi-K3)
- [MoonshotAI/Kimi-K3 仓库（仅四个文件）](https://github.com/MoonshotAI/Kimi-K3)
- [MiniMax-M2 LICENSE（Modified MIT 条款原文）](https://github.com/MiniMax-AI/MiniMax-M2/blob/main/LICENSE)
- [Mistral Medium 3.5 模型卡](https://huggingface.co/mistralai/Mistral-Medium-3.5-128B)
- [科大讯飞星火 X2.5 发布（293B-A30B 与端侧开源）](https://ah.people.com.cn/BIG5/n2/2026/0907/c227767-41689210.html)
