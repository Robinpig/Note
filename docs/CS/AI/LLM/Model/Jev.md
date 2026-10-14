## Introduction

Jev 是 TypeSafe AI 在 2026 年推出的模型，官方给它的类别名是 **System One model**：输入是任意自然语言状态，输出是**类型化的判断 + 校准过的概率**，不生成文本。官方一句话定位是 *frontier-intelligence function call — unstructured state in, typed probabilistic decisions out*。

它要解决的坑非常具体：Agent Harness 里有大量「小而快」的判断——意图路由、模型分档、风险审核、结果核验——过去只有两条路，用大模型写 Prompt（慢、偶发格式不遵循）或自训一个 BERT 级分类器（快，但每个任务都要数据、训练、单独部署，且零迁移能力）。Jev 站在两者中间：**像 LLM 一样能零样本听懂任意指令，又像分类器一样把输出收敛到封闭集合并给出可用置信度**。

模型名取自经济学家 **William Stanley Jevons**（杰文斯），押的是**杰文斯悖论**：智能成本每下降一个数量级，会解锁多个数量级的新需求（见 [The Jevons Paradox Bet](/docs/CS/AI/LLM/Model/Jev.md?id=the-jevons-paradox-bet)）。

> [!WARNING]
>
> **本笔记的版本基线：2026-10-14 核实。** 线上模型为 `jev-1.13.0`（别名 `jev-latest`），官方「jaggedness」页最后核对日期 2026-10-02。三件事必须先说清楚，否则后面的数字容易被误用：
> ① TypeSafe **未公开 Jev 的架构、参数量、训练数据与 RLCD 实现细节，也不开放权重**（截至本文核实）；
> ② 所有「快多少、省多少」的性能数字都是**厂商自测口径**，官方自己在评测页承认了若干偏差方向；
> ③ 模型仍在快速迭代，定价与限额「可无通知变动」，官方文档原文是限额正在随 GPU 供给动态调整。

## The Decision Gap in an Agent Harness

Agent 的主力链路（写代码、答问、开单）由生成模型承担，但**围绕它的辅助判断**数量更多、每次只值几毫秒。三类典型：

- **路由**：一句话进来，分给哪个子 Agent / 哪个部门的工单池 / 哪一档参数的模型。
- **门控**：这一步输出有没有风险、这条引用是否被上下文支撑、这段检索结果是否相关。
- **度量**：严重程度、情绪强度、敏感级别这类有序等级打分。

这类任务的共同形状是：**输入是一段自由文本 + 一条判断标准，输出必须被代码直接消费**。现有两条路各自的失效点：

| 做法 | 好处 | 失效点 |
| :--- | :--- | :--- |
| 前沿 LLM + Prompt，强制输出 JSON | 零训练、当天上线 | 要准就得开 thinking，慢；长指令下偶发结构错误；**自报的置信度不可信**；账单主体在输出侧 |
| 自训小模型（微调 BERT 级） | 毫秒级、有 logits 可卡阈值 | 每个任务一份数据 + 训练流水线 + 独立部署；**零迁移**，换任务重练 |

Jev 的取舍是把「生成」整个砍掉来换另一半：**不写字符串，所以不可能写错结构；输出面收窄到三个原语，所以可以把概率训成可信的**。

## System One, System Two, and Three Software Architectures

类别名借自 Kahneman《思考，快与慢》：System 1 快速直觉，System 2 缓慢审慎。官方也顺带承认这个名字有历史包袱——"System 1 thinking" 通常暗示**易错**，而他们的立场恰恰是这一类模型可以被做得比替代方案更可靠。

⚠️ **不要和 LLM 社区的用法混起来**：在推理模型语境里，「系统 1 / 系统 2」常常指**关 thinking / 开 thinking** 的同一个模型。Jev 的区分不在这里，而在**输出契约**——它根本不生成文本。

官方文档对定位有一句话划界很关键：**System One 是用来构建 AI-powered software 的，不是用来做 agent 的**——它不生成代码，也不自己选下一步。文档给出的三架构对照：

| 架构 | 控制流在谁手里 | 特征 |
| :--- | :--- | :--- |
| 传统软件 | 代码 | 由可靠简单原语堆出的决策树，可审计 |
| LLM Agent | 模型（每轮自选下一步） | 人在旁边看时好用，但**每个循环都是一次跑偏机会** |
| AI-powered software | **代码** | 代码做确定性工作与副作用，模型只出现在需要「可编程常识」的判断点上，每个判断保持原子且受约束 |

这也是它和 Agent 层最实际的接口：**决策模型是 Harness 的补偿件之一**——把原本要靠「再调一次大模型 + 解析它的输出」实现的微决策，换成一次带概率的类型化调用。

## Three Primitives: Choice, Score, and Noul

Jev 的提问面只有三种，都是「一个问题 = 一次原子判断」：

| 原语 | 问什么 | 返回 | 典型场景 |
| :--- | :--- | :--- | :--- |
| `Choice` | 这几个选项里选哪个 | `choice`、`probabilities`（每个选项）、`confidence` | 意图路由、文档分类、语言识别、部门分派 |
| `Score` | 落在哪个等级 | `score`、`legend`（等级标签）、`probabilities`、`confidence` | 严重度分级、敏感度评估、情绪强度 |
| `Noul` | 这句话是真的吗 | `noul`（0~1，「是」的概率） | 是否合规、是否请求退款、是否含紧急信号 |

三条最容易被忽略的接口事实：

- **一次请求可以混着问**。同一个 `state`、多个问题，**并行且互相独立**评估；官方文档明确「加问题几乎不增加响应时间」，且不会因为问得多而互相污染上下文（这是 LLM 串行做不到的）。
- **`Choice` 最多 255 个选项**，官方建议直接把完整清单（全部团队 / 全部品类）给它，而不是先做个 shortlist——加选项每个只花几个 token。清单可能不全时，**显式加一个 `other` / `none of the above` 选项**。
- **问题的 ID 不送进模型**，只是给代码取结果用的键。别指望 ID 本身当提示，完整问题必须写在 `instructions` 里。

请求与响应（官方文档最小例 + 中文分诊例的骨架）：

```json
{
  "state": "Help! My payouts have been failing for 3 days.",
  "model": "jev-latest",
  "questions": {
    "is_urgent": {
      "type": "noul",
      "instructions": "Does this convey urgency?",
      "criteria": {
        "true": "Explicitly time-sensitive",
        "false": "No urgency expressed"
      }
    }
  }
}
```

```json
{
  "model": "jev-latest",
  "answers": {
    "department":    { "type": "choice", "choice": "外科", "probabilities": { "外科": 0.97, "皮肤科": 0.03 }, "confidence": 0.96 },
    "is_emergency":  { "type": "noul",   "noul": 0.95 },
    "severity":      { "type": "score",  "score": 1.95, "legend": { "0": "轻微", "1": "中等", "2": "严重" }, "probabilities": { "1": 0.05, "2": 0.95 }, "confidence": 0.93 }
  }
}
```

（第二段是中文实测响应的骨架，**零概率项已省略**：入参把「右下腹剧痛 + 发热恶心」的症状描述同时问成分科室的 `choice`、是否紧急的 `noul`、严重度的 `score`，一次调用拿回三个带置信度的判断。）

`state` 侧同样接受结构：字符串、JSON 对象或文本数组都可以。官方推荐**用反引号包住路径**把问题钉到具体字段上（如 `` `support.tickets[0].message` ``），`instructions` / `criteria` 本身也能写成对象，把「问题」和「问题要引用的数据」分字段放，方便代码换数据不换问题。

## Calibrated Probabilities and Confidence

这一节是 Jev 与普通 LLM 结构化输出真正的分水岭，**必须把「概率」和「置信度」分开理解**：

- **`probabilities`**：整个输出集合上的分布（每个选项 / 每个等级一份）。
- **`confidence`**：把分布的**形状**压成一个 0~1 的数——分布越尖越高，越平越低。全压在一个结果上是 1，完全均匀是 0。
- **`Noul` 没有 `confidence` 字段**——它的概率本身就是答案；想要同一尺度可自己算 `|2p - 1|`（p 为「是」的概率，0.5 处为 0、0 与 1 处为 1）。

官方给的公式（Choice 与 Score 不同，因为等级是有序的）：

```tex
\text{confidence}_{\text{choice}} = \frac{p_{\max} - \frac{1}{n}}{1 - \frac{1}{n}}
```

```tex
\text{confidence}_{\text{score}} = \max\!\left(0,\ 1 - \frac{\sum_i p_i \lvert i - m \rvert}{\text{MAD}_{\text{unif}}}\right),\qquad \text{MAD}_{\text{unif}} = \frac{1}{n}\sum_i \left\lvert i - \frac{n-1}{2} \right\rvert
```

Choice 只看最高概率离均匀分布多远（所以 `(0.6,0.3,0.1)` 与 `(0.6,0.2,0.2)` 的 confidence 都是 0.4）；Score 还会看**剩余概率离最可能等级多远**——三等级下 `(0,0.5,0.5)` 得 0.25（纠结在相邻两档），`(0.5,0,0.5)` 得 0（纠结在两端）。官方同时提醒：`confidence` 只是「一种合理的分布摘要」，`top probability` 与 `top-to-second ratio` 这两个更朴素的量在实践中同样好用，而且答案里带着完整分布，自己算任何统计量都可以。

**校准（calibrated）**说的是群体性质：被判为 0.2 的预测里约 20% 真为真，0.8 的约 80%。**它不保证任何单条答案正确**——所以工程含义不是「信这条」，而是「这个阈值可以长期用」。这正是 `if prob > 0.9` 这种写法第一次具备统计意义的前提。

配套的用法是**把置信度当第二根轴**：答案告诉你「是什么」，置信度告诉你「要不要动」。官方给的三段式：高置信直接执行，中置信加确认 / 打标复核，低置信转人工或转更贵的推理模型。并且强调**阈值要按动作的风险分别设**——看错余额页可以恢复，放错一笔提现不行。

## RLCD: The Third Post-Training Path

官方的说法是，**决策模型要单独的第三条后训练路线**：

| 路线 | 优化目标 | 代价与失效 |
| :--- | :--- | :--- |
| RLHF | 人类偏好的回复 | 标注与 reward model 成本高；**奖励谄媚与「听起来很确定」**；造成 **mode dropping**（偏好某风格，压低其它可能输出），使概率系统性失真 |
| RLVR | 可程序化验证的对错（数学、代码） | 准，但只适用于有标准答案的场景，慢且贵，且**不量化不确定性** |
| RLCD（Reinforcement Learning for Calibrated Decisions） | **带校准概率的判断** | 实现细节未公开 |

另一处结构差异是**采样方式**：自回归逐 token 生成换成**并行采样**——一次查询直接给出整个输出分布，这是「毫秒级 + 输出免费」在成本上成立的原因。类型安全也不是「提示词约束得好」，官方说法是**输出被 schema 约束，类型错误在构造上不可能**——所以他们能把自己那条幻觉/类型错误率写成 0%，同时承认这个数字**不是经验测出来的，是构造保证**。

> [!NOTE]
>
> RLHF 这条路线与 TypeSafe 有直接渊源：官方文档写明 RLHF 由 **Diogo Almeida**（TypeSafe 联合创始人兼 CEO）参与共同发明，他在 OpenAI 期间参与 InstructGPT、ChatGPT、GPT-4 相关工作。这篇笔记的叙事因此带有明显的「内部人反水」色彩——**「LLM 的概率不可信」既是技术论断，也是商业定位**，读时按此打折。

## Numbers: Latency, Price, and Limits

| 项 | Jev（`jev-1.13.0`，2026-10-14） | 前沿 LLM 参照 |
| :--- | :--- | :--- |
| 输入价格 | **$42 / Btok = $0.042 / MTok** | $0.20 ~ $10 / MTok |
| 输出价格 | **免费**（官方语：too cheap to meter） | 约为输入的 5 倍 |
| 端到端延迟 | **70 ms ~ 500 ms**，官方称多数约 100 ms | 3 s ~ 329 s |
| 官方宣称倍数 | 同档 System One 任务下 **40x ~ 200x** 更快；首页挂 **193.6x faster / 444.6x cheaper** | — |
| 上下文 | 单请求 64K token；其中 **`state` + 最长单问 32K** | — |
| 限流 | 100K token/s、80 req/s，超则 429 + `retry-after`；**官方声明限额随 GPU 供给动态调整** | — |
| 输入模态 | **仅文本**（字符串 / JSON 对象 / 文本数组），无图像、音频、视频 | — |
| 语言 | **英文为主、当前最准**；含 CJK 的其它语言「能处理但没那么好」，官方要求非英文负载先自测 | — |
| 定制 | **不做客户数据微调、不做 LoRA**，所有账号同一份权重；靠 `state` + `instructions` + 拆问题塑形 | — |
| 数据 | 不用客户请求 / 响应训练；企业版提供零数据留存（ZDR） | — |

模型名的坑：**别名 `jev-latest` / `jev-preview` 会随新版本漂移**，响应的 `model` 字段回的是真实版本 ID。**如果阈值是对着某个版本调出来的，就 pin 版本 ID**，别用别名上线。

评测口径要一起记：官方的 workflow 评测**取 GPT-6 Astra 与 Fable 5.1 的平均作为参考答案**（等于偏向 OpenAI/Anthropic 自己），LLM 基线套了自家「System One LLM wrapper」强制结构化输出（他们承认这样更慢更贵），工作流由本团队能力组编写（承认存在选择偏差），计时是在美西笔记本上跑的。官方把这些写进了 nuance——**这类自我披露本身值得学，但也意味着 40x ~ 200x 是「自家评测里的上界」而不是可复现基准**。

第三方口径可以拿来对冲：**JevBench**（Benchmark Heaven 出品，2026-09-19 建仓，测类型化判断的准确率、校准、延迟与成本）、Cloudflare 的 **Jev Decision Index**、以及 **JevServe-bench**（2026-10-02，专门测「决策模型替 serving 系统做决定」做得好不好——路由、缓存、调度、验证、护栏、工具调用六类任务，打分是从系统默认值的 0 分到先知 oracle 的 100 分，且每个分数带 95% 区间）已经公开了排行榜；斯坦福与 Nvidia 的研究者报告他们开源的 **CLM-8B** 在部分任务上比 Jev 快至多九倍，代价是工具调用准确率更低——**注意这是他们自己的工作负载与部署配置下的结论**，恰好也是「开源小决策模型能不能自建」这个问题的第一个公开数据点。

**同一个 Jev 的延迟，三把尺子量出三个数**，这一组对比比任何单一数字都更该记住：

| 测量方 | 口径 | Jev 延迟 |
| :--- | :--- | :--- |
| TypeSafe 官方 | 自家评测、美西笔记本计时 | 端到端 **70 ~ 500 ms**，文档称多数约 100 ms |
| Cloudflare（Jev Decision Index） | 43 项评测的中间值 | **中位 524.1 ms / p95 536 ms**（Clef 209.3、Clef-flash 38.8、Laya 5.8） |
| Laya README 对拍表 | 单问 p50，走 API | **236 ~ 276 ms**（其自托管编码器 32.8 ms） |

差别来自任务复杂度、是否含公网往返、以及各家 wrapper 的实现——**引用延迟数字时必须连测量方与负载一起写**。这也再次说明官方那句「比前沿 LLM 快 40~200 倍」是相对它自己选定的工作流而言的，不是可搬运的物理常数。

## Engineering Practice: How to Use It Well

官方 How-to-build 的方法论，浓缩成可执行清单：

1. **能用代码就别用模型**。日期比较、阈值判断、算数，代码永远更准更快；问自己「这个 count 为什么要过模型」。
2. **拆原子问题**（官方称这是全文最重要的一条）。别问「这封邮件是垃圾邮件吗」，而是拆成「是否在索要密码 / 是否承诺额外奖励 / 发件人身份与内容是否矛盾」，**判断交模型，综合与加权交代码**。权重变了改系数，不用重写提示词。
3. **精简 `state`**。只放当前这题需要的上下文，无关内容会稀释注意力——官方直接用了 **context rot** 这个词；检索与过滤先在代码里做，必要时用一个 `Noul` 先判相关性。
4. **结构化 `instructions` 与 `criteria`**。每个选项写清「属于什么 / 不属于什么 / 几个例子」，各选项用同一组字段名，让模型能逐项对比。
5. **一次多问**。同一 `state` 下的意图、情绪、风险全打包进一个请求（speculative fan-out），事后代码挑要用的——加问几乎不加延迟。
6. **组合输出**：确定性规则、加权和，或者**把概率当特征喂给下游经典机器学习模型**（官方 AutoResearch cookbook 就是拿 Jev 输出训一个 CatBoost 回归器）。
7. **按不确定性路由**：把 confidence 与准确率画在同一张图上定阈值，低置信转人工或转推理模型（级联见 patterns 与 SDE cascade cookbook）。

四个官方 pattern 对应四类落点：`Speculative fan-out`（一次问完）、`Confidence-gated routing`（三段式处置）、`Composite scoring`（原子分 + 代码权重）、`Intent routing`（分派给确定性逻辑 / 专家 LLM / 人工）。

cookbook 里两个带数字的结论最可复用作参照：

- **并行问答确实免费**：13 个监管问题塞进一个请求，比逐个调用**便宜 12.2 倍、快 10.0 倍，且答案不变**。
- **它能当廉价重排器**：40 条 CLERC 法律检索、BM25 取 30 段短名单，逐候选问一次，top-1 从 5% 提到 18%、top-5 从 15% 到 35%、top-10 从 38% 到 62%。

代码形态（Python SDK）示意一下门槛有多低——数「列表里有几个是水果」，官方给的做法就是**每个元素问一次 `Noul`，代码来加**：

```python
from typesafe_sdk import Noul, TypeSafeClient

client = TypeSafeClient(model="jev-1.13")
YES = 0.5  # 阈值由业务自己定
result = client.system_one(
    {"items": items},
    {f"item_{i}": Noul(instructions=f"Is `items[{i}]` the name of a fruit?") for i in range(len(items))},
)
count = sum(result.nouls[f"item_{i}"].noul > YES for i in range(len(items)))
```

## Where It Does Not Work

官方的 jaggedness 页把失效模式列成九条，这份清单比卖点更有工程价值：

| # | 失效模式 | 替代做法 |
| :--- | :--- | :--- |
| 1 | **字面理解**：答你写出来的问题，不是你想问的；否定词、限定词按字面读 | 把条件写死，边界样本进 `criteria`；发现要解释「我其实意思是…」时，那段解释就是缺的那半个指令 |
| 2 | 数学与数字 | 算术留在代码里 |
| 3 | **计数不可靠**（字符数、词频、长列表条数），且误差随规模增长 | 逐条问 + 代码累加 |
| 4 | 日期与时间比较：把日期当文本读，不当有序量 | 抽取（判断题）给模型，排序 / 差值 / 归属给代码 |
| 5 | 间接性与双重否定、多跳 | 指令直写，点名 `state` 里相关字段 |
| 6 | `state` 大而杂 → context rot | 先过滤再发 |
| 7 | **对抗性内容**：`state` 是数据，模型不默认当它敌意；注入文案可以撬动答案 | 判据写明确 + 上线前专门测对抗样本 |
| 8 | `instructions` 与 `criteria` 互相矛盾；`Noul` 里 true/false 反着映射会掉准 | 把 `criteria` 当指令的延伸来对齐 |
| 9 | **选项顺序有偏**：会偏向排在前面那个；换序检查答案是否稳 | 打乱选项重问一次 |

三条**结构层面的**限制，不属于「调一调就好」：

- **不保证结构不变性**：同一判断用 `noul` 问和用 `choice` 问，结果可能不完全一致。官方文档只承诺**同一问法反复问答案稳定**（self-consistency），没承诺**换问法等价**——中文那篇实测笔记把这条单独拎出来提醒过。别假设换了表达形状，输出还是同一个数。
- **`score` 的插值不是精确数值**：`score 1.95` 只该用来卡阈值，不能用来反解「到底多大」。等级间的数值标定本身就弱。
- **不能拿来生成，也不给解释**：链 `Choice` 硬凑文本很慢且效果差，正确姿势是正则或生成模型先给候选、让 Jev 从候选里挑。另外它对每个判断**不返回书面理由**——需要「为什么」的场景要么另接生成模型，要么靠拆出来的多个原子判断反推。

## Selection: LLM, BERT, and Decision Model

把三方拉平到同一张表上（BERT 列按「自训小模型」这条路线读）：

| 维度 | 自训 BERT 级分类器 | 前沿 LLM 的结构化输出 | Jev 这类决策模型 |
| :--- | :--- | :--- | :--- |
| 换新任务 | 重标数据 + 重训 + 重部署 | 改提示词 | 改 `instructions` / `criteria` |
| 零样本理解自由文本 | ✗ | ✅ | ✅ |
| 输出可被代码直接消费 | ✅ | ⚠️ 需解析 + 校验，偶发格式错 | ✅（schema 构造保证） |
| 概率可用做阈值 | ✅ logits，但需自校准 | ⚠️ RLHF 后系统性过度自信 | ✅ 校准是训练目标 |
| 延迟 | 毫秒级 | 秒到几十秒（开 thinking 更久） | 70~500 ms |
| 输出侧计费 | 自建 GPU | 输出约为输入 5 倍价 | 输出免费 |
| 生成 / 解释 / 多跳推理 | ✗ | ✅ | ✗ |
| 私有化 / 离线 | ✅ | ⚠️ 开权重模型可自建 | ✗ Jev 本身只有 API、权重不开；但**同接口的开权重实现已可自建**（Laya / Clef / Strands Decider 2B），见 [The Interface Won](/docs/CS/AI/LLM/Model/Jev.md?id=the-interface-won-jev-compatible-decision-models) |
| 迁移与泛化 | ✗ 单任务 | ✅ | ✅ 但**只覆盖判断形状的任务** |

一句话判据：**答案空间封闭 + 代码是消费者 + 要概率可卡阈值** → 决策模型；**要生成、要解释、要多跳** → 生成模型；**任务极窄、量极大、必须私有化或延迟要求变态** → 仍然自训小模型。中间地带还有官方的 SDE cascade（mini → verify → reasoning 三段级联），本质是「先用便宜的判断层把贵的推理层省掉」。

## The Jevons Paradox Bet

命名不是彩蛋，是**定价策略的宣示**。Jevons 在 1866 年《The Coal Question》里的观察是：瓦特的分离冷凝器大幅降低了蒸汽机的单位功耗煤，但英国的煤耗不降反升——因为煤从此能用在过去根本不划算的场景上。**提高资源利用效率，反而提高资源总消耗**，这就是杰文斯悖论 / 回弹效应（rebound effect）。

TypeSafe 的原文表述有两句，一句在发布公告，一句在工程文档里：

- 「我们预期机器智能会重演煤炭的路径：**智能成本每下降一个数量级，就解锁数量级更多的用例**。」
- 架构目标的原文是**「大于 100 倍的智能—速度—成本比」**，底注是「更便宜的智能会创造多得多的需求」。

再叠加他们那份宣言式的判断——**大规模 AI 自动化最终会是约 99% 的机器对机器交互、1% 的人机交互**（所以设计目标不该是「读起来舒服」，而是「在软件里行为可预测」），整套叙事就闭合了。

这套叙事在 2026 年的落点是自洽的：如果一次判断的成本掉到 $0.042/MTok 且输出免费，那么原本「不值得为这一步单独调模型」的微决策全部变得可行——每个工单、每句话、每个候选段落、每次工具返回都可以问一遍。**判断的单价塌下去，判断的次数爆炸**，总账单与总算力需求反而上升。官方的 cookbook 恰好是这个回弹的现场证据：一次问 13 题比串行便宜 12.2 倍，于是没人会只问一题。

**接下来发生的事，比任何评论都更像对这条叙事的检验**：Jev 发布四周内，Cloudflare 把托管的 Clef-flash 从 $0.09 一路降到 **$0.038/MTok——刻意低于 Jev**，OpenAI 的 Decisions API 定在 $0.10，AWS 直接开源一个 2B 让你自建。判断的单价在被继续往下打，而每一家降价的理由都是「用量会更大」。**这正是杰文斯悖论的双向读法**：厂商用它解释自己为什么敢把输出定价为零，而竞争格局用它解释了为什么三个月内出现了四个可互换的实现。至于回弹到底发生多少，目前只有间接证据——TypeSafe 自己在文档里写「限额随 GPU 供给动态调整、我们正在承接非常大的需求量」，即**需求确实把供给顶住了**。

⚠️ 但要把话说清楚：**悖论是厂商的叙事，不是被验证的结论**。回弹效应的实证幅度在能源与算力上一直有争议，判断「效率提升是否真的增加了总消耗」需要区分单位效率、总需求与弹性三个量（AI 场景下的系统讨论见 References 里的 arXiv 综述）。对本库更有用的读法在 [Overview](/docs/CS/AI/LLM/Model/Overview.md) 那一侧：**定价结构里真正决定账单的是缓存、思考 token 与台阶加价，成本下降从来不会自动等于总成本下降**——杰文斯悖论给的是这件事的一个具体版本。

## Ecosystem and Adoption

公司背景先交代一句：TypeSafe AI 2024 年在旧金山成立，创始人是 **Diogo Almeida**（CEO，前 OpenAI，参与过 RLHF 与 InstructGPT / ChatGPT / GPT-4 的工作）、Erik Gafni、Sasha Sheng；两年隐身期后带着 Jev 出关。

一条时间线（2026 年，公开报道口径）：

| 时间 | 事件 |
| :--- | :--- |
| 09-15 | TypeSafe 结束两年隐身发布 Jev，同步 $40M 种子轮（DCVC 领投），early access |
| 09-18 ~ 09-20 | Vercel 称 Jev 是 AI Gateway **史上被采纳最快的模型**：上线 24 小时内近 **13% 的付费团队**接入，超过以往任何一次模型发布同期覆盖的两倍；三天内 Cloudflare、LangChain（`TypeSafeClassifier`）、Langfuse 完成接入 |
| 09-18 | 开源同类 **Laya** 建仓（`NandhaKishorM/laya`，Apache 2.0，编码器 421M / 322M，四周内 3.2 万 star） |
| 09-19 | 第三方决策模型基准 **JevBench** 建仓（Benchmark Heaven 出品，测类型化判断的准确率、校准、延迟与成本） |
| 09-21 前后 | 中文媒体报道「爆火一周后正式全面开放」 |
| 09-25 | OpenRouter 上架 `typesafe/jev-router` 条目 |
| 10-01 | AWS 开源 **Strands Decider 2B**（Apache 2.0，自托管）；同日 Cloudflare 发布 **Clef / Clef-flash**（Apache 2.0 开权重 + Workers AI 托管，自称「完全 Jev-API 兼容」）与**决策模型 RL 微调平台**——事后披露的时间线是「周五晚决定、周末训练、周四上线」 |
| 10-06 | OpenAI 推出 **Decisions API**：首版直接跑 GPT-6 Luna 不做额外训练，输入 $0.10/MTok、输出免费；**接受图像输入**（Jev 仅文本）。OpenAI 的 Nikunj Handa 公开承认是 Jev「激发了这一切」，且该 API 四周前还不在路线图上 |
| 10-09 | TypeSafe 宣布 **$870M Series A**（a16z 领投，Sequoia 与 DCVC 参与，估值 $7.5B，a16z 的 Martin Casado 进董事会），距发布 24 天；同日 Cloudflare 发 **Clef-omni**（音频 / 视频 / 图像 / 文本），**把 Clef-flash 降到 $0.038/MTok 以低于 Jev**，并把托管版 flash 的上下文从 64k 砍到 24k |
| 10-13 | 阿里云 AgentCore 公众号发布《深度解析 Jev 模型》中文长文（本笔记的主要中文来源） |

需要打折的地方有四处。**其一**，「三分之一财富 500 强在用 Jev」是公司口径（约 167 家），领投方同一天的帖子写的是 25%（约 125 家，且措辞是「已完成集成」），**两边都没解释差异**——采用率类数字一律按营销读。**其二**，竞品跟进（OpenAI / AWS / Cloudflare）是这条路线成立的最强旁证，但也意味着**「决策模型」不是独家护城河**：Cloudflare 自己披露的节奏是「周五晚决定、周末训练、周四上线」。**其三**，排行榜本身要看口径，AWS 发布对比图时引用了公开的 JevBench 结果，却把 Jev 与自己即将发布的 checkpoint 一起略去——**看这类图先查它缺了谁**。**其四**，中文圈流传的 **jevai.net 是社区站而非官方站**（自述「与 TypeSafe AI、Cloudflare 无隶属或背书关系」，页面同时推荐第三方转售通道 DefAPI 的半价额度）。它的三篇对比文章把 Jev / Laya / Clef 摆进同一张表，作为**线索**很有用，但三处口径要纠正：它写 Jev 输入价 $0.084/MTok，而官方文档当前是 **$0.042/MTok**（要么是早期定价、要么是笔误，以 docs 为准）；它说「公开资料未列明 DPA 与数据保留」，而官方 `/legal` 页其实列了 DPA、Privacy Policy 与企业级 ZDR（SOC 2 / ISO / on-prem 确实未见）；它对 Clef 与 Laya 的定性描述与两家的一手发布基本一致，可以引用。**结论：二手站只用来找线索，任何数字都回一手核对。**

中文生态里最实用的两份材料在阿里云开源的《Alibaba Cloud AI Agent Handbook》里：一篇是上面那篇 Jev 深度解析（含中文分诊实测），另一篇是 `HiRoute：Jev 模型智能路由实践`——把长程 Agent 任务里的「整理资料 / 设计方案 / 实现代码 / 核验结果」按阶段路由到不同档位模型，这正好是本文第 [Engineering Practice](/docs/CS/AI/LLM/Model/Jev.md?id=engineering-practice-how-to-use-it-well) 节那条判据的落地样本。

## The Interface Won: Jev-Compatible Decision Models

Jev 真正的行业影响不是模型本身，而是 **`POST /v1/systemone` 这套接口形状在四周内变成了事实标准**——多家实现直接宣称「Jev API 兼容」，连原语名 `choice` / `score` / `noul` 都被照抄。但兼容只到 wire protocol 为止，**语义差别恰好落在决定阈值的地方**，这是选型最容易翻车的位置。

| 实现 | 许可与底座 | 接口与语义差异（相对 Jev） |
| :--- | :--- | :--- |
| **Cloudflare Clef / Clef-flash / Clef-omni**（10-01、10-09） | **Apache 2.0 开权重** + Workers AI 托管；冻结 Qwen3.8-27B（flash 用 Qwen3.5-9B、omni 用 Qwen3-Omni-30B-A3B MoE）加 rank-256 LoRA，配两阶段注意力路由与 lexical prior，后训练用 label-smoothed CE + Brier 校准 | 同一请求体与 answers / usage 结构；**带视觉编码器**（omni 连音频与视频帧一起吃）、官方称上下文 64k；定价 Clef $0.24、flash 从 $0.09 降到 **$0.038/MTok（低于 Jev）**、omni $0.15；降价的代价是 **flash 托管上下文从 64k 砍到 24k**（权重自托管可跑到 256k）；Cloudflare 同时上线**决策模型 RL 微调平台**（AI Gateway 沉淀数据集 → Workers AI 跑 rollout → Containers 打分 → Trainer → BYO Model 部署回去） |
| **Laya**（09-18 建仓，四周 3.2 万 star） | **Apache 2.0**，三个 ModernBERT-large 421M / mmBERT-base 322M 编码器 + 一个 typed-decisions 微调版，`Router` 按语言与任务分派；单次前向 T4 32.8 ms、批量 7.2 ms/问 | `laya-serve` 直接暴露 `/v1/systemone` 与 `/v1/systemone/batch`（≤64 state），另加 `lang` / `min_confidence` / `max_len` / `head_max_len`；但 **`confidence` 是 1 减归一化熵，不是 Jev 的 `(n·p_max − 1)/(n − 1)`**，其 README 原话是「A threshold carried over from Jev does not transfer」；选项共享 192 / 256 token 预算，**不是 Jev 的 255 选项上限** |
| **AWS Strands Decider 2B**（10-01） | **Apache 2.0 开权重**，自托管 | 发布对比图引用了公开的 JevBench 结果，但把 Jev 与自己待发布的 checkpoint 一起略去 |
| **OpenAI Decisions API**（10-06） | 托管，首版直接跑 GPT-6 Luna 不加训练 | **接受图像**（Jev 仅文本），输入 $0.10/MTok、输出同样免费 |

一句提醒：Cloudflare 拿「64k vs Jev 的 32k」做对比时，取的是 Jev 的 **`state` + 最长单问**预算；官方口径其实是单请求 64K、其中 state + 最长单问 32K。**两家说的不是同一个数**，这类跨厂商对比要先对齐定义。

三条可以直接抄进设计文档的结论：

1. **换后端不等于换 base URL**。`confidence` 在不同实现里是不同的函数，**迁移必须用边界样本重标阈值**，别假设 0.8 还是 0.8。
2. **开源侧的诚实代价值得读**。Laya 的 README 明确写：base checkpoint 在 typed-decisions 上零样本只有 0.362 / 0.352，**低于 0.461 的多数类基线**，要拿到 0.766 得自己微调并拟合温度，且 `noul` 有标签敏感性、`score` 有位置偏置。自托管换来的是控制权与一份模型工程工作，不是白拿的精度。
3. **高基数选项目前仍是 Jev 的结构性优势**（选项预算与 255 上限的差异），而**多模态与可微调是它的结构性短板**——正好是 Clef 与 RL 微调平台切进去的两个口子。

## Links

- [Overview](/docs/CS/AI/LLM/Model/Overview.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Reinforcement Learning](/docs/CS/AI/ML/ReinforcementLearning.md)
- [Economics](/docs/Economics/Economics.md)

## References

- [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [TypeSafe Docs: Introduction](https://docs.typesafe.ai/introduction)
- [TypeSafe Docs: Models and pricing](https://docs.typesafe.ai/models)
- [TypeSafe Docs: Primitives, Choice, Score, Noul](https://docs.typesafe.ai/primitives)
- [TypeSafe Docs: Confidence](https://docs.typesafe.ai/confidence)
- [TypeSafe Docs: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- [TypeSafe Docs: AI primer (RLHF / RLVR / RLCD)](https://docs.typesafe.ai/introduction/machine-learning-primer)
- [TypeSafe Docs: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- [TypeSafe Docs: Patterns](https://docs.typesafe.ai/patterns)
- [TypeSafe Docs: Parallel questions cookbook](https://docs.typesafe.ai/cookbooks/parallel_questions)
- [TypeSafe Manifesto](https://typesafe.ai/manifesto)
- [深度解析 Jev 模型：如何快速做结构化决策](https://mp.weixin.qq.com/s/OLWHlE9HAiZKFrz2WgjWcA)
- [Alibaba Cloud AI Agent Handbook](https://github.com/aliyun/ai-agent-handbook)
- [TypeSafe AI Raises $870 Million for Jev as OpenAI, Amazon and Cloudflare Ship Rivals](https://www.implicator.ai/typesafe-ai-raises-870-million-for-jev-as-openai-amazon-and-cloudflare-ship-rivals/)
- [AI 决策模型 Jev 硅谷爆火，OpenAI 三周后紧急推出竞品](https://news.qq.com/rain/a/20261009A04GAO00)
- [TypeSafe's Jev hits 13% of Vercel paid teams in 24 hours](https://aiweekly.co/alerts/typesafes-jev-hits-13-of-vercel-paid-teams-in-24-hours)
- [JevBench: Benchmark for AI Decision Models](https://github.com/fstandhartinger/jevbench)
- [JevServe-bench Leaderboard](https://supercomputing-system-ai-lab.github.io/jevserve-bench/)
- [Introducing Clef: our open-source decision models, and new RL fine-tuning platform](https://blog.cloudflare.com/clef-decision-models/)
- [Introducing Clef-omni with full multimodality, plus a faster Clef and a cheaper Clef-flash](https://blog.cloudflare.com/clef-faster-cheaper-multimodal/)
- [Laya: non-autoregressive System 1 decision engine](https://github.com/NandhaKishorM/laya)
- [Jev AI 文章（社区站，含 Jev 入门 / Jev vs Laya / Clef vs Jev）](https://jevai.net/zh-cn/articles/)
- [From Efficiency Gains to Rebound Effects: The Problem of Jevons Paradox in AI](https://arxiv.org/abs/2501.16548)
