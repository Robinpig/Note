## Introduction

Kev 是独立开发者 **Jared Palmer** 于 2026-09-17 开源的 **System One（决策）模型家族**，Apache-2.0。它和 TypeSafe 的 [Jev](/docs/CS/AI/LLM/Model/Jev.md) 回答同一类问题——输入一段 state 加类型化问题（Choice / Score / Noul），输出带概率的判断，**不生成文本**——但 Kev 把权重、训练代码与评测集全部开放，定位是「把路由、分诊、护栏这类高频快判断彻底搬回自己的机器」。

它被称为 Jev 生态里**最可替换的一支**：服务端暴露 `POST /v1/systemone`，请求/响应体与 TypeSafe 完全一致，官方 TypeSafe Python SDK 只要把 `base_url` 指向本地 Kev 即可零改动调用。

> [!WARNING]
>
> **版本基线：2026-10-26 核实。** 三件事先说清：① Kev 是**开权重自托管**，没有官方托管 API（仅 OpenRouter 上架了 Kev-4B 一种托管）；② 所有「准多少、快多少」数字多为**作者自报口径**（repo 自带 benchmark，也跑 Jev 对照），未独立复核；③ 27B 这一支基座是 Qwen3.8-27B（post-trained 发布），其训练数据作者自述未知，与 0.8B/4B/9B 的 Qwen3.5-Base 起点不同，比较时要分开看。

## Family and Base Models

| 型号 | 基座 | 硬件门槛 |
| :--- | :--- | :--- |
| Kev-0.8B | Qwen3.5-Base | 可 CPU；Mac / 24GB GPU |
| Kev-4B | Qwen3.5-Base | 32GB Mac 或 24GB GPU（单卡） |
| Kev-9B | Qwen3.5-Base | 32GB Mac 或 24GB GPU |
| Kev-27B | Qwen3.8-27B | 80GB 数据中心 GPU，**无 Mac 路径** |

0.8B / 4B / 9B 从 Qwen **base** checkpoint 起步；27B 从 Qwen3.8 **post-trained** 发布起步。基座冻结，上面挂一个 **rank-16、α32 的 LoRA adapter**（作用于 attention / MLP / DeltaNet 投影，约 33.8M 参数）加一个**指针头（pointer head）**：两层投影把每个选项的收尾 token 与问题的末 token 打分，softmax 成概率。

## Question Isolation and Interface

与 Jev 同样，一次请求里多个问题共享同一段 state 但**互相不可见**——常规靠 attention mask 阻断，而在 Qwen3.5 的 Gated DeltaNet 层（循环结构、忽略 attention mask）上，Kev 把每个问题作为独立行运行以保证严格隔离。服务端只计算一次 state 缓存并在问题间复用。

接口即 `POST /v1/systemone`，三种原语与 Jev 一致：

| 类型 | 选项数 | 返回 |
| :--- | ---: | :--- |
| `choice` | 1–255 命名选项（可带描述） | 每选项概率 + 最可能项 + confidence |
| `score` | 2–255 有序等级 | 每等级概率 + 期望等级索引 |
| `noul` | 是 / 否 | 「是」的概率 |

⚠️ **语义差别落在阈值上**：Kev 的概率是「选项得分的 softmax」，不是 Jev 的 `(n·p_max − 1)/(n − 1)` 式 confidence；迁移时必须用边界样本**重标阈值**，别假设 0.8 还是 0.8（这点与 Laya 同族坑，见 [Jev](/docs/CS/AI/LLM/Model/Jev.md?id=the-interface-won-jev-compatible-decision-models)）。

## Deployment: Self-hosted and OpenRouter

- **自托管**：CUDA / ROCm / MLX（Apple Silicon）均可；`kev.train --init_from jaredpalmer/kev-4b` 可在自己的标签上微调。repo 还提供 Modal 部署脚本（L40S + bearer key）与浏览器内 Hugging Face Space（跑 Kev-4B / Kev-0.8B）。
- **OpenRouter Kev-4B**（2026-09-25 上架，SiliconFlow fp8 托管）：输入 **$0.042 / MTok、输出免费、上下文 8,192**——与 Jev 同价。切换只需把 `model` 改为 `jaredpalmer/kev-4b`，请求体不变。0.8B / 9B / 27B 不在 OpenRouter。

上下文细节：自托管下 state 最多 65,536 token、每问至少 8,192；Kev-4B 验证上下文为 8,192（训练时 state ≤ 7,552）。

## Calibration

每个 checkpoint 自带一个在分布内数据上拟合的温度（如 Kev-4B **T = 2.41**，存于 `head.pt` 加载时应用），它改变概率分布的形状但**不改变答案**。这是 Kev 敢于把 `if prob > 0.9` 当统计依据的前提。

## Benchmarks (Author-reported)

数字来自 repo 自带 benchmark（同时跑 Jev 对照），**未独立于作者**：

| 模型 | 开发集 | 测试集 | 备注 |
| :--- | ---: | ---: | :--- |
| Kev-9B | 0.822 | 0.852（Jev 未跑） | vs Jev 0.857 |
| Kev-27B | 0.848 | 0.896 | 基座不同，单独看 |
| Jev（参照） | 0.857 | — | 厂商自报 |

第三方 **System One Score**（systemonemodels.org，跨三个独立榜综合）把 Kev 排 **89.9 / 100，第一**，标注 *best overall / best calibrated*；Kev-27B 在 Jev Decision Index 上的校准误差 **0.022** 为已排名模型中最低。对照看，独立 49 任务分类基准上 Jev 仍 0.966、最佳开源入局约 0.704——**开源赢了延迟/价格/可控，未必赢开箱准确率**。

## Limitations

- **无官方托管 API**，只有 OpenRouter 上的 4B 一种；其余全靠自托管，意味着一张 GPU 账单。
- **27B 训练数据未知**（Qwen3.8 post-trained 基座），与 0.8B/4B/9B 不构成纯方法对照。
- **仅英文**为主的判断质量，非英文负载需自测。
- 与所有 Jev 兼容实现一样，**换后端不等于换 base URL**：confidence 是不同函数，阈值必须重标。

## Links

- [Jev](/docs/CS/AI/LLM/Model/Jev.md)
- [Overview](/docs/CS/AI/LLM/Model/Overview.md)
- [SemIf](/docs/CS/AI/LLM/Model/SemIf.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Kev-4B (Hugging Face)](https://huggingface.co/jaredpalmer/kev-4b)
- [Kev (systemonemodels.org)](https://systemonemodels.org/models/kev)
- [Kev GitHub (jaredpalmer/kev)](https://github.com/jaredpalmer/kev)
- [Best AI decision models in October 2026](https://systemonemodels.org/compare/best-ai-decision-models)
