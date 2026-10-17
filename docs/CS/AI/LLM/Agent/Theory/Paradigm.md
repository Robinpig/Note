## Introduction

[Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 给出了 Agent 的最小定义——**一个能调用工具的循环系统**，以及四组件（Loop / Tools / Memory / Harness）。但"循环"只描述了骨架，没有回答下一个问题：**循环里的"思考"与"行动"到底有几种组织方式**。同样的四步（Reason → Act → Observe → 回环），可以每走一步重新决策，也可以先画好蓝图再施工，还可以干完之后再回头批判自己。这三种答案就是本文的三个主角：

- **ReAct**：推理与行动交错，走一步看一步，动态纠错；
- **Plan-and-Solve**：先全局规划、后严格执行，三思而后行；
- **Reflection**：执行之后再接一层"自我评审 → 修订"的事后迭代。

它们不是互斥选项，成熟系统常把两三种组合使用。本文按「机制 → 代价 → 选型」展开每一种，最后给一个 **TypeScript 的最小 Agent Loop 完整实现**——不到 150 行、零第三方依赖，把"一个 Agent 到底由什么构成"亲手写一遍。

为什么值得手写而不直接上框架？LangChain、LangGraph 这类框架把输出解析、重试、防死循环都封装好了，直接用很省事，但也意味着**这些坑你一个都不会见到**。而它们恰恰是理解 Agent 工程的入口：协议有多脆弱、循环怎么收敛、上下文怎么回灌——写一遍最小实现，再看框架的抽象 layer 在哪一层，收益比读十篇架构图大。

## The Same Loop, Three Organizations

三篇范式论文（ReAct 2022、Plan-and-Solve 2023、Reflexion 2023）面对的是同一个事实：**LLM 单次生成不可靠**——会幻觉、会算错、会在长链条上偏离轨道。区别只在于把不可靠性放在哪里消化：

| 范式 | 思考与行动的关系 | 不可靠性在哪一步被处理 | 一句话形象 |
| :--- | :--- | :--- | :--- |
| ReAct | 每一步都是 Thought → Action → Observation | 每一步之后，用 Observation 纠正下一步 | 侦探：看现场线索随时调整侦查方向 |
| Plan-and-Solve | 先一次性产出完整计划，再逐步执行 | 计划阶段提前分解，执行阶段不再重新决策 | 建筑师：先画蓝图，再按图施工 |
| Reflection | 先执行产出初稿，再评审、再修订 | 任务完成后，用自我批判迭代提升质量 | 作者：写完初稿先校对，再交稿 |

一个容易混淆的点：**Reflection 不是第四个循环，它是套在循环外面的一层迭代**。它的"执行"阶段本身就可以是 ReAct 或 Plan-and-Solve。

## ReAct

### Why Not Pure Reasoning or Pure Acting

ReAct 诞生之前，让 LLM 解决复杂问题的路线分裂成两半，各有各的死角：

- **纯思考派**（Chain-of-Thought）：引导模型一步步推理，但模型与外部世界完全隔离——推理得再认真，查不到的实时信息还是查不到，算不动的算术还是算不动，**事实性幻觉**无法避免；
- **纯行动派**：模型直接输出要执行的动作，但没有任何规划与纠错——第一步错了，后面步步错，且错了也看不出来。

ReAct（Yao et al., ICLR 2023）的洞察是：**思考与行动互为因果**。思考给行动提供目的性，行动给思考提供事实依据——两者交替，幻觉在 Observation 一步被现实打掉，规划在 Thought 一步被持续修正。

### The Thought-Action-Observation Trajectory

ReAct 用提示词强制模型的每一步输出遵循固定轨迹：

- **Thought（思考）**：智能体的"内心独白"——分析当前情况、拆解任务、制定下一步计划，或反思上一步的结果；
- **Action（行动）**：决定采取的具体动作，通常是调用一个外部工具，如 `Search['华为最新款手机']`；
- **Observation（观察）**：Action 执行后从外部工具返回的结果，如搜索摘要或 API 返回值。

智能体把新的 Observation 追加进历史记录，形成不断增长的上下文，如此循环，直到它在 Thought 中判断已经找到最终答案，输出 `Finish[最终答案]`。**推理使得行动更具目的性，而行动则为推理提供了事实依据**——这个协同效应是 ReAct 全部价值的来源。

### Formalization

每个时间步 $t$，策略 $\pi$（即 LLM）根据初始问题 $q$ 和此前的行动-观察历史，生成本步的思考与行动：

$$
(th_t, a_t) = \pi\left(q, (a_1, o_1), \ldots, (a_{t-1}, o_{t-1})\right)
$$

环境中的工具 $T$ 执行行动并返回新的观察：

$$
o_t = T(a_t)
$$

循环持续进行，直到模型在 $th_t$ 中判定任务完成。注意历史是**无界增长**的——这正是长任务里上下文爆炸的根源，应对手段（压缩、裁剪）在 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 一篇。

### The Prompt Is the Protocol

在 function calling 成为 API 标配之前，ReAct 的"协议"完全靠提示词约定。一个典型模板：

```text
你是一个有能力调用外部工具的智能助手。

可用工具如下:
{tools}

请严格按照以下格式进行回应:
Thought: 你的思考过程，用于分析问题、拆解任务和规划下一步行动。
Action: 你决定采取的行动，必须是以下格式之一:
- `{tool_name}[{tool_input}]`: 调用一个可用工具。
- `Finish[最终答案]`: 当你认为已经获得最终答案时。

现在，请开始解决以下问题:
Question: {question}
History: {history}
```

四个组成部分各有职责：**角色定义**设定身份；**工具清单**告知有哪些"手脚"（每个工具的 description 是模型判断用哪个工具的唯一依据）；**格式规约**强制输出结构化，使代码能精确解析意图；**动态上下文**把原始问题和不断累积的历史注入，让模型基于完整信息决策。

工具的定义三要素——**Name**（简洁唯一的标识符）、**Description**（自然语言说明，机制中最关键的部分）、**Execution Logic**（真正干活的函数）。一个 tool 对应一项简单具体的任务，简单到 description 一两句话能说清，模型判断最准。

### Parsing: Where the Text Protocol Leaks

LLM 返回的是纯文本，`Thought` 与 `Action` 靠正则提取：

```python
thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.DOTALL)
action_match  = re.search(r"Action:\s*(.*?)$", text, re.DOTALL)
action_match  = re.match(r"(\w+)\[(.*)\]", action_text, re.DOTALL)  # 再拆工具名与入参
```

这套解析的脆弱点是结构性的，不是调参能救的：

- 模型偶尔不守格式（漏写 `Action:`、把思考写进 Action 后面），正则直接失配；
- 参数里含 `]` 时贪婪/非贪婪匹配都可能切错；
- `Thought` 与 `Action` 的相对顺序、换行风格稍有变化，前瞻断言 `(?=\nAction:|$)` 就失灵。

更鲁棒的替代方案：**让模型输出 JSON**（约束解码或 function calling 保证结构），或至少加 few-shot 示例锚定格式。框架（如 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)）的价值一半就在这里——把"解析不可靠输出"这件脏活封装掉。

### Loop Safety: Three Guards

ReAct 是死循环高发区，三道安全阀缺一不可：

1. **最大步数限制**——通常设 5~15 步，超过强制终止。这是兜底，不是策略；
2. **重复动作检测**——连续 N 次（如 3 次）调用同一工具且参数相同，直接判定打转，退出循环；
3. **超时控制**——整个任务设最大执行时间，防止某一步的工具调用无限挂起。

### Strengths and Limitations

**特点：**

1. **高可解释性**：Thought 链就是智能体的"心路历程"，每一步为什么选这个工具、下一步打算干什么都透明——调试、审计、建立用户信任都靠它；
2. **动态规划与纠错**：走一步看一步，上一步搜索结果不理想，下一步就改搜索词重试；
3. **工具协同**：LLM 负责运筹帷幄，工具负责精确执行（搜索、计算），突破单一 LLM 在知识时效性与计算准确性上的天花板。

**局限：**

1. **强依赖 LLM 自身能力**：推理、指令遵循、格式输出任一短板，都会让流程中断；
2. **执行效率**：串行多轮调用，网络延迟与费用随步数线性增长；
3. **提示词脆弱性**：整个机制建立在一个精心调过的模板上，措辞的微小变动都可能改变行为，且并非所有模型都能持续稳定守格式；
4. **可能局部最优**：缺乏全局长远规划，可能因眼前 Observation 选择短视路径，甚至原地打转。

### Debugging Playbook

行为不符合预期时，按信息量从大到小查：

- **打印完整提示词**——含全部历史记录的最终 prompt，是追溯决策源头的最直接方式；
- **分析原始输出**——解析失败时务必看未经处理的原始文本，区分"模型没守格式"与"解析逻辑写错"；
- **验证工具输入输出**——`tool_input` 是否是工具期望的格式，`Observation` 是否是模型能理解的形态；
- **加 few-shot 示例**——模型频繁不守格式时，在提示词里塞一两个完整的 Thought-Action-Observation 成功案例，比改措辞有效；
- **换模型或调 temperature**——Agent 场景 temperature 通常设 0 要确定性；格式遵循能力差的模型直接换掉。

## Plan-and-Solve

### Two Phases

如果说 ReAct 是侦探，Plan-and-Solve（Wang et al., 2023）就是建筑师：**动工之前必须先有完整蓝图**。它的动机是思维链在多步复杂问题上容易"偏离轨道"——前面某一步推歪了，后面全盘皆输。先谋后动把"目标一致性"提前锁死：

- **规划阶段**：接收完整问题，第一件事不是解题，而是**分解问题、产出分步骤的行动计划**——计划本身是一次 LLM 调用的产物；
- **执行阶段**：拿到完整计划后**严格按步骤逐一执行**，每步可能是独立 LLM 调用或对上一步结果的加工，直到计划全部完成。

形式化地，规划模型 $\pi_{\text{plan}}$ 根据原始问题 $q$ 生成含 $n$ 步的计划 $P=(p_1,\dots,p_n)$：

$$
P = \pi_{\text{plan}}(q)
$$

执行阶段，第 $i$ 步的解决方案同时依赖原始问题、完整计划和此前所有步骤的结果：

$$
s_i = \pi_{\text{solve}}\left(q, P, (s_1, \dots, s_{i-1})\right)
$$

最终答案即最后一步的结果 $s_n$。

### The Planner

规划提示词的两个设计要点：**角色设定**（"顶级 AI 规划专家"激发专业能力）+ **格式约束**（强制输出结构化列表）。后者比前者更重要——计划要被代码解析执行，要求输出 `["步骤1", "步骤2", ...]` 这样的列表，解析稳定性远高于自然语言段落。

### The Executor and Its State

执行提示词必须带四样东西：**原始问题**（模型始终知道最终目标）、**完整计划**（知道当前步在全局中的位置）、**历史步骤与结果**（当前步的直接输入）、**当前步骤**（明确本轮只解决什么）。

执行器因此承担**状态管理**职责：把每步结果累积进 history，作为下一步的上下文。这本质上是把 ReAct 里"每轮动态重决策"换成"按既定剧本走"——信息流的形状相同，决策权的位置不同。

### The Static Plan Problem

Plan-and-Solve 的软肋在计划是**一次性静态**的：执行中发现某步走不通、结果不符合预期，原范式没有机制回头改计划。常见的改进是**动态重规划（replan）**——执行若干步后带着已完成的结果重新调用规划器，修订剩余计划。加了 replan 的 Plan-and-Solve 与 ReAct 的边界开始模糊，区别只剩"规划是全量提前还是分批提前"。

适用场景：多步数学应用题、需要整合多个信息源的报告撰写、代码生成——**结构性强、逻辑路径确定、内部推理密集**的任务。

## Reflection

### Execute, Reflect, Refine

ReAct 与 Plan-and-Solve 都是"任务完成即结束"，初稿里的谬误没有机会被修正。Reflection（Reflexion，Shinn et al., NeurIPS 2023）引入事后的自我校正循环，灵感来自人类的学习过程：写完初稿要校对，解完题目要验算。三步循环：

1. **执行（Execution）**：用 ReAct 或 Plan-and-Solve 尝试完成任务，生成初步方案（"初稿"）；
2. **反思（Reflection）**：一个独立实例（或带特殊提示词的同一模型）扮演"评审员"，从事实性错误、逻辑漏洞、效率问题、遗漏信息等维度评估初稿，产出结构化**反馈（Feedback）**；
3. **优化（Refinement）**：把初稿和反馈作为新上下文，再次调用模型生成"修订稿"。

### Formalization

设 $O_i$ 为第 $i$ 次迭代的输出（$O_0$ 为初始输出），反思模型生成反馈，优化模型据此产出新版本：

$$
F_i = \pi_{\text{reflect}}(\text{Task}, O_i)
$$

$$
O_{i+1} = \pi_{\text{refine}}(\text{Task}, O_i, F_i)
$$

### The Reviewer Is a Role, Not Necessarily a Model

实践中的关键经验：**反思效果取决于提示词里的角色设定，而不是换了更强的模型**。"你是一位极其严格的代码评审专家，对性能有极致要求"会让评审直奔时间复杂度瓶颈；同一个模型换成"注重可读性的开源维护者"角色，反馈方向立刻不同。三角色提示词（执行 / 评审 / 优化）各自独立设计，是这套机制的主要工程量——每轮迭代至少额外消耗两次 LLM 调用（一次反思、一次优化）。

### Short-Term Memory

迭代的前提是记住此前的尝试与反馈。一个最小记忆模块只需按序存 `(type, content)` 两类记录（execution / reflection），提供两个操作：**序列化轨迹**（拼成文本插进后续提示词，给评审和优化提供完整上下文）与**取最近一次执行结果**。注意这是**会话内的短期轨迹**，与 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 里跨会话、可增删改写的知识库式 Memory 是两个层次——后者管"越用越懂你"，前者管"这一轮怎么改"。

### Termination and Convergence

两个终止条件：反馈中出现"无需改进"，或达到最大迭代次数。前者的本质是**让模型自评收敛**——已优化的代码，评审员可能一边肯定效率一边罗列分段筛法之类的高级方向，最后自己得出"一般情况下无需改进"的判断。这个判断触发终止，迭代得以收敛，但它终究是模型的自评，存在"过早宣称无需改进"的风险；最大迭代次数是保底。

### Cost and Benefit

**成本：**

- 每轮迭代至少 +2 次 LLM 调用，多轮下来 API 成本成倍增加；
- 串行过程，每轮优化必须等待上轮反思完成，总延迟显著拉长，不适合实时场景；
- 三套提示词的设计与调试是持续投入。

**收益：**

- 方案质量的**跃迁**——从"合格"到"优秀"，从功能正确到性能高效，从逻辑粗糙到逻辑严谨；
- 鲁棒性增强——内部纠错回路能发现逻辑漏洞、事实错误、边界情况处理不当。

典型的"以成本换质量"：**对最终质量、准确性、可靠性要求极高，且对实时性宽松**的场景用它（关键业务代码、科学推演、决策支持）；需要快速响应或"大致正确"就够的场景，用更轻量的 ReAct 或 Plan-and-Solve 更划算。

## Choosing a Paradigm

| 维度 | ReAct | Plan-and-Solve | Reflection |
| :--- | :--- | :--- | :--- |
| 决策时机 | 每一步重新决策 | 计划阶段一次决策，执行阶段不再决策 | 任务完成后追加评审迭代 |
| 上下文来源 | 上一步 Observation | 原始问题 + 完整计划 + 历史结果 | 初稿 + 评审反馈 |
| 核心优势 | 环境适应性、动态纠错 | 结构性、目标一致性 | 质量跃迁、鲁棒性 |
| 主要代价 | 多轮调用、提示词脆弱 | 计划僵化、缺 replan 机制 | 成本翻倍、串行延迟 |
| 典型场景 | 探索性任务、需要外部工具（搜索/API） | 多步推理、报告、代码生成 | 关键代码、深度分析、质量优先 |

三条选型经验：

1. **默认从 ReAct 开始**——它是另外两种的"执行单元"，生态最厚，可解释性最好；
2. **逻辑路径确定的任务换 Plan-and-Solve**——规划先行让长链条不跑偏，但记得评估要不要加 replan；
3. **质量不达标时再套 Reflection**——它是质量放大器，不是起点；且只在实时性宽松时用。

组合是常态：智能客服 = ReAct + Tool Use + Reflection（查订单、查库存，答前自检）；代码助手 = ReAct + Reflection + Tool Use（写代码、跑测试、按报错修订）。反过来，**不要过早引入 Multi-Agent**——一个强大的单 Agent 往往比多个简单 Agent 协作更稳定、更省钱；只有任务明确需要并行或专业分工时才上多 Agent（模式地图见 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 的 Pattern 一节）。

## A Minimal Agent Loop in TypeScript

### Why Write One by Hand

框架把循环、解析、重试都封装了，但"Agent 到底由什么构成"这个问题，只有亲手写一遍最小实现才能答上来。选 TypeScript 有两个现实理由：本库追踪的 [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md) 等产品的运行时就是 TS 工程；Node 18+ 原生 `fetch` 让零依赖调用 OpenAI 兼容端点成为可能。

### Design Choices

三个刻意的取舍，每个都对应正文讲过的机制：

- **文本协议（Thought/Action）而非 JSON tools**：最小依赖、每一步可解释；代价是解析脆弱——上面「Parsing」一节列的问题，这份实现原样承受；
- **OpenAI 兼容端点**：`LLM_BASE_URL` 指向任意兼容服务，一套代码切换提供商；
- **temperature = 0**：Agent 要的是确定性，不是创造力。

### The Complete Minimal Implementation

单文件、零第三方依赖，保存为 `agent-loop.ts`（Node 18+，ESM）：

```typescript
// 最小 Agent Loop：Reason -> Act -> Observe，直到 Finish 或触及步数上限
// 运行：LLM_API_KEY=... LLM_BASE_URL=https://api.openai.com/v1 LLM_MODEL_ID=gpt-4o-mini node agent-loop.ts

// ---------- 工具层：给 LLM 的"手脚" ----------
interface Tool {
  name: string;
  description: string; // 给模型看的"按钮说明书"：什么时候该按哪个
  execute: (input: string) => Promise<string> | string;
}

class ToolRegistry {
  private tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  // 渲染成提示词里的工具清单——description 是模型判断用哪个工具的唯一依据
  describe(): string {
    return [...this.tools.values()].map((t) => `- ${t.name}: ${t.description}`).join("\n");
  }

  async run(name: string, input: string): Promise<string> {
    const tool = this.tools.get(name);
    if (!tool) return `错误：未找到名为 '${name}' 的工具`;
    try {
      return await tool.execute(input);
    } catch (err) {
      return `错误：工具 '${name}' 执行失败：${(err as Error).message}`;
    }
  }
}

// ---------- LLM 层：一次 think = 一次 chat completion ----------
const { LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID } = process.env;

async function think(prompt: string): Promise<string> {
  const res = await fetch(`${LLM_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${LLM_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: LLM_MODEL_ID,
      messages: [{ role: "user", content: prompt }],
      temperature: 0,
    }),
  });
  if (!res.ok) throw new Error(`LLM API ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return data.choices[0].message.content ?? "";
}

// ---------- 输出解析：文本协议的代价在这里 ----------
function parseOutput(text: string): { thought?: string; action?: string } {
  const thought = /Thought:\s*([\s\S]*?)(?=\nAction:|$)/.exec(text)?.[1]?.trim();
  const action = /Action:\s*([\s\S]*)$/.exec(text)?.[1]?.trim();
  return { thought, action };
}

function parseAction(action: string): { name: string; input: string } | null {
  const m = /^(\w+)\[([\s\S]*)\]$/.exec(action.trim());
  return m ? { name: m[1], input: m[2] } : null;
}

// ---------- 提示词：协议就写在这里 ----------
const PROMPT_TEMPLATE = `你是一个有能力调用外部工具的智能助手。

可用工具如下:
{tools}

请严格按照以下格式进行回应:
Thought: 你的思考过程，用于分析问题、拆解任务和规划下一步行动。
Action: 你决定采取的行动，必须是以下格式之一:
- \`{tool_name}[{tool_input}]\`: 调用一个可用工具。
- \`Finish[最终答案]\`: 当你认为已经获得最终答案时。

现在，请开始解决以下问题:
Question: {question}
History: {history}`;

// ---------- 循环本体：整个 Agent 就这十几行 ----------
async function runAgent(
  question: string,
  tools: ToolRegistry,
  maxSteps = 5,
): Promise<string | null> {
  const history: string[] = []; // 上轮的 Action/Observation 在这里回灌——Memory 的最简形态

  for (let step = 1; step <= maxSteps; step++) {
    const prompt = PROMPT_TEMPLATE.replace("{tools}", tools.describe())
      .replace("{question}", question)
      .replace("{history}", history.join("\n") || "（暂无）");

    const { thought, action } = parseOutput(await think(prompt));
    console.log(`\n--- 第 ${step} 步 ---\n🤔 ${thought ?? "（未解析到 Thought）"}`);

    if (!action) {
      console.log("⚠️ 未解析出有效 Action，流程终止");
      return null;
    }
    console.log(`🎬 ${action}`);

    // 收敛：模型自称完成
    const finish = /^Finish\[([\s\S]*)\]$/.exec(action.trim());
    if (finish) return finish[1];

    const call = parseAction(action);
    const observation = call
      ? await tools.run(call.name, call.input)
      : "错误：Action 格式无法解析，请严格按照 tool_name[tool_input] 或 Finish[答案] 格式输出";

    console.log(`👀 ${observation}`);
    history.push(`Action: ${action}`, `Observation: ${observation}`);
  }

  console.log("⚠️ 已达到最大步数，流程终止");
  return null; // 安全阀：防死循环烧钱
}

// ---------- 组装 ----------
const tools = new ToolRegistry();
tools.register({
  name: "Search",
  description: "一个网页搜索引擎。当你需要回答关于时事、事实以及知识库中找不到的信息时，应使用此工具。",
  execute: async (query) => {
    // 真实实现接 SerpApi / Brave / Tavily 等；这里留作练习
    return `（搜索 '${query}' 的返回结果）……`;
  },
});

const answer = await runAgent("华为最新的手机是哪一款？它的主要卖点是什么？", tools);
console.log(`\n🎉 最终答案: ${answer}`);
```

把这段代码和 ReAct 一节的机制逐行对照，每个概念都能落地：`history` 就是"执行结果回灌上下文"；`maxSteps` 就是最大步数安全阀；`Finish` 分支就是循环的收敛条件；`ToolRegistry.describe()` 就是"description 是模型判断用哪个工具的唯一依据"。**框架做的所有事，都是在这十几行上加东西**——重试、并发、观测、权限，见下文。

### From Text Protocol to Native Tool Calling

现代 API 已把协议升级：请求时传 `tools` 数组（name + description + JSON Schema 参数），模型若不调工具则正常返回文本，若调工具则响应里带结构化的 `tool_calls`：

```typescript
// 请求体多一个 tools 字段（每个工具的参数用 JSON Schema 描述）
body: JSON.stringify({
  model: LLM_MODEL_ID,
  messages,
  tools: [{
    type: "function",
    function: {
      name: "Search",
      description: "一个网页搜索引擎。当你需要回答关于时事、事实以及知识库中找不到的信息时，应使用此工具。",
      parameters: {
        type: "object",
        properties: { query: { type: "string", description: "搜索关键词" } },
        required: ["query"],
      },
    },
  }],
});

// 响应解析：tool_calls 由 API 保证是合法 JSON，正则那套脆弱性整体消失
const msg = data.choices[0].message;
for (const call of msg.tool_calls ?? []) {
  const args = JSON.parse(call.function.arguments); // { query: "..." }
  const observation = await tools.run(call.function.name, JSON.stringify(args.query));
}
```

变化只在"解析"这一步的可靠性：**循环骨架原封不动**——think → act → observe → append history。选文本协议还是原生 tool calling，取决于你要最小可解释（前者）还是要最大鲁棒（后者）；生产系统几乎都走后者，但前者的每一行都对应后者的某个抽象。

### What This Minimal Version Deliberately Omits

这份实现刻意省掉的东西，恰好划出了 Harness 的边界——每一项在 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 有展开：

- **重试与超时**：`think` 和 `tools.run` 都可能失败，工程上需要指数退避与超时预算；
- **观测**：每轮的 Thought/Action/Observation 应落成 Trace，Token 消耗要可计量；
- **权限**：真实环境里不是每个工具都能无条件的跑，沙箱与分级授权是另一层（见 [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)）；
- **上下文管理**：`history` 无界增长，长任务里需要压缩与裁剪（见 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)）；
- **多模态与并发**：并行工具调用、多 Agent 协作是更上层的编排问题。

换句话说：**这十几行是内核，框架是操作系统**。内核不变，操作系统可以整个换掉。

## Links

- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)
- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [Hello-Agents 第四章 智能体经典范式构建](https://datawhalechina.github.io/hello-agents/#/./chapter4/%E7%AC%AC%E5%9B%9B%E7%AB%A0%20%E6%99%BA%E8%83%BD%E4%BD%93%E7%BB%8F%E5%85%B8%E8%8C%83%E5%BC%8F%E6%9E%84%E5%BB%BA)
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- [Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models](https://arxiv.org/abs/2305.04091)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
