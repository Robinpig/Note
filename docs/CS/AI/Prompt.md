## Introduction

在大规模语言模型（LLM, Large Language Models）领域，Prompt 是一种结构化的输入序列，用于引导预训练语言模型生成预期的输出。它通常包括明确的任务要求、背景信息、格式规定以及示例，以充分利用模型的能力在特定任务中生成高质量的响应。

把这句话再说准一点：**prompt 是你在推理时唯一能改动的输入**。模型权重、训练数据、上下文窗口都是调用前就定死的，prompt 是唯一留在手里的旋钮——这也是为什么同一个模型，提示写法的差距常常大过换一个档位的模型。它本质上不是"问句"，而是**一次性的程序**：没有循环、没有变量、没有调试器，全部逻辑必须摊平在一段文本里，靠模型对自然语言的统计理解来"执行"。

## How a Prompt Actually Runs

理解提示工程之前，先看清一次调用里 prompt 处于什么位置。模型看到的不是你以为的那句话，而是一整段拼装好的上下文：

```
系统提示（角色与约束）
  + 工具定义（function calling 的 schema）
  + 历史对话（此前的轮次，可能被截断/压缩）
  + 当前用户输入
  → tokenize → prefill（一次前向，算力密集）→ 自回归 decode（逐 token，带宽密集）
```

三个推论直接决定写法：

- **一切都在上下文里竞争注意力。** 系统提示写得越长，每条指令被"听见"的权重越薄；互相矛盾的约束（"简洁"与"详尽"）不会报错，只会得到一个折中的平庸结果。
- **模型没有记忆，只有上下文。** 跨会话、超窗口的信息不会凭空保留，要么重写进 prompt，要么靠外部机制——这是 [RAG](/docs/CS/AI/RAG.md) 与 Agent 记忆层存在的理由。
- **输入即全部证据。** 模型回答"不知道"并不比编一个答案更默认——缺什么就明确写进 prompt，包括"资料不足时说明资料不足"这种指令本身。

## Writing a Good Prompt

抛开话术，高质量提示稳定地做四件事：

1. **说清任务与验收标准。** "写得好"不可执行，"按 X 格式输出、包含 A/B/C 三段、总长 300 字内"可执行。判断标准是：一个不了解背景的人照着这段文字能否复现出你要的输出。
2. **给足上下文，并标明来源边界。** 把参考资料放进分隔符（如 `"""` 或 XML 标签）内，并明确"只依据以下资料回答"。分隔符同时降低了提示注入把资料尾部伪装成指令的风险。
3. **用示例锚定格式与风格。** few-shot 是给"输出形状"上的保险：一个输入输出对，往往比三段形容词更准确地传达你要什么。示例要覆盖边界情形，只给简单例子会让模型把简单当规范。
4. **分解任务，而不是堆指令。** 复杂任务拆成有序步骤写出来（"先列要点，再逐条展开，最后自查是否覆盖全部要点"），比一段密不透风的长指令可靠。对显式要求"展示推理过程"的做法（chain-of-thought），注意它提升复杂任务表现的同时拉长输出；对内置思考预算的推理模型，这类显式催促的收益已经下降，但**任务分解与格式约束仍然普遍有效**。

常见反模式与上面的四条一一对应：一次提十个互相挤压的要求、把参考资料混写在指令里没有分隔、只给一个过于简单的示例、以及用"你是一个资深专家"这类角色扮演替代具体的验收标准。

## What Prompting Cannot Fix

提示工程的上界由架构与部署决定，这几条它碰不到：上下文窗口就那么大，超长输入要么被截断要么被压缩（根因在 self-attention 的 O(n²) 成本，见 [Transformer](/docs/CS/AI/Transformer.md)）；训练数据截止之后的事，写进 prompt 的资料之外它不知道；幻觉的根因是建模目标是 token 分布而非事实核查。需要突破这三条时，该换的手段分别是记忆与压缩机制、外部检索（[RAG](/docs/CS/AI/RAG.md)）、以及让模型在环境里执行与自纠错的包裹层（[Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)）。

反过来，**能靠 prompt 解决的不要先上架构**：输出格式不稳定、语气不一致、遗漏显式要求，多数是提示没写清，而不是模型不行。

## Links

- [LLM：模型总纲](/docs/CS/AI/LLM/LLM.md)
- [Transformer：架构根因](/docs/CS/AI/Transformer.md)
- [RAG：外部事实供给](/docs/CS/AI/RAG.md)
- [Agent：执行与记忆的包裹层](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Tools：工具调用与结构化输出](/docs/CS/AI/LLM/Protocol/Tools.md)

## References

1. [Language Models are Few-Shot Learners（GPT-3）](https://arxiv.org/abs/2005.14165)
2. [Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903)
3. [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
4. [OpenAI Prompt Engineering Guide](https://platform.openai.com/docs/guides/prompt-engineering)
