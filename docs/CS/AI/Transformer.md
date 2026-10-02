## Introduction

Transformer 是 2017 年 Google 在《Attention Is All You Need》中提出的序列建模架构。它的核心主张写在标题里：**注意力就够了**——完全抛弃 RNN 的时间递推与 CNN 的局部卷积，只用 self-attention + FFN 堆叠，就能把任意序列位置之间的依赖一次性算出来。

它之所以成为 [LLM](/docs/CS/AI/LLM/LLM.md) 的地基，原因不在"效果更好一点点"，而在于三个工程性质同时成立：

- **可并行**：RNN 第 t 步必须等 t-1 步，序列长度方向上无法并行；Transformer 一次矩阵乘法算完整个序列的所有位置对，训练吞吐随 GPU 数量线性扩展。这让万亿 token 语料上的预训练第一次变得可行。
- **短路径**：任意两个位置之间的信息传播路径长度是 O(1)（RNN 是 O(n)），长程依赖不再依赖记忆单元的逐级搬运。
- **可扩展**：同一套 block 可以无脑堆叠到上百层、千亿参数，配合 Scaling Law，能力随规模幂律增长（见 [AI](/docs/CS/AI/AI.md) 中的三范式对比）。

今天的 BERT、GPT、LLaMA、Qwen、DeepSeek、ViT、Diffusion Transformer 全是它的变体。理解 Transformer 的每一层在计算什么，是理解上下文窗口、KV cache、幻觉、量化、长文本外推这些工程问题的前提。

## 动机：为什么用 Self-Attention 替代循环

原论文用三个指标对比三种序列层：每层的计算复杂度、**顺序操作数**（不可并行的步骤数）、**最大路径长度**（任意两位置间的最长信息传播路径）。

| 层类型 | 每层复杂度 | 顺序操作 | 最大路径长度 |
|--------|-----------|----------|--------------|
| Self-Attention | O(n² · d) | O(1) | O(1) |
| Recurrent（RNN/LSTM） | O(n · d²) | O(n) | O(n) |
| Convolutional | O(k · n · d²) | O(1) | O(log_k n)（膨胀卷积） |

n 为序列长度，d 为表示维度，k 为卷积核宽度。Trade-off 很清楚：self-attention 在序列长度上是 **平方代价**，换来的是常数级的路径长度和完全并行。当 n < d（2017 年的典型场景，n≈512、d≈512）时 self-attention 甚至更快；而随着模型变宽、语境变长，n² 这一项最终成为长上下文的全部瓶颈（见后文"长上下文的代价"）。

## 整体结构

原始 Transformer 是完整的 encoder-decoder（为机器翻译设计）：

```
Token IDs
   │
   ├─ Token Embedding × √d_model  ── + ── Positional Encoding ──┐
   │                                                            │
   │   ┌────────────────────────────────────────────────────────┘
   │   ▼
   │  ┌── N × Encoder Block ──────────────────────────────┐
   │  │  Multi-Head Self-Attention（双向，无掩码）          │
   │  │  └ Add & Norm（残差 + LayerNorm）                  │
   │  │  Position-wise FFN                                │
   │  │  └ Add & Norm                                     │
   │  └───────────────────────────────────────────────────┘
   │        │
   │        ▼  memory（K、V 供 decoder 读取）
   │  ┌── N × Decoder Block ──────────────────────────────┐
   │  │  Masked Multi-Head Self-Attention（causal mask）   │
   │  │  └ Add & Norm                                     │
   │  │  Cross-Attention（Q 来自 decoder，K/V 来自 memory）│
   │  │  └ Add & Norm                                     │
   │  │  Position-wise FFN                                │
   │  │  └ Add & Norm                                     │
   │  └───────────────────────────────────────────────────┘
   │        │
   ▼        ▼
Linear(d_model → vocab_size) → Softmax → 下一个 token 概率分布
```

原始 base 配置：N=6 层、d_model=512、h=8 个头（每个头 d_k=d_v=64）、d_ff=2048、dropout 0.1。现代 LLM 没有 encoder，只堆叠 decoder block（见"三种架构流派"）。

## Attention 的核心：Scaled Dot-Product Attention

### 直觉：一次可微的字典检索

把每个 token 的表示拆成三个角色：

- **Query（查询）**：我是谁，我在找什么信息；
- **Key（键）**：我有什么可被检索到的特征，用来和 Q 匹配打分；
- **Value（值）**：匹配上之后，我要贡献的内容。

每个 token 用自己的 q 和所有 token 的 k 做点积得到相关性分数，softmax 归一化成权重，再对所有的 v 做加权求和。整个过程只是矩阵乘法和 softmax，**处处可微，处处并行**。

### 公式

$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$

形状：Q ∈ R^{n×d_k}，K ∈ R^{m×d_k}，V ∈ R^{m×d_v}；输出 R^{n×d_v}。自注意力时 m=n。

### 为什么要除以 √d_k

这是全文最容易被人忽略却最关键的一步。假设 q、k 各分量独立、均值 0、方差 1，那么点积 q·k 的方差是 d_k（各项累加），标准差是 √d_k。当 d_k=64 时，点积典型值在 ±8 附近；若不缩放，这些大值经过 softmax 后分布会极度尖锐（一个权重接近 1，其余接近 0），softmax 的输出梯度正比于 p(1-p)，几乎处处为 0 —— **梯度消失，模型训不动**。除以 √d_k 把logits 拉回单位方差，让 softmax 保持"软"，保留可学习的分布。

## Multi-Head Attention

单个 attention 只能在一个表示空间里做加权平均，作者用多个头把表示投影到不同子空间并行做 attention，再拼回来：

$$
\begin{aligned}
\text{MultiHead}(Q,K,V) &= \text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O \\
\text{head}_i &= \text{Attention}(QW_i^Q,\; KW_i^K,\; VW_i^V)
\end{aligned}
$$

其中 d_k = d_v = d_model / h。这样总计算量与"用一个 d_model 维的单头"基本相当，但每个头学到了不同东西——实测中有的头专门盯句法依存，有的头盯共指消解，有的头只关注相邻词或特定标点。

工程意义：头数是并行切分维度，也是后续 MQA/GQA 压缩 KV cache 的抓手（把 K/V 的头数减少，Query 头数不变）。

## 三种 Attention 的位置与作用

| 位置 | Q 来源 | K/V 来源 | 掩码 | 作用 |
|------|--------|----------|------|------|
| Encoder self-attention | 上一层 encoder | 同左 | 无（仅 padding mask） | 双向上下文编码，每个位置看到全序列 |
| Decoder masked self-attention | 上一层 decoder | 同左 | causal mask（下三角） | 自回归建模，防止位置 i 看到 i 之后的信息 |
| Cross-attention（encoder-decoder） | decoder 上一层 | encoder 输出 memory | padding mask | 把源序列信息引入解码过程，等价于 seq2seq attention |

用检索的语言说：**self-attention 是序列自己和自己检索**（建立内部表示），**cross-attention 是拿 decoder 的 query 去检索 encoder 的 memory**（这就是后来 RAG、 function calling 结果回填在结构上的远亲）。

## Position-wise FFN

每个 token 位置独立地过同一个两层 MLP：

$$
\text{FFN}(x) = \max(0,\, xW_1 + b_1) W_2 + b_2
$$

- 通常 d_ff = 4 × d_model，是模型参数量的大头（约占 2/3）。
- 这里的"position-wise"指**同一层内所有位置共享参数、但位置之间不做交互**——交互交给 attention 层完成。两类层交替，构成了"混信息 / 加工信息"的节奏。
- 现代模型普遍把 ReLU 换成 **SwiGLU**（LLaMA、PaLM、Qwen、DeepSeek）：引入一个门控分支 `SiLU(xW_gate) ⊙ (xW_up)` 再投影回 d_model，同参数量下效果更好，代价是多一个矩阵；稀疏化的 MoE 也正是在这一层做的（见"现代 LLM 的改进清单"）。

## 残差与归一化：Pre-LN vs Post-LN

原始论文用 **Post-LN**：`LayerNorm(x + Sublayer(x))`，LayerNorm 放在残差相加之后。这条路径需要精细的学习率 warmup（原配方：4000 步 warmup、Adam β₂=0.98、label smoothing 0.1），深层模型容易训练发散。

现代 LLM 几乎全部改用 **Pre-LN**：`x + Sublayer(LayerNorm(x))`，归一化放在子层输入之前，残差分支是一条从输入直通输出的"信息高速路"，梯度可以直接回传，训练稳定性大幅提升，warmup 依赖也变弱（GPT-2 之后成为事实标准）。

为什么是 LayerNorm 而不是 BatchNorm：BatchNorm 依赖 batch 维统计量，而序列任务里 batch 内样本长度不一、padding 位置会污染统计量；推理时的 running statistics 在小 batch / 长序列下也不稳定。LayerNorm 对每个样本自身的特征维做归一化，与 batch 大小无关，天然适配自回归推理。LLaMA 之后更进一步用 **RMSNorm**（去掉减均值、只保留均方根缩放），计算更省且效果相当。

## 位置编码

Self-attention 本身是**置换不变**的——打乱输入顺序，输出只是相应打乱，模型完全感知不到"顺序"。必须显式注入位置信息。

### Sinusoidal（原始）

$$
\text{PE}_{(pos,\,2i)} = \sin\left(\frac{pos}{10000^{2i/d_{model}}}\right),\quad
\text{PE}_{(pos,\,2i+1)} = \cos\left(\frac{pos}{10000^{2i/d_{model}}}\right)
$$

不同维度对应不同频率的波：低维索引是高频、波长极短，高维索引近乎低频单调，整体构成一组从"逐位变化"到"整句量级"的多分辨率时钟。它的好处是无需学习参数、并且位置间存在线性关系（任意固定偏移 k 的 PE 可由 PE(pos) 线性变换得到），理论上可外推到训练时没见过的长度；实践中外推能力有限。

### RoPE（旋转位置编码，现代主流）

LLaMA、PaLM、Qwen、GLM 等采用。思路是在复数域里对 q、k 做一次角度为 pos·θ 的旋转：

$$
\langle f(q, m),\, f(k, n)\rangle = g(q,\,k,\, m-n)
$$

即**旋转后的内积只依赖相对位置 m-n**。因为它直接作用在 q/k 上而不是加在 embedding 上，理论上对长度外推更友好；配合 NTK-aware scaling、YaRN 等插值方法，可以把 4k/8k 训练出来的模型拉到 32k、128k 上下文。

### ALiBi

不改动 embedding，直接在 attention score 上加一个与距离成正比的偏置 `-k·|m-n|`（每个头斜率不同），近处的 token 天然更受关注。好处是推理时对任意长度都成立且实现极简，BLOOM、MPT 使用。

## Decoder 与自回归生成

训练时 decoder 一次性吃进整句：causal mask 保证位置 i 只能attend 到 ≤ i 的位置，于是一个 batch 里每个位置都能并行预测下一个 token（teacher forcing），这就是 Transformer 训练效率远超 RNN 的直接来源。

推理时是自回归的：逐个生成 token，每步都要重算包含历史全部 token 的前向。若不做优化，生成一个长度 n 的序列总代价是 O(n²)。

### KV Cache

观察：位置 i 的注意力只依赖当前 query 和所有历史位置的 K、V，而历史的 K/V 在生成过程中**永远不会变**。于是把它们缓存下来，每步只计算新 token 的 q/k/v 并与缓存拼接：

- 计算量：从 O(n² · d) 降到 O(n · d)（每步增量 O(n·d)）；
- 显存换时间：cache 显存量 ≈ `2（K、V）× layers × kv_heads × d_head × seq_len × batch × sizeof(dtype)`。
- 举例：一个 32 层、32 头、d_head=128 的 7B 模型，FP16 下每个 token 的 KV cache 约 0.5 MB；4096 上下文的单条请求约占 2 GB，已经接近模型权重本身的规模。

这条公式是理解 GPU 显存规划、最大并发 batch、以及 PagedAttention / continuous batching 等推理优化（vLLM 一类框架的核心）的起点。

### Prefill vs Decode

推理被天然切成两个阶段，性能瓶颈完全不同：

| 阶段 | 算什么 | 瓶颈 | 特点 |
|------|--------|------|------|
| Prefill | 并行算整个 prompt 的 K/V | 算力（compute-bound） | 大矩阵乘，GPU 利用率高 |
| Decode | 逐 token 生成 | 带宽（memory-bound） | 反复读取 KV cache 和权重，算术强度低 |

这也是为什么长 prompt 的首字延迟（TTFT）主要看算力，而生成速度主要看显存带宽与 batch 策略。

## 长上下文的代价与优化

Self-attention 的时间和空间都是 O(n²)，上下文从 4k 涨到 128k，注意力部分代价是 900 多倍（30²）。应对路线：

- **精确加速**：FlashAttention 用 IO-aware 的分块（tiling）把 Q/K/V 切成小块在 SRAM 里算完再回写，避免把 n×n 的注意力矩阵完整落地到 HBM，**显存占用降到 O(n) 且数学上与标准 attention 等价**（不牺牲精度）。FlashAttention-2/3 进一步优化并行与低精度（FP8）利用。这已经是训练和推理的默认算子。
- **近似注意力**：Longformer（滑窗 + 全局 token）、Reformer（LSH 分桶）、Performer（核方法线性化）、Linformer（低秩投影）等把复杂度降到线性或 O(n log n)，代价是精度损失与场景适配。
- **稀疏 / 压缩 KV**：只保留部分历史 KV（滑窗、重击者 token、token 合并），用检索的方式按需加载（见 [RAG](/docs/CS/AI/RAG.md) 的检索思路在 decode 阶段的变体）。

## 三种架构流派

| 流派 | 代表 | 预训练目标 | 擅长 | 现状 |
|------|------|-----------|------|------|
| Encoder-only | BERT、RoBERTa、Embedding 模型 | MLM 掩码预测 | 理解类：分类、NER、语义向量、rerank | 仍是检索/排序场景的主力，因双向编码+"一次前向"而高效 |
| Decoder-only | GPT 系列、LLaMA、Qwen、DeepSeek | 下一个 token 预测（CLM） | 生成类；规模上去后涌现 ICL/CoT | **现代 LLM 的绝对主流** |
| Encoder-decoder | T5、BART、原始 Transformer | 去噪 / 文本到文本 | 翻译、摘要等 seq2seq | 仍有专用价值，但通用模型已退潮 |

为什么 decoder-only 赢了：参数利用率高（一套参数同时做理解和生成）、训练目标与真实推理形态完全一致、cross-attention 的额外开销与并发/缓存复杂度被省掉，且规模定律在它身上验证得最好。

## 与现代 LLM 相关的几个运作细节

- **Tokenizer 先于模型**：BPE / WordPiece / SentencePiece 把文本切成子词，词表通常 3–15 万；中文通常一个字接近 1–2 个 token，这也是计费与上下文长度估算的口径（见 [NLP](/docs/CS/AI/NLP/NLP.md)）。
- **采样策略**：temperature 缩放 logits 控制分布陡峭度，top-p（核采样）/ top-k 截断长尾，beam search 适合翻译而容易让对话变啰嗦，repeat penalty 压制循环。
- **训练目标与对齐**：预训练 CLM → 指令微调（SFT）→ 偏好对齐（RLHF，或更简单的 DPO）。这套流水线解决的是"会续写"到"会听指令"的落差。
- **Scaling Law**：Chinchilla 给出的经验配比是每 1 参数约 20 个训练 token；超出数据配比的欠训练模型反而浪费算力。涌现能力（ICL、CoT）随之出现。
- **幻觉的结构性来源**：模型只学到了 token 分布而非事实数据库，"下一个 token 最可能是什么" 与 "什么是真的" 是两件事 —— [RAG](/docs/CS/AI/RAG.md) 正是从外部补上这一环。

## 现代 LLM 相对原始 Transformer 的改进清单

一句话总结：**原始 Transformer 的骨架没变，每个零件都被换过一轮。**

| 组件 | 原始（2017） | 现代主流 | 收益 |
|------|-------------|----------|------|
| 位置编码 | Sinusoidal 绝对编码，与 embedding 相加 | RoPE（少数 ALiBi） | 相对位置建模，长度外推友好 |
| 归一化 | Post-LN LayerNorm | Pre-LN + RMSNorm | 训练稳定、省计算 |
| FFN 激活 | ReLU | SwiGLU | 同参数下效果更好 |
| 注意力 | MHA（K/V 头数 = Q 头数） | GQA / MQA | KV cache 缩小数倍到数十倍，提升并发 |
| bias 项 | 各处 dense/attention 带 bias | 普遍去掉 | 减少冗余参数，提升稳定性 |
| FFN 结构 | 稠密 FFN | MoE 稀疏专家（Switch、DeepSeekMoE） | 参数量与算力解耦，同样推理成本下扩容量 |
| 注意力算子 | 朴素 `softmax(QK^T)V` | FlashAttention 系列 | 显存线性化、速度大幅提升 |

## Links

- [DL](/docs/CS/AI/DL/DL.md)
- [CNN](/docs/CS/AI/CNN.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)
- [DeepSeek](/docs/CS/AI/LLM/DeepSeek.md)

## References

1. [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
2. [The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/)
3. [The Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/)
4. [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)
5. [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864)
6. [Train Short, Test Long: Attention with Linear Biases Enables Input Length Extrapolation](https://arxiv.org/abs/2108.12409)
7. [Root Mean Square Layer Normalization](https://arxiv.org/abs/1910.07467)
8. [GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints](https://arxiv.org/abs/2305.13245)
9. [GLU Variants Improve Transformer](https://arxiv.org/abs/2002.05202)
10. [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)
11. [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)
12. [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)
13. [YaRN: Efficient Context Window Extension of Large Language Models](https://arxiv.org/abs/2309.00071)
