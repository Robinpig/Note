## Introduction

> **版本基线：2026-10-05 核实。** 版本时间线以 [Qwen3.8 仓库 News](https://github.com/QwenLM/Qwen3.8) 为准；参数量、上下文、架构与许可证以 ModelScope 上各模型的 `config.json` 与 `LICENSE` 原文为准；基准分数为厂商自报，未做第三方复现。

[通义千问（Qwen）](https://qwen.ai) 是阿里通义团队的模型系列，也是全球下载量最大的开源权重模型家族。它的开源策略与其他厂商有一个结构性差别：**同一个代次内，不同规格型号可能挂着不同许可证**。2026 年这个差别第一次大到会直接影响选型——`Qwen3.8-27B` 是 Apache-2.0，而 `Qwen3.8-2.4T-A95B` 是自定义协议。

本文只记Qwen 模型与权重事实。API 与云服务侧的通义见[阿里云百炼](/docs/CS/AI/LLM/Platform/)，开源阵营的横向对比见 [Open Model](/docs/CS/AI/LLM/Model/Open_Model.md)。

## Current Version Baseline

最新代次是 **Qwen3.8**，不是 Qwen3.5。Qwen3.5 → Qwen3.6 → Qwen3.8 三代共用同一个仓库 `QwenLM/Qwen3.8`（截至核实日4231 stars，最后推送 2026-08-17，仓库 license 字段 `Apache-2.0`），仓库内按代次分节记录各型号。

| 型号 | 权重上线 | 形态 | 参数 | 上下文 | 许可证 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Qwen3.8-2.4T-A95B` | 2026-08-12 | MoE，纯文本 | 2.4T 总 / 95B 激活 | 262,144 原生，YaRN 可扩至 1,010,000 | ⚠️ Qwen3.8-Max License |
| `Qwen3.8-27B` | 2026-08-14 | Dense，原生多模态 | 27B | 262,144 原生，YaRN 可扩至 1,000,000 | Apache-2.0 |
| `Qwen3.8-Flash-Next` | 2026-08-26 | MoE，多模态 | 125B 主模型 + 51B N-gram embedding / 6B 激活 | 未查到官方数字 | ⚠️ 自定义（`license: other`） |
| `Qwen3.6-35B-A3B` | 2026-04-16 | MoE，多模态 | 35B / 3B 激活 | 262,144 原生 | Apache-2.0 |
| `Qwen3.6-27B` | 2026-04-22 | Dense，多模态 | 27B | 未单独查到 | Apache-2.0 |
| `Qwen3.5-397B-A17B` | 2026-02-16 | MoE，多模态 | 397B / 17B 激活 | 未单独查到 | Apache-2.0 |
| `Qwen3.5-122B-A10B` / `35B-A3B` / `27B` | 2026-02-24 | MoE / Dense | 122B、35B、27B | 262,144（35B-A3B） | Apache-2.0 |
| `Qwen3.5-9B` / `4B` / `2B` / `0.8B` | 2026-03-02 | Dense | 小尺寸系列 | 未查到 | Apache-2.0 |

> ⚠️ **网上流传的「Qwen3.5 是最新」和「Qwen 有 480B」都过时了。** 截至 2026-10-05，最新是 Qwen3.8；ModelScope 与 HuggingFace 上**均未查到任何 480B 规格的 Qwen 模型**，这个数字在流传的资料里没有对应权重。Qwen3.8-Max（托管版，2.4T）不是开放权重型号，它是在 `Qwen3.8-2.4T-A95B` 基础上加了视觉输入、non-thinking 支持与默认 1M 上下文的官方版本。

> ⚠️ **`Qwen3-235B-A22B`（2025-04-28）已是上一代。** 它属于 Qwen3 代际，官方在 Qwen3.5-397B-A17B 的博客里明确给出解码吞吐对比（32k/256k 上下文下为 3.5 倍／7.2 倍），MMLU-Pro 76.01 对 67.7。实际选型中它已被同代甚至更小的新型号取代：Qwen3.5-35B-A3B 在 MMLU-Pro（86.1 对 80.8）、GPQA Diamond（85.5 对 80.1）、LiveCodeBench v6（80.7 对 82.7，少数例外）等多数基准上超过它。**新项目不要从 235B 起步。**

## Open Source License Apache-2.0 and Its Pitfalls

这是 Qwen3.8 最需要注意的一处。同一代次内两种许可证并存，ModelScope API 实测字段如下：

- `Qwen/Qwen3.8-27B` → `license: apache-2.0`
- `Qwen/Qwen3.8-2.4T-A95B` → `license: other`，`license_name: qwen3.8-max`，`license_link: LICENSE`

`Qwen3.8-2.4T-A95B` 挂的协议全名是 **Qwen3.8-Max License**（注意与托管版产品名 Qwen3.8-Max 同名，但这是权重仓库里的许可证文件）。原文只有两条实质约束：

1. **署名条款**：若用它做商业产品或服务，且该产品**月活超过 1 亿**或**月收入超过 2000 万美元**，须在该产品界面上显著展示模型名。
2. **MaaS 特别授权**：若被许可方**及其关联方**运营 Model-as-a-Service 或 AI Work Assistant 业务，且连续 12 个月累计收入**超过 5000 万美元**，须在商业使用前另行向 Qwen 取得授权。协议把「AI Work Assistant」定义为面向 AI 辅助编码或办公效率的独立 AI 产品（举例 Qoder、QwenWork），并明确排除单一用途工具（AI 翻译）与非编码／办公域的助手。

> ✅ **内部部署不触发这两条门槛。** 许可证原文第 2 条末句明确写了内部使用（internal Use）不适用该要求，前提是不得把软件、其输出或底层模型能力提供给第三方。所以自建服务只给自己人用、或纯内部研究，即使营收很高也不需要单独授权——**会触发门槛的是对外提供 MaaS 或做带模型的商业产品**。

这条协议属于「宽松但有条件」的开放权重（open-weight），不是 OSI 定义的开源：它没有附带训练数据与训练代码，且附加了规模与营收条件。商用前法务需要按自身营收与产品形态对号入座，不能沿用「Apache-2.0 所以随便用」的直觉。

## Architecture: Gated DeltaNet Hybrid Attention

Qwen3.5 引入并被Qwen3.5 全系、Qwen3.6、Qwen3.8 沿用的架构是 **Gated DeltaNet + Gated Attention 混合注意力**配稀疏 MoE。`config.json` 里能直接读出它的层布局规律——每4 层里 3 层用线性注意力、1 层用全注意力，`full_attention_interval: 4` 就是这个配比。

| 维度 | `Qwen3.8-27B` | `Qwen3.8-2.4T-A95B` |
| :--- | :--- | :--- |
| 架构标记 | `qwen3_5`（带vision encoder） | `qwen3_5_moe_text` |
| 层数 | 64 | 92 |
| 隐藏维度 | 5120 | 8192 |
| 线性注意力头| 48（V）/ 16（QK） | 128（V）/ 16（QK） |
| 全注意力头 | 24（Q）/ 4（KV） | 64（Q）/ 4（KV） |
| 专家数 | —（Dense，无 MoE） | 512 |
| 每 token 激活专家 | — | 10 Routed + 1 Shared |
| 词表 | 248,320 | 248,320 |
| 视觉编码器 | MoonViT 风格 ViT，约 27 层、hidden 1152 | 无 |

几个从配置直接读出的结论：

- **多模态在Dense 侧**。`Qwen3.8-27B` 的 `config.json` 顶层含 `image_token_id`、`video_token_id`、`vision_start/end_token_id` 与独立 `vision_config`，是真正的原生视觉语言模型；而2.4T-A95B 的架构是 `Qwen3_5MoeForCausalLM`、config 里**没有** `vision_config`，是纯文本权重。**要本地跑多模态，27B 才是那个带视觉的型号**，别因为它参数少就当成低配版。
- **MTP（Multi-Token Prediction）已随权重发布**。两个模型的 config 都有 `mtp_num_hidden_layers: 1`、模型卡标注 MTP trained with multiple steps。投机解码（speculative decoding）草稿模型可以直接用权重自带的 MTP 头，不必另训。
- **词表 248,320 是padded 值**，模型卡明确写(Padded)，做 embedding 容量估算时别按这个数算有效词表。

## Context Length and YaRN Window Extension

`Qwen3.8-27B` 与 `Qwen3.8-2.4T-A95B` 的 `max_position_embeddings` 都是 **262144**（256K）原生，模型卡写作「262,144 natively and extensible up to 1,000,000 tokens」，扩窗方式是 RoPE 缩放（YaRN），官方给的目标值：27B 扩至 1,000,000，2.4T-A95B 扩至 1,010,000。托管版 Qwen3.8-Max 默认就是 1M。

扩窗的具体配置在模型卡里给了完整命令行，vLLM 与 SGLang 各自的环境变量不同：

```
# vLLM
VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 vllm serve ... --hf-overrides '{"text_config": {"rope_parameters": {"rope_type": "yarn", "factor": 4.0, "original_max_position_embeddings": 262144, ...}}}' --max-model-len 1000000

# SGLang
SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 python -m sglang.launch_server ... --json-model-override-args '{...}' --context-length 1000000
```

> ⚠️ **YaRN 是静态缩放，不是动态的。** 模型卡明确警告：所有主流开源框架实现的都是静态 YaRN，缩放因子不随输入长度变化，**会牺牲短文本性能**。所以 `factor` 要按自己的典型负载设——若典型上下文是 524,288，官方建议设 `factor: 2.0` 而不是 4.0。只有在真的需要处理超长文本时才改`rope_parameters`。

## Thinking and reasoning_effort

Qwen3.8 **默认开启 thinking**，输出里会带 `<think>\n...</think>\n\n`。采样参数按模式分两套，thinking 模式是 `temperature=1.0, top_p=0.95, top_k=20`，instruct（非思考）模式是 `temperature=0.7, top_p=0.80, presence_penalty=1.5`。这两个默认值与 DeepSeek 正好相反（DeepSeek 默认 thinking、但采样推荐不同），跨模型迁移配置时要单独校准。

`reasoning_effort` 三档，**默认 `xhigh`**：

- `xhigh`（默认）：复杂任务、彻底分析
- `medium`：精度与速度平衡
- `low`：效率优先，压成本

另有 `preserve_thinking`，**默认开启**：保留全部历史消息中的 thinking 块，模型卡说明这既降低 agent 场景下的重复推理、又改善 KV cache 利用率。要只保留最近一轮用户消息的思维链，设`preserve_thinking: False`。

**关掉 thinking 的两个坑**：`Qwen3.8-27B` 走本地权重时用 `chat_template_kwargs: {"enable_thinking": False}`；走 QwenCloud API 时参数位置不同，要改成 `extra_body={"enable_thinking": False}`。直接照抄另一条路径的参数会静默不生效。

## Inference Engine

官方在 Qwen3.8 仓库里给出的推荐顺序与适配情况：

| 引擎 | 定位 | 备注 |
| :--- | :--- | :--- |
| **SGLang** | 生产／高吞吐首选 | 提供 [Qwen3.8 Cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8) |
| **vLLM** | 生产／高吞吐 | 提供 [Qwen3.8 Recipe](https://recipes.vllm.ai/Qwen) |
| **TokenSpeed** | 高吞吐 | 提供 [Qwen3.8 Recipe](https://lightseek.org/tokenspeed/recipes/models#qwen3-8) |
| `transformers serve` | 模型定义与轻量服务 | 官方给了 `transformers serve Qwen/Qwen3.8-27B --port 8000 --continuous-batching` |
| **llama.cpp** | 边缘／CPU／Apple Silicon | 仓库说明支持 Qwen3.5 系列的文本与视觉 |
| **MLX** | Apple Silicon 原生 | `mlx-lm`（纯文本）与 `mlx-vlm`（视觉+文本）|
| **Unsloth** | 本地 UI + 训练 | 有专门的 Qwen3.8 quants 运行指南 |

> ⚠️ **llama.cpp 与 MLX 的官方说明写的是「Qwen3.5 open model series」，不是 3.8。** 仓库原文是「llama.cpp supports the Qwen3.5 open model series (text & vision)」和「mlx-lm … support the Qwen3.5 open model series」。27B与 3.8 共用 `qwen3_5` 架构标记，实际能否跑通要自己试；生产部署建议直接上 SGLang / vLLM，两边都有 Qwen3.8 的专门 recipe。

起服务时两个引擎都需要指定推理解析器与工具解析器，这是 Qwen3.8 服务化的必要参数：

```bash
# SGLang
sglang serve --model-path Qwen/Qwen3.8-27B --port 8000 --tp-size 4 \
  --context-length 262144 --reasoning-parser qwen3 --tool-call-parser qwen3_coder

# vLLM
vllm serve Qwen/Qwen3.8-27B --port 8000 --tensor-parallel-size 4 --max-model-len 262144 \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder
```

视频输入在 vLLM 上需要额外开关：`--media-io-kwargs '{"video": {"num_frames": -1}}'`，模型卡注明该特性目前仅 vLLM 支持。

微调侧官方点名 Unsloth、ModelScope Swift、Llama-Factory，支持 SFT、DPO、GRPO。

## Weight Acquisition

HuggingFace 与 ModelScope 同名同步，模型 ID 就是 `Qwen/Qwen3.8-27B` 这种形式。HuggingFace 不可达时官方推荐走 ModelScope，框架侧设环境变量即可：

```bash
export SGLANG_USE_MODELSCOPE=true
export VLLM_USE_MODELSCOPE=true
```

## Positioning Relative to Domestic Siblings

放进开源阵营看，Qwen 的位置是**规模与完整度最齐、协议分叉最需留意的一家**：

| 维度 | Qwen | GLM | Kimi | DeepSeek |
| :--- | :--- | :--- | :--- | :--- |
| 最新开放权重 | Qwen3.8（2026-08） | GLM-5.3（2026-08） | Kimi K3（2026-07） | V4.1（2026-09） |
| 最大规模 | 2.4T / 95B 激活 | 744B / 40B 激活 | 2.8T / 104B 激活 | 552B |
| 协议 | ⚠️ 同代双协议 | ⚠️ 旗舰转自定义 | ⚠️ 只开权重 | Apache-2.0 |
| 原生上下文 | 256K，YaRN 扩至 1M | 1M | 1M | 1M |
| 多模态 | Dense 侧原生 | Flash 侧原生 | 原生 | Flash 侧原生 |
| API 形态 | QwenCloud，OpenAI + Anthropic 双格式 | api.z.ai / BigModel | 平台 API | OpenAI + Anthropic 双格式 |

Kimi K3 的总参数（2.8T）比 Qwen3.8-2.4T 更大，但Qwen 是同代里唯一提供 Apache-2.0 纯文本选项的（27B），且三家里只有 Qwen 覆盖从 0.8B 到 2.4T 的完整尺寸谱系——小尺寸档位是它被大量项目选中的真正原因。

详细横向对比与各家协议条款见 [Open Model](/docs/CS/AI/LLM/Model/Open_Model.md)，部署侧选型见 [Inference](/docs/CS/AI/LLM/Model/Inference.md)，价格侧见 [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md) 的横向位置一节。

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [LLaMA Factory（微调工具链）](https://github.com/hiyouga/LLaMA-Factory)
- [Qwen Code（官方终端 Agent）](https://github.com/QwenLM/qwen-code)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Transformer](/docs/CS/AI/Transformer.md)

## References

- [QwenLM/Qwen3.8 仓库（News 含完整时间线）](https://github.com/QwenLM/Qwen3.8)
- [Qwen3.8-Flash-Next 仓库（Qwen4 架构预览）](https://github.com/QwenLM/Qwen3.8-Flash-Next)
- [Qwen3.8-2.4T-A95B 模型卡（ModelScope）](https://modelscope.cn/models/Qwen/Qwen3.8-2.4T-A95B)
- [Qwen3.8-27B 模型卡（ModelScope）](https://modelscope.cn/models/Qwen/Qwen3.8-27B)
- [Qwen3.5 发布博客（397B-A17B 与 235B 对比）](https://qwen.ai/blog?id=qwen3.5)
- [Qwen3.8-Max 发布博客](https://qwen.ai/blog?id=qwen3.8)
