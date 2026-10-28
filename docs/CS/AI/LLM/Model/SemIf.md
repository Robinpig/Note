## Introduction

SemIf（前身 **OpenJev**）是开发者 **TheoLeeCJ** 于 2026-09-16 开源的 AI 决策模型项目，MIT 许可。它复现 TypeSafe 闭源 [Jev](/docs/CS/AI/LLM/Model/Jev.md) 的「语义决策」接口范式，被社区形象地称为**「语义 If（Semantic If）」**：用自然语言理解给经典 if-else 分支赋予判断能力。

与需要微调或训练 adapter 的同类不同，SemIf 的核心取舍是 **training-free（不微调）**——直接拿一个**冻结的开源模型**（Qwen3.5-4B，或 MiniCPM5 2B，或 Qwen3.5 4B），单次前向传播读取候选选项对应的 **logits** 打分，由服务端构造结构化结果，**完全不生成答案文本**。

> [!WARNING]
>
> **版本基线：2026-10-26 核实。** ① SemIf 不训练、不改权重，质量完全取决于冻结基座的 logits 分布；② 所有「快多少」数字来自项目方与社区报道，未独立复核；③ 它只回答 Jev 同款三类问题，不做生成/解释/多跳。

## How It Works: Read Logits, Not Generate

传统做法是让模型生成一段 JSON 再解析；SemIf 把候选选项拼进 prompt，一次前向直接读这些选项对应位置的 logits 转成概率，省掉生成与解析。因此：

- **零生成 token** → 没有 JSON 格式错误、解码循环、输出解析失败这类问题。
- **21 个二元决策约 1 秒完成**，比生成 JSON 快约 **5.2 倍**。
- 标准与选项描述都随请求传入，**无需微调、无需预定义任务**——适合路由、重试判断这类随时会变的小型 agent 决策。

## Shared State: One Prefill, Many Branches

多个判断共享同一段上下文（如同一用户状态判多个标准）时，SemIf 的 `shared` 模式**预填充一次前缀**，再串行或并行评估各标准。官方数据：共享状态场景的吞吐量从 **2.33 提升到最高 20.03 决策/秒**。

## Calibration and Hardware

- **温度校准**：内置按工作负载拟合的温度缩放脚本，让输出概率置信度与实际准确率对齐，校准后的置信度可直接用于自动化阈值（如 NLI 里「证据是否支持结论」）。
- **硬件门槛低**：冻结的 4B 模型**单张 RTX 3090 即可运行**；支持 CUDA GPU、Apple Silicon（MPS/MLX）、CPU，以及浏览器 WebGPU 演示。环境要求 Python 3.10+、能容纳 4B BF16 的显卡。
- **27B 桥接**：除冻结 4B 外，项目提供一条通向 27B 模型的桥接路径，用于更大规模的人工决策比对。

用法骨架（直接模式）：

```bash
semif-score --mode direct --model Qwen/Qwen3.5-4B \
  --input examples/decisions.jsonl --output results.jsonl
# 共享状态：--mode shared
```

## Benchmarks and Positioning

SemIf 的卖点不是开箱准确率（它不训练），而是**零训练成本 + 极低部署门槛 + 完全可审计**：

- 仓库提交了固定 prompt、模型版本、prompt 哈希、逐行输出与已知失败，可精确复现。
- 在「复用已有模型、不想微调」的场景里，它比 Laya（需微调的 encoder）和 Kev（需 LoRA 训练）更轻——**你本来就在跑 Qwen3.5-4B，就直接拿它读 logits**。
- 代价是：判断质量天花板受限于基座；且同样不解决「高基数选项」「多模态」等非 Jev 结构性短板。

## Limitations

- **training-free 的双刃剑**：没有针对决策任务的后训练，复杂或高基数选项上大概率不如微调过的 Laya / Kev。
- **仅文本**，不接收图像/音频/视频。
- **校准需自拟合**：开箱概率未必可信，上线前要在自己的负载上跑温度缩放。
- 与所有 Jev 兼容实现一样，换基座/换后端后**阈值要重标**。

## Links

- [Jev](/docs/CS/AI/LLM/Model/Jev.md)
- [Overview](/docs/CS/AI/LLM/Model/Overview.md)
- [Kev](/docs/CS/AI/LLM/Model/Kev.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [SemIf – 开源的 AI 决策模型 (ai-bio.cn)](https://ai-bio.cn/semif)
- [SemIf 开源决策模型：用 logits 直读替代生成 (ChatTools)](https://ai.chattools.top/article/68202)
- [SemIf – 开源的 AI 决策模型，复现 Jev 语义决策模式 (CloudsAI)](https://www.cloudsai.cn/ai-tutorials/7004.html)
- [SemIf 霸榜 GitHub (AI DAILY)](https://sns.style/zh/news/2026/09/20/semif-tops-github-open-source-community-replicates-jev-paradigm-for-millisecond-1)
