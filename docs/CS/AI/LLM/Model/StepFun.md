## Introduction

> **版本基线：2026-10-16 核实。** API 型号与价格以 [StepFun 开放平台定价页](https://platform.stepfun.com/docs/zh/guides/pricing/details) 为准；架构与训练细节以 2026-10-15 随权重发布的技术博客《Inside Step 5 Preview: Architecture and Training for Agentic Work》与 [HuggingFace 模型卡](https://huggingface.co/stepfun-ai/Step-5-Preview) 为准；基准分数除标注外均为厂商自报，未经独立复现。

[StepFun（阶跃星辰）](https://platform.stepfun.com) 是上海的大模型公司，2026-09-20 发布旗舰基模 **Step 5 Preview**，2026-10-15 按发布时承诺的日期开放权重。这个型号在国产模型里的位置很特殊：**它是第一个把「长程 Agent 任务」当作第一设计目标、而不是事后补丁的前沿权重**——架构、训练与产品三条线都围绕「调用工具、长上下文、持续推进到交付结果」展开，金融是官方点名的重点验证场景。

本文只记 StepFun 的模型、权重与 API 事实。

## Specifications

| 规格 | Step 5 Preview |
| :--- | :--- |
| 模型 ID | `step-5-preview` |
| 架构 | 稀疏 MoE，600B 总参数 / 27B 每 token 激活 |
| 层数 | 92 层 Transformer（窄而深） |
| 上下文窗口 | 1M tokens（上一代 Step 3.5 为 256K） |
| 最大输入 | 1M tokens |
| 最大输出 | ⚠️ 官方文档页写 **64K**，HuggingFace 模型卡写 **最高 1M**——以平台文档为准，模型卡数字是权重侧上限 |
| 输入模态 | 文本、图片、视频 |
| 输出模态 | 文本 |
| 生成速度 | 约 100 tokens/s（厂商数据） |

功能面：流式输出、工具调用、结构化输出（JSON Mode 与 JSON Schema）、提示缓存都支持；**推理强度可调** `low` / `medium` / `high`——Chat Completions API 用 `reasoning_effort` 参数，Messages API 用 `output_config.effort`；`max_tokens` 默认 `INF` 不设限，由模型自行决定。多模态输入的限制：图片支持 URL 或 Base64，JPG/JPEG、PNG、WebP、静态 GIF，单次最多 60 张，细节级别 `low` / `high`；视频支持 URL、Base64 或 Files API 的 `stepfile://` 引用，MP4、QuickTime、Matroska，单个文件小于 128MB、时长建议小于 5 分钟。

## Architecture: Narrow But Deep

Step 5 Preview 的架构选择全部指向同一个场景：**Agent 干活时，大量时间花在处理工具返回的上下文上，模型没有机会一步步写出推理过程，Prefill 阶段的隐式多跳推理能力因此比生成阶段更关键**。围绕这一点的设计有四层。

**第一层是「窄而深」的 92 层堆叠。** 业界主流是靠加宽提升容量，StepFun 选择把 Transformer 深度加到 92 层——深度为长 Prefill 中的信息传播提供更长路径，支撑链式任务里的隐式多跳推理，相对较窄的布局则控制计算成本。代价是更难训：92 层网络会撞上数值爆炸与梯度尖峰，StepFun 的解法是把关键状态与参数保持在 FP32 精度，并做细粒度梯度裁剪来压制激活增长。

**第二层是多层面稀疏：Sparse MoE ++ Sparse GQA。** 除 MoE 本身的专家稀疏激活（600B 总 / 27B 激活）外，注意力侧引入 Sparse GQA——处理百万 token 上下文时，通过稀疏索引只让相关的历史信息进入注意力计算，不让每个 token 与所有 token 交互。索引按 8 token 的块进行。

**第三层是把算法稀疏落到系统效率。** 稀疏计算对 GPU 的索引与数据搬运模式要求不同，理论节省容易被工程细节吃掉。StepFun 的做法是 Block-wise Token Merging：把相邻的、Top-k 结果高度重叠的 token 合并，将 Indexer 与 Top-k Selection 的成本降到约 1/8，同时缓解碎片化计算对 GPU 利用率的影响。

**第四层是训推一致性与长轨迹 RL。** MoE 动态选专家，细微数值差异会让路由偏移并在 92 层网络里累积，导致训练好的策略推理时失效。StepFun 在严格在线策略训练中实现训练与推理的 **bit-wise 对齐**：用确定性算子统一两侧实现，树状归约消除张量并行度的影响，端到端开销增加低于 10%，异步训练中 logprob 偏差控制在 1e-2 以内。长程 RL 还叠加了 load-aware scheduling、**MTP-3 投机解码**、FP8 MoE 与 KV-cache offload，官方称长程 RL 端到端加速超过 3 倍、sample-ledger 损失低于 1%。

> ✅ **Context Compaction 是这款模型最特别的一课：上下文压缩不是外挂规则，而是训进策略里的。** 上下文快用满时，Agent 自己把手头工作状态整理成可接续的摘要再继续，而不是被动被窗口截断——这个能力与任务奖励一起端到端训练出来，官方援引 Rich Sutton《The Bitter Lesson》解释这个选择：让模型学会管理上下文，而不是人写规则裁剪。RL 侧还有反作弊设计：模型想利用任务或评测漏洞走捷径时，系统当场拦住该步骤并扣分、提示换路，而不是判整条轨迹失败。

数据生产体系同样面向 Agent：Agent 不只生成样本，还参与知识探索、任务设计、难度与多样性控制与流程动态编排，专家提供原则与关键判断，确定性操作交给代码与工具，并配 Anti-hacking 检查——最终构建出**百万级、可验证的高难任务环境**，覆盖科学推理、软件工程、机器学习研发与专业知识工作。

## Benchmarks

以下为 StepFun 官方对比图数据（除标注外），横列为同场对比的开源旗舰：

| 基准 | Step 5 Preview | Kimi K3 | GLM-5.3 | Claude Opus 5 | GPT-6 Astra |
| :--- | ---: | ---: | ---: | ---: | ---: |
| DeepSWE v1.1（%） | **67.7** | 67.5 | 66.9 | 74.0 | 74.1 |
| ProgramBench | **80.5** | 77.8 | 72.0 | — | — |
| Terminal-Bench v4 | 33.3 | — | **41.9** | 52.3 | 57.9 |
| GDPval-AA v2.1 | 1566 | — | **1645** | — | — |

其他关键数字：

- **Artificial Analysis 综合智能指数 44 分**，位居全球开源模型前三；AA 测算其完成单项智能指数任务成本约 $0.71，官方称同智能水平下单任务成本约为 Claude Opus 5 的**八分之一**
- **DeepSWE v1.1 67.7%**：仅次于 GPT-6 Astra 与 Claude Opus 5 两个闭源旗舰，领先全部开源模型
- **Terminal-Bench 4.0 33.3%**：这是它的相对弱项，落后 GLM-5.3 约 8.6 个点
- **FrontierFinance 66.4**（220 道专业金融问题、11,543 项评估标准、六类投资场景）：全球第二，领先 GPT-6 Astra 及其他参评开源模型
- 内部 **StepCodeBench**（553 个代码仓库、9 类任务、20 个应用领域、33 种编程语言）avg@4 49.0%；约 70% 的内外部评测专家认为它可自主完成中高复杂度编程任务
- 长程执行标本：单张 NVIDIA H100 上 24 小时从零优化 MLA GPU Kernel，约 22 小时达到前向 + 反向合计 508 TFLOPS；另一次实验用自动化后训练把 Qwen3-30B-A3B 的 AIME24 准确率从 53.3% 提到 60%
- 金融内部评测 FinStepBench 系列（LiveSearch / CorporateValuation / DeepResearch）考察实时信息检索核验、数据与假设到可复现估值的转化、完整研究报告产出

官方对短板的表述也值得记录：中低难度编程任务接近 Claude Opus 5，但**最具挑战、运行时间更长的任务上「仍有进一步提升空间」**。

## Pricing

国内开放平台按人民币计价（元／百万 tokens）：

| 模型 | 输入（缓存未命中） | 输入（缓存命中） | 输出 |
| :--- | ---: | ---: | ---: |
| `step-5-preview` | 7 | **0.70** | 20 |
| `step-3.7-flash` | 1.35 | 0.27 | 8.1 |
| `step-3.5-flash` | 0.7 | 0.14 | 2.1 |
| `step-1o-turbo-vision` | 2.5 | 0.5 | 8 |

海外渠道（OpenRouter 等）为美元计价：**输入 $1.00 / 输出 $2.70，缓存读取 $0.05**，约合人民币价的汇率等价。

> ⚠️ **缓存命中价在 2026-10-14 00:30（北京时间）翻倍：0.35 → 0.70 元／百万 tokens。** 且这次调价**只对首次调用发生在调价前的用户保留旧价**，Step Plan 订阅渠道的缓存价不在调整范围内。按 10-14 之前流传的 0.35 元估成本会低估一半；对 Agent 循环这种高缓存命中负载（OpenCode 数据显示 Step 5 Preview 输入 token 约 96% 命中缓存），这一项的影响被进一步放大。

增值能力单独计费：互联网搜索 0.04 元/次、文搜图 0.12 元/次、文件存储 0.5 元/GB/天。阿里云百炼渠道的限流为 RPM 500、TPM 10,000,000（该数字是百炼平台口径，非 StepFun 直连口径）。

## Open Weights and License

StepFun 在 09-20 发布时即承诺 10-15 开源，**2026-10-15 按期释放权重**，没有跳票。发布物包括：

- **三个精度的 checkpoint**：主仓库 `stepfun-ai/Step-5-Preview`（FP8，24 个权重分片 + MTP 与视觉文件）、`stepfun-ai/Step-5-Preview-BF16`、`stepfun-ai/Step-5-Preview-NVFP4`（面向 Blackwell），全部公开无门禁；ModelScope 同步镜像
- 技术博客《Inside Step 5 Preview: Architecture and Training for Agentic Work》与配套开源开发工具、部署指南
- 体量参考：FP8 约 650 GB，BF16 约 1.2 TB（safetensors 索引计数 604.3B）——**这是数据中心级模型，不是桌面玩具**

> ℹ️ 一个有意思的细节：权重释放前，Artificial Analysis 模型页仍将 Step 5 Preview 标注为 **Proprietary（闭源）**——「API 可调用」与「开放权重」在 AA 那里是两件事，10-15 之后它才进入开源模型口径的排名。

### StepFun Model License 1.0

许可证自称 "Apache-2.0-style"，永久、免版税的使用 / 修改 / 再分发 + 专利授权，但有三条 Apache-2.0 没有的商业门槛：

1. **署名条款**：商业产品或服务月活超 **1 亿**或月收入超 **2000 万美元**，须显著展示 "Powered by StepFun AI"
2. **单独商业授权**：两类主体须先取得 StepFun 单独授权——① 把模型能力装进手机、汽车、智能眼镜、可穿戴、机器人、智能家居设备的**硬件厂商**；② 年收入超 **2000 万美元**的 **MaaS 提供商**
3. **衍生作品口径宽**：「用 Step 5 输出在实质程度上训练的模型」被认定为复现或包含模型的实质部分，即衍生作品

**内部使用豁免第 2 条。** 自建自用不触发硬件与 MaaS 门槛；会触发的是对外提供搭载模型的产品或大规模 MaaS 服务。这个结构与 Qwen / GLM / Kimi 的营收门槛同族，但多出了硬件厂商这一格——做端侧落地的不二权重。

### Deployment

官方部署表（数据来自模型卡）：

| 框架 | 精度 | 硬件 | 并行 | 接口 |
| :--- | :--- | :--- | :--- | :--- |
| vLLM | FP8 | 1 节点 4× B300 或 8× H200 | TP4/TP8、TEP4/TEP8 或 DEP4/DEP8 | OpenAI 兼容 API |
| vLLM | BF16 | 1 节点 8× B300 或 2 节点 16× H200 | TP8/TP16、TEP8/TEP16 或 DEP8/DEP16 | OpenAI 兼容 API |
| SGLang | FP8 | 1 节点 4× B300 或 8× H200 | TP4/EP4、TP8/EP8 | OpenAI 兼容 API |
| Transformers | FP8 | 1 节点 8× H200 | TP8/EP8 | 离线生成 |
| Transformers | BF16 | 2 节点 16× H200 | TP16/EP16 | 离线生成（BF16 分片流程官方尚未端到端验证） |

vLLM 有专用镜像 `vllm/vllm-openai:step-5-preview`。官方推荐采样参数 `temperature=1.0`、`top_p=0.95`、`top_k=0`；需要框架构建包含 Step 5 Preview 支持（推理、工具调用、投机解码）。

## Platform and Product Lineup

StepFun 开放平台是「一套密钥全覆盖」的模型即服务结构，文本／语音／图像模型共用 `https://api.stepfun.com/v1`（OpenAI 兼容）与 Messages API 两套接口：

- **文本线**：旗舰 `step-5-preview`，往下是 `step-3.7-flash` 与 `step-3.5-flash`（含 2603 快照版）两个经济档，加 `step-1o-turbo-vision` 视觉型号
- **语音线（StepAudio 3）**：ASR（`stepaudio-3-asr-max` 2.8 元/小时）、实时交互（Realtime）、语音生成（TTS 2.5 元/万字符）、音乐生成（Gen/Music）四类，realtime 与 gen/music 的 preview 版限时免费
- **订阅线 Step Plan**：按月订阅，内置多模型智能路由，适配主流 agent 框架，并支持 **Claude Code 接入**（配置 Step Plan 并开启 1M 上下文）
- **分发渠道**：国内开放平台、海外开放平台（platform.stepfun.ai）、Studio 在线体验、OpenRouter、阿里云百炼；WorkBuddy 于 2026-10-12 接入并提供 10-12 至 10-25 的限时免费体验

> ✅ **OpenRouter  token 用量周榜与日榜全球第二**（2026-10-15 数据）——开源发布三天即到的位置，说明需求侧早就就位，缺的只是权重许可。

## Horizontal Positioning

把 Step 5 Preview 放进国产开源旗舰的格子裡，它的差异不在单项跑分，而在三处结构性选择：

- **为 Agent 而非聊天设计**：92 层窄深、Sparse GQA、Context Compaction、反作弊 RL，全部服务「长任务链 + 长上下文 + 工具调用」这一个负载形态。同场对比里 Kimi K3 与 GLM-5.3 的强项更偏通用对话与终端基准，Step 5 Preview 的 DeepSWE 67.7 与 ProgramBench 80.5 正是 agentic 编码的直接度量。
- **金融是官方点名的第一垂直**：FrontierFinance 66.4 全球第二（开源第一），并配了三个内部基准。金融任务同时压测长任务链、长上下文与工具调用，官方把它当作超长任务的试金石——这一定位与 DeepSeek 的「最便宜」、GLM 的「国产算力」形成错位。
- **激活比 27B/600B 的效率路线**：与 DeepSeek V4.1-Flash 的不对称 encoder–decoder（8B 读 / 16B 写）是两种不同的省钱哲学——一个压激活总量，一个压输入侧路径。AA 的单任务成本 $0.71 与「Opus 5 的 1/8」是这条路线的成绩单。

架构上它代表了 2026 年长上下文收敛的**另一支**：Kimi K3（KDA）、Qwen3.8（Gated DeltaNet）、GLM-5（DSA）走混合线性注意力，Step 5 Preview 走**块索引稀疏注意力**（Sparse GQA + Block-wise Token Merging）——同为「不让每个 token 看所有 token」，一个改注意力形式，一个改索引方式。两条路线都让 1M 上下文的成本进入可部署区间，横向对比见 [开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)。

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)
- [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)
- [Qwen](/docs/CS/AI/LLM/Model/Qwen.md)
- [本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)

## References

- [Step 5 Preview 模型页（官方文档）](https://platform.stepfun.com/docs/zh/guides/models/step-5-preview)
- [StepFun API 定价（官方）](https://platform.stepfun.com/docs/zh/guides/pricing/details)
- [Step 5 Preview HuggingFace 模型卡](https://huggingface.co/stepfun-ai/Step-5-Preview)
- [Inside Step 5 Preview: Architecture and Training for Agentic Work（官方技术博客）](https://stepfun.ai/blog/inside-step-5-preview)
- [StepFun opens Step 5 Preview's weights（ArtificialWatch，许可证与跑分细节）](https://artificialwatch.com/wire/stepfun-step-5-preview-open-weights)
- [阶跃星辰发布 Step 5 Preview（人民网，AA 指数与成本对比）](https://sh.people.com.cn/n2/2026/0921/c138654-41703001.html)
