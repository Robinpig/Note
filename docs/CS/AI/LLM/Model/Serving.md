## Introduction

[Inference](/docs/CS/AI/LLM/Model/Inference.md) 回答"用哪个引擎、量化到什么精度"；本页回答更底层的问题：**这些引擎为什么快**。GPU 推理服务的一切设计都始于同一个事实——自回归生成分两个性质完全不同的阶段，而瓶颈资源各不相同：

| 阶段 | 做什么 | 瓶颈 | 用户感知 |
| :--- | :--- | :--- | :--- |
| prefill | 一次前向算完整个 prompt 的 KV | **算力**密集 | 首 token 延迟（TTFT） |
| decode | 每步生成一个 token，读全部历史 KV | **显存带宽**密集 | 生成速度（tokens/s） |

batch 越大，prefill 挤占的算力越多、decode 的步长越不齐；batch 越小，GPU 利用率越低。静态 batch（等一批全部生成完再换下一批）让短请求陪长请求空等，是这一切浪费的根源。下面四个机制——continuous batching、PagedAttention、prefix caching、以及把两者接起来的调度器——构成当代推理引擎的共同内核。

## Continuous Batching

Orca（OSDI'22）提出并从此成为行业标配的**迭代级调度**：每个 decode 步都可以插入新请求、移除已完成的请求，batch 在 token 粒度上动态重组。短请求生成 10 个 token 就离开，不再占着 batch 里的位置陪跑；长请求也不会因为"等最慢的同伴"而阻塞整批。

它的效果与 PagedAttention 是**相乘**而非相加：显存浪费降下来 → 同样显存塞得进更多并发请求 → 连续批处理有更多请求可调度 → GPU 利用率更贴近饱和。

## PagedAttention: The KV Cache Is Virtual Memory

传统分配给每个请求的 KV cache 是一段**连续**显存，且必须按最大长度预留——输出多长事前不知道，于是碎片与预留浪费长期在 60%~80%。vLLM 的观察是：KV 块本来就不需要物理连续，只需要一张**映射表**。

PagedAttention 的做法：KV cache 切成固定大小的块（默认 16 token/块），每个请求维护一张逻辑块 → 物理块的 block table，attention kernel 里通过块表间接寻址。浪费降到 4% 以下；附带收益是**块可以共享**——相同前缀的多个请求只存一份 KV。代价是 kernel 必须自己理解分页布局（FlashInfer 等后端即为此而生），这是 vLLM 最难复制的部分。这个"逻辑连续、物理分散、一张表映射"的思路，与操作系统解决堆碎片的做法同源。

## Prefix Caching: Where the Real Money Is

生产负载里 prompt 的前缀重复度远高于想象：系统提示、工具定义、RAG 检索到的同一文档、多轮对话的历史。这些 token 的 KV 完全一致，重复计算纯属浪费。

- **vLLM** 做**块级自动前缀缓存**：按块哈希（自 v0.11 起为 sha256）索引，命中即复用，未引用块 LRU 驱逐。两个细节：只缓存**整块**，不足一块的尾部前缀仍要重算；`cache salt` 可做多租户隔离。**V1 引擎默认开启**，且缓存零命中率的吞吐代价低于 1%——几乎没有理由关掉它。
- **SGLang** 用 **RadixAttention**：KV 组织成基数树，最长前缀匹配 + 缓存感知调度，前缀密集负载下优势更明显。公开基准（H100、Llama 3.1 8B、前缀密集）下吞吐约 16.2k vs vLLM 约 12.5k tok/s（+29%）；而 prompt 各不相同的负载下差距收窄到约 +4%（70B FP8、50 并发：1,920 vs 1,850 tok/s）。**前缀复用越多，RadixAttention 领先越大；没有前缀复用时它也在付缓存管理成本。**

两个引擎的缓存都只缩短 prefill，对 decode 毫无帮助——响应越长，缓存的相对收益越小。

## The V1 Scheduler: One Token Budget

vLLM V1 引擎（2025 年发布，相对 V0 提速 1.5~2 倍）最被低估的设计是把调度统一成**一道 token 预算分配题**：调度器眼里没有"这个请求在 prefill 还是在 decode"，只有"这一步给它多少 token"。chunked prefill（把长 prompt 切段与 decode 交替执行）、prefix caching、投机解码因此可以在同一框架内组合，而不是各写一条代码路径互相打架。

chunked prefill 的旋钮是 `max_num_batched_tokens`，它直接交易两个指标：**调小 → 每步塞的 prefill 少，生成更连贯（ITL 好）、TTFT 变差；调大 → 每步多算 prompt，TTFT 好、ITL 差**。官方口径是纯吞吐场景建议 8192 以上，交互式场景往 2048 收。

显存吃紧时 V1 会**抢占（preempt）请求并稍后重算**——重算的代价全压在 TTFT 上。排障顺序：先抬 `--gpu-memory-utilization`，再降 `--max-num-seqs` / `--max-num-batched-tokens`，最后才加张量并行。

## Prefill/Decode Disaggregation

既然两个阶段一个吃算力、一个吃带宽，就没有理由让它们抢同一批卡。DistServe 一类方案把 prefill 与 decode **分开部署**到不同实例、不同卡型，中间只传 KV。收益是两类集群各自跑在自己的最优点上，代价是 KV 传输的网络开销与部署复杂度——规模足够大时才划得来。

## Speculative Decoding

解码慢的根因是每步只出一个 token 却要读一遍全部权重。投机解码用小模型（或 EAGLE 类的轻量头）先猜 k 个 token，再用大模型一次前向**批量验证**：猜中就跳过 k 步，猜错才回退。典型收益 2~3 倍 decode 加速，代价是额外一份小模型显存与调度复杂度。它与 continuous batching、chunked prefill 在 V1 里可叠加。

## Engine Landscape

| 引擎 | 强项 | 弱点 |
| :--- | :--- | :--- |
| vLLM | 生态最大、模型覆盖最广、运维简单、V1 调度器 | 纯吞吐不是第一 |
| SGLang | 前缀密集 / Agent 负载、结构化输出（xgrammar） | 生态较小 |
| TensorRT-LLM | NVIDIA 卡上峰值（手工 kernel、FP8/FP4、in-flight batching） | 仅 NVIDIA、配置调试重、模型跟进看 NVIDIA 路线图 |
| llama.cpp / Ollama | 本地、CPU、Apple Silicon | 并发与服务化能力有限 |
| HF TGI | — | 2025-12 起进入维护模式，官方建议迁往 vLLM / SGLang |

选型结论因此不是"谁最快"，而是**最快是对于什么负载、什么硬件、什么运维约束**：前缀密集 + 结构化输出选 SGLang，NVIDIA 上压榨极限选 TensorRT-LLM，其余大多数情况 vLLM 是默认答案。

## Operational Notes

- **冷启动真实存在**：首次请求前编译 CUDA graph 与优化内核，大模型可加 30~90 秒——扩缩容与发布评估要把这段时间算进去。
- **V1 是 CPU 敏感的设计**：至少需要 2 + N 个核（API server、engine core、N 个 GPU worker），engine core 是忙循环。在超售的 K8s pod 里跑出"GPU 没满但吞吐上不去"，先查 CPU 限流，不要先疑模型。
- 缓存是**进程内**的：重启即清零，别把命中率当跨实例的持久指标看。

## Links

- [Inference：引擎选型与量化](/docs/CS/AI/LLM/Model/Inference.md)
- [Post-Training：微调与对齐](/docs/CS/AI/LLM/Model/Post_Training.md)
- [Model Overview：模型总览](/docs/CS/AI/LLM/Model/Overview.md)
- [Transformer：prefill / decode 的架构根因](/docs/CS/AI/Transformer.md)

## References

1. [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)
2. [SGLang: Efficient Execution of Structured Language Model Programs](https://arxiv.org/abs/2312.07104)
3. [DistServe: Disaggregating Prefill and Decoding for Goodput-optimized LLM Serving](https://arxiv.org/abs/2401.09670)
4. [Orca: A Distributed Serving System for Transformer-Based Generation Models（OSDI'22）](https://www.usenix.org/conference/osdi22/presentation/yu)
5. [vLLM Documentation](https://docs.vllm.ai/)
6. [SGLang Documentation](https://docs.sglang.ai/)
