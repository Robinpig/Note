## Introduction

> **版本基线：2026-10-05 核实。** 引擎版本取各项目 GitHub Releases 当日快照；硬件支持清单以 vLLM、SGLang、llama.cpp、Ollama 官方文档为准；量化格式以 vLLM 官方量化文档的支持矩阵为准。

本地部署这一层在 2026 年最大的变化不是更快，而是**硬件分层**。同一年里FP8 在数据中心成了默认、GGUF 在端侧仍是唯一解、FP4 上了 Blackwell、国产芯片各自有自己的插件通道——**「选一个量化格式通吃所有场景」的想法已经失效**。现在必须先确定目标硬件，再定格式，最后才选引擎。

本文只记部署与推理事实。模型侧选型见 [Open Model](/docs/CS/AI/LLM/Model/Open_Model.md) 与 [Qwen](/docs/CS/AI/LLM/Model/Qwen.md)，协议层见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)。

## Positioning of the Four Engines

| 引擎 | 核实版本 | 定位 | 上手成本 |
| :--- | :--- | :--- | :--- |
| **Ollama** | v0.35.1 稳定（另有 v0.40.0-rc3 预发布） | 本地跑通优先、单模型试用 | 最低，一条命令 |
| **vLLM** | v0.31.0 | 数据中心生产服务首选 | 中 |
| **SGLang** | v0.5.21 | 高吞吐、结构化输出与 Agent 场景 | 中 |
| **llama.cpp** | b11411 | 边缘、CPU、Apple Silicon、超大模型卸载 | 低到中 |

> ⚠️ **llama.cpp 用 `b` 加 build 号而不是语义化版本号，且一天能出多个 build。** 核实日当天 b11411 与 b11412 前后脚发布。这类引擎的版本基线只在几小时内有效，凡涉及复现问题或写文档，务必带上具体 build 号。新模型首发时官方也会给出最低 build 要求（如 Muse Glimmer 的官方 GGUF 要求 b10353+）。

> ⚠️ **Ollama 有稳定的预发布通道，当前 v0.40.0-rc3 领先稳定版 v0.35.1 一个多版本号。** 落后不是落后，是刻意的节奏控制：新模型支持先在rc 里落地。所以「Ollama 跑不动某个新模型」时先查 rc 通道，别急着换引擎。

### Hardware Support Matrix

| 硬件 | Ollama | vLLM | SGLang | llama.cpp |
| :--- | :--- | :--- | :--- | :--- |
| NVIDIA CUDA | ✅ CC 5.0+ | ✅ CC 7.5+ |✅ | ✅ |
| AMD ROCm | ✅ ROCm v7 | ✅ ROCm 6.3+（预编译 7.0/ 7.2.1） | ✅ | ✅ (HIP) |
| Intel XPU | ❌ | ✅（需 `vllm-xpu-kernels`） | ✅（仅源码安装） | ✅ (SYCL) |
| Apple Silicon | ✅ Metal API | ✅ vLLM-Metal（社区插件，MLX 后端） | ✅（MLX，`SGLANG_USE_MLX=1`） | ✅ Metal（一等公民） |
| Google TPU | ❌ | ✅（独立项目） | ✅ SGLang-JAX 后端 | ❌ |
| 昇腾 Ascend NPU | ❌ | ✅ vLLM-Ascend | ✅ 官方文档 | ⚠️ CANN 后端 |
| 摩尔线程 MUSA | ❌ | 插件 | ✅ 原生页 | ✅ MUSA 后端 |
| CPU | ✅ | ✅ x86 / AArch64 / S390X | ✅（Intel AMX 优化） | ✅ 多架构 SIMD |
| Jetson Orin | ✅ | — | ✅ 文档 | ✅ Android arm64 |

几处需要说明的细节：

- **llama.cpp 在国产卡上比预期支持得多。** 官方后端表里有 **CANN（昇腾 NPU）** 和 **MUSA（摩尔线程）** 两个国产后端，还有 `ZenDNN`（AMD CPU）、`IBM zDNN`（IBM Z）、`Hexagon`（骁龙）、`OpenCL`（Adreno GPU）、`OpenVINO`（Intel CPU/GPU/NPU，标注 In Progress）、`WebGPU`、`VirtGPU`、RPC 分布式。国产卡在这四个引擎里是**只有 llama.cpp 官方后端表里有 CANN 与 MUSA**。
- **Ollama 的Apple Silicon 支持是 Metal API，不是 MLX。** 官方硬件页原文是「Ollama supports GPU acceleration on Apple devices via the Metal API」。另外 Ollama 还支持 **Vulkan**（Windows 与 Linux 上的额外 GPU 覆盖，依赖装好后默认启用），环境变量是 `GGML_VK_VISIBLE_DEVICES`。
- **vLLM 的 Apple Silicon 走的是社区维护的硬件插件** vLLM-Metal，用 MLX 作计算后端，且官方建议搭配 HuggingFace `mlx-community` 组织下的 MLX 优化模型。
- **SGLang 的 Apple Silicon 支持要求 macOS 14+、PyTorch 2.13.x、MLX 0.32.0+**，且编译可选的 `sgl-kernel` 原生 Metal kernel **需要完整版 Xcode**，单独装 Command Line Tools 不够。

### Third-Party Hardware Plugin Mechanism

国产芯片能进vLLM 与 SGLang，靠的是一套正式的插件机制而不是fork。

**vLLM** 有两个层次：`vllm-xpu-kernels`（Intel 的独立 kernel 包，绑 Python 3.12）把 GPU 后端做成可插拔；更通用的是**量化插件**——用 `@register_quantization_config` 装饰器注册 `QuantizationConfig` 子类，即可接入自有量化方案而不改vLLM 代码库。

**SGLang** 的插件系统表述更明确：「Allows hardware vendors and developers to extend SGLang **without modifying the main repository code**」，通过 Python 标准 `setuptools` entry_points 发现，两类插件分别对应不同 entry point group。

> ✅ **所以评估国产卡支持时，看两件事：一是该芯片厂商有没有提交上层的量化/后端插件，二是有没有进入上游项目的官方文档目录。** SGLang 的 `docs/docs/hardware-platforms/` 目录当前有 nvidia-gpus、amd_gpu、apple_metal、ascend-npus、cpu_server、mthreads_gpu、nvidia_jetson、tpu、xpu、overview、plugin 十一个条目——摩尔线程与昇腾都有独立目录，这比任何二手清单都更能说明支持深度。

## Quantization Formats: Layered by Hardware

> ⚠️ **2026 年已经没有单一主流量化格式了。** 常见的「Qwen 3.8 该用哪个量化」这个问题，答案取决于你跑在什么卡上：同一模型在 Hopper 上选 FP8，在 M4 上选 Q4_K_M，在 Blackwell 上才考虑 FP4。下面这张表是按硬件层的选择依据。

| 格式 | 位宽 | 目标硬件 | 特征与代价 |
| :--- | :--- | :--- | :--- |
| **FP8**（W8A8） | 8 | 数据中心默认 | Hopper/Ada/Blackwell 原生；权重与激活显存减半；近无损；vLLM/SGLang 免校准 |
| **GGUF** `Q4_K_M` / `Q5_K_M` | ~4.5–5.5 | CPU / 边缘 / Apple Silicon | 唯一支持 GPU+RAM 混合卸载；超大模型唯一出路 |
| **AWQ**（INT4） | 4 | 数据中心 GPU 常规服务 | 激活感知量化，保护约 1% 显著权重；Marlin-AWQ 内核 |
| **GPTQ**（INT4） | 4 | 基座 + 多 LoRA 场景 | vLLM 中唯一支持多 LoRA 的 INT4 路径；Marlin 提速明显 |
| **NVFP4 / MXFP4** | 4 | Blackwell 极限密度 | ⚠️ 硬件门槛高，见下|
| **bitsandbytes NF4** | 4 | **仅微调/训练** | QLoRA 标准配置，**不是推理格式** |

vLLM 官方量化文档给出的硬件支持矩阵（✅︎支持 / ❌不支持）：

| 实现 | Volta | Turing | Ampere | Ada | Hopper | AMD | Intel | x86 CPU | Arm CPU |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| AWQ | ❌ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ |
| GPTQ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ |
| Marlin (GPTQ/AWQ/FP8/FP4) | ❌ | ✅︎\* | ✅︎ | ✅︎ | ✅︎ | ❌ | ❌ | ❌ | ❌ |
| llm-compressor FP8 (W8A8) | ❌ | ❌ | ❌ | ✅︎ | ✅︎ | ✅︎ | ❌ | ❌ | ❌ |
| llm-compressor INT8 (W8A8) | ❌ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ❌ | ❌ | ✅︎ |
| GGUF | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ✅︎ | ❌ |

这张表里有两个容易读错的地方：

- **FP8 W8A8 从 Ada 才开始支持，Turing/Ampere 是不支持的。** 「Hopper 原生」的说法没错，但不完整——如果你的卡是 A100（SM 8.0），llm-compressor 的 FP8 W8A8 走不通，要退回 INT8 W8A8 或 INT4 路线。
- **Marlin 在 Turing 上不支持 MXFP4**（文档标了 `*`）。Marlin 覆盖 GPTQ/AWQ/FP8/FP4 四种，但 CPU 端全线不支持。

### Why FP8 Became the Default

FP8 从「研究阶段」变成「数据中心生产默认」是这两年最实质的变化。它的优势不在压缩率而在**免校准**——AWQ/GPTQ 需要在数据集上跑校准来保护显著权重，FP8 直接缩放，所以部署链路少一个失败点。代价是 4-bit 路径的精度损失明显大于 FP8，所以 FP8 承担了「服务端默认」这个位置。

### Current Status of FP4 and NVFP4

> ⚠️ **FP4 已从研究走到生产，但门槛是 Blackwell。** Hopper 与 Ampere 上想要 4-bit，仍然只能走 AWQ 或 GPTQ。NVFP4 配合 `--linear-backend` 使用，vLLM 文档给的示例显示可以用 `linear_backend_per_quant` 做混精度覆盖（如让 NVFP4 层走 Humming 后端、其余走 CUTLASS）：

```bash
vllm serve <model> \
  --linear-backend cutlass \
  --kernel-config '{"linear_backend_per_quant":{"nvfp4_w4a16":"humming"}}'
```

另一个方向是 **MXFP4**——Kimi K3 已经把它做成**出厂默认格式**（MXFP4 权重 + MXFP8 激活，量化感知训练），而不是社区后处理产物。昇腾侧也宣布支持 mxFP4/mxFP8，配合 950 芯片的 SIMT 编程。

### How to Choose Between AWQ and GPTQ

两者的实际差异比理论差异大：

- **AWQ** 是激活感知量化，运行时按激活分布保护约 1% 的显著权重，Marlin-AWQ 内核速度好。**常规服务选AWQ。**
- **GPTQ** 在 vLLM 里有一条别人没有的能力：**唯一支持多 LoRA 的 INT4 路径**。如果你要在一个基座上挂多个 LoRA 适配器（同一个基座服务多个业务），GPTQ 是唯一选择，AWQ 做不到。Marlin 内核对 GPTQ 有明显提速。

### GGUF and Hybrid Offloading

GGUF 的 `Q4_K_M` 约 4.5 bit/weight，是端侧甜点区；`Q5_K_M` 在内存宽裕时质量更稳。但 GGUF 真正的独特之处是**唯一支持 GPU+RAM 混合卸载**——模型大于显存时，把部分层放显存、部分层留系统内存，靠内存带宽与算力之间的取舍跑起来。**这是跑超大模型（远超单卡显存）唯一现实的路径**，llama.cpp 的 README 把「CPU+GPU hybrid inference to partially accelerate models larger than the total VRAM capacity」列为核心特性。

## Domestic Chips

### Huawei Ascend

生态完整度上没有第二家能比。华为昇腾计算业务在 2026 年 4 月披露的数据：**已与 Triton、PyTorch、vLLM、SGLang 等 90 多个主流开源社区深度对接，对 DeepSeek、Qwen 等 70 余个主流大模型完成「0day适配」与全链路优化**，预置 1500 多个基础算子与 100 多个融合算子，全年向社区开放 4000卡算力资源。

两个标志性的生态地位：

- **Triton Ascend 是 Triton 官方社区首个支持的国产加速后端。** 关键区别在于「融入主仓库」而非「插件独立、版本脱节」——社区版本发布时同步支持昇腾硬件。
- **TorchNPU 正式上线 PyTorch 官网**，是首个获官方支持的中国芯片硬件，也是首个拥有官方分支仓下载支持的加速后端。昇腾累计向 PyTorch 社区贡献超 20 万行核心代码，参与重构约 100 万个测试用例，2000 多张昇腾卡接入社区 CI/CD 做 7×24 小时质量看护。

CANN 的时间线也值得记：2023 年 Ascend C 编程语言发布、PyTorch 同步支持昇腾；2024 年底层运行时能力全面开放；2025 年 vLLM 发布昇腾版本、Triton-Ascend 推出；**2026 年随 950 芯片发布，CANN 实现 SIMT 编程支持，新增 SIMT+SIMD 混合编程、Vector 高算力、CCU 专用通信引擎**，并支持 HiFP8/MXFP8/MXFP4 等低精度格式，官方称内存占用降低 50%+、计算能力翻倍。CCU 通信引擎提供基于 CCU 的 Allreduce、Allgather、Reducescatter、AlltoAll 等主流通信原语。

SGLang 侧的昇腾文档有完整目录：`getting-started/`（含 CANN 版本映射，**每个 CANN 版本有自己匹配的一套组件版本，不要跨套混用**）、`development/`、`optimization/`、`model-deployment/`、`diffusion/`、`evaluation/`，还有一个 `mindspore_backend.mdx`——**MindSpore 是 SGLang 支持的第三个后端路径**，GLM-5 训练用的就是 MindSpore。

### Moore Threads

MUSA 在 **SGLang 官方硬件页有独立条目**（`mthreads_gpu`），通过 `torch_musa` 与 `torchada` 运行时接入，`python[all_musa]` extra 会从摩尔线程包索引装 MUSA torch、Triton、**TileLang**、MATE 与运行时全栈。文档给了 MTT S5000 驱动安装指引。

另一个信号：**GLM-5 发布当天（2026-02-12）完成 Day-0 全流程适配**。

### Other Domestic Chips

智谱在 GLM-5 模型卡与博客里明确列出官方支持部署的非 NVIDIA 芯片：**华为昇腾、摩尔线程、寒武纪、昆仑芯、沐曦（MetaX）、燧原（Enflame）、海光（Hygon）**，并称通过算子优化与模型量化在这些芯片上达到合理吞吐。SGLang 与 vLLM 均可承载。

> ⚠️ **TensorRT-LLM 完全不支持任何国产卡。** 它绑定 CUDA，是 NVIDIA 独占。所以国产卡上想要 TensorRT-LLM 级别的优化，只能靠厂商自研后端（如 SGLang 的 `sgl-kernel`、vLLM-Ascend），没有通用捷径。

> ⚠️ **国产卡MoE all-to-all 通信性能约为国际旗舰的 50–65%，这是当前最大瓶颈。** MoE 模型在解码时每层都要做专家分发，通信量远大于 dense 模型，而国产卡的互联带宽与 collective 通信库成熟度是主要短板。所以国产卡上跑 MoE 的实测吞吐会明显低于同参数规模 dense 模型，**不要直接用「与国际旗舰的 token/s 比值」来判断卡好坏**。端侧小模型（如星火 4B/1.7B）因为不是 MoE，这个瓶颈不明显。

## Selection Path

按顺序问四个问题就能定下方案：

1. **卡是什么** → 决定格式上限。Blackwell 才给FP4，Hopper 给 FP8，Ampere 只能 INT8/INT4，CPU 与Apple Silicon 走 GGUF。
2. **模型多大 vs 显存多大** → 模型远超显存就只剩 GGUF 混合卸载一条路。
3. **要不要多 LoRA** → 要，就只能 GPTQ；不要，AWQ 或 FP8 更省心。
4. **是微调还是推理** → 微调才用 bitsandbytes NF4，推理别碰它。

三个常见错误值得单独点出：

- **在 Hopper/A100 上强行上 FP4。** 硬件不支持，`--linear-backend` 配了也没用，退回 AWQ。
- **用 bitsandbytes NF4 做推理。** 它是 QLoRA 训练格式，为训练设计，推理路径没有优化甚至可能不支持。vLLM 矩阵里 bitsandbytes 在 CPU 与 Intel GPU 上都是 ❌。
- **在 Ampere 上用 llm-compressor FP8 W8A8。** 该组合在官方矩阵里是 ❌，需要退回 INT8 W8A8。

## Links

- [Model 总览](/docs/CS/AI/LLM/Model/Overview.md)
- [RAG](/docs/CS/AI/RAG.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)
- [Dify](/docs/CS/AI/LLM/Platform/Dify.md)

## References

- [Ollama Releases](https://github.com/ollama/ollama/releases) ／ [Ollama 硬件支持](https://docs.ollama.com/gpu)
- [vLLM Releases](https://github.com/vllm-project/vllm/releases) ／ [vLLM GPU 安装与后端](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/) ／ [vLLM 量化格式与硬件支持矩阵](https://docs.vllm.ai/en/latest/features/quantization/)
- [SGLang Releases](https://github.com/sgl-project/sglang/releases) ／ [SGLang 硬件平台文档](https://github.com/sgl-project/sglang/tree/main/docs/docs/hardware-platforms)
- [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) ／ [llama.cpp 支持的后端](https://github.com/ggml-org/llama.cpp/blob/master/README.md)
- [昇腾算力平台生态进展（90+ 开源社区、SIMT/CCU、mxFP4）](http://intl.ce.cn/sjjj/qy/202604/t20260427_2932533.shtml)
- [Triton Ascend 首个国产加速后端、TorchNPU 上线 PyTorch 官网](https://cn.chinadaily.com.cn/a/202609/15/WS6aa8b2abe4b09a165c78a0d4.html)
- [Ascend C v9.0.0-beta.2 SIMT/CCU/MXFP4 特性](https://gitcode.com/hehongan/asc-devkit/blob/master/README_en.md)
- [GLM-5 模型卡（非 NVIDIA 芯片部署支持列表）](https://modelscope.cn/models/ZhipuAI/GLM-5)
