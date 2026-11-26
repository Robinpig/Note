## Introduction

`agentscope.classifier` 是 v2.0.9 引入的一层新抽象：**返回带类型的概率化决策**的模型。它不生成文本，而是对「一批具名 question」给出 `Binary` / `Choice` / `Score` / `Refusal` 四类答案。`ModelRouterMiddleware` 把它接进 Agent，实现**每个 reply 用分类器挑一个 chat model**——把以往放在网关或应用层做的「大小模型分流」下沉到了单个 Agent 内部。

> 版本基线：v2.0.11（`src/agentscope/classifier/`、`src/agentscope/middleware/_model_router.py`）

三个反直觉点：

1. **概率不是本地算的**：两家实现的概率都由服务端返回，AgentScope 只做归一化，源码注释直说 "Translate … without changing its probabilities"（`classifier/_openai/_model.py`、`classifier/_jev/_model.py`）。
2. **jev 不是另一家大模型**，而是 TypeSafe 的 Jev System One SDK；Binary 问题被映射成它的 `Noul` 原语，概率直接取 `answer.noul`。
3. **`ModelRouterMiddleware` 每次 `on_reply` 结束都把 `agent.model` 还原**（`middleware/_model_router.py`）。所谓「HITL 恢复后保持不变」不是模型对象没被换回去，而是**恢复时按 `reply_id` 重新替换成同一个候选**。

## The Classifier Abstraction

`ClassifierModelBase.__call__(state: str | dict, questions: Mapping[str, ClassifierQuestion], **kwargs) -> ClassifierResponse`（`classifier/_base.py`）是唯一抽象入口：输入是共享 state 加一批具名 question，输出一个 `ClassifierResponse`。

```python
# classifier/_base.py
    @abstractmethod
    async def __call__(
        self,
        state: str | dict,
        questions: Mapping[str, ClassifierQuestion],
        **kwargs: Any,
    ) -> ClassifierResponse:
```

| 类型 | 位置 | 内容 |
| :--- | :--- | :--- |
| `ClassifierResponse` | `classifier/_response.py` | `model / content: dict[str, ClassifierAnswer] / usage / id / created_at / type / metadata` |
| `ClassifierAnswer` | `classifier/_response.py` | `BinaryAnswer \| ChoiceAnswer \| ScoreAnswer \| RefusalAnswer` 四型联合，均带 `type` 判别字段；概率字段分别为 `probability` / `confidence` / `probabilities` |
| `ClassifierQuestion` | `classifier/_question.py` | `BinaryQuestion / ChoiceQuestion / ScoreQuestion`，用 `Field(discriminator="type")` 判别 |
| `ClassifierUsage` | `classifier/_usage.py` | `time / input_tokens / output_tokens / type` |

上面表格里的「四型联合」与「判别字段」由下面两段真实定义给出（分别摘自 `classifier/_response.py`、`classifier/_question.py`）：

```python
# classifier/_response.py
#: A provider-independent classifier answer.
ClassifierAnswer: TypeAlias = (
    BinaryAnswer | ChoiceAnswer | ScoreAnswer | RefusalAnswer
)
```

```python
# classifier/_question.py
#: A provider-independent classifier question.
ClassifierQuestion: TypeAlias = Annotated[
    BinaryQuestion | ChoiceQuestion | ScoreQuestion,
    Field(discriminator="type"),
]
```

`content` 按 question 的 key 索引，所以一次调用可以并发问多个问题、拿回一组带类型的答案。

## Two Providers, Two APIs

| 维度 | OpenAI | jev |
| :--- | :--- | :--- |
| 后端 API | OpenAI **Decisions API**，`client.decisions.create`（`classifier/_openai/_model.py`） | TypeSafe 的 **Jev System One**，`AsyncTypeSafeClient.system_one`（`classifier/_jev/_model.py`） |
| 依赖 / 默认模型 | `openai>=3.26.0`，默认 `gpt-6-luna`（`classifier/_openai/_model.py`） | `typesafe_sdk`，默认 `jev-latest`（`classifier/_jev/_model.py`） |
| Binary 映射 | → `predicate` | → TypeSafe `Noul` 原语，概率取 `answer.noul`（`classifier/_jev/_model.py`） |
| Refusal | 支持，映射成 `RefusalAnswer`（`classifier/_openai/_model.py`） | **没有**；`_from_sdk_answer` 只有 noul / choice / score 三支（`classifier/_jev/_model.py`） |

两家的「翻译」函数都只是把服务端答案原样搬进带类型的 dataclass，概率字段直接取自 SDK 返回值（`classifier/_openai/_model.py`、`classifier/_jev/_model.py`）：

```python
# classifier/_openai/_model.py
def _from_sdk_answer(answer: Any) -> ClassifierAnswer:
    """Translate a Decisions answer without changing its probabilities."""
    match answer.type:
        case "predicate":
            return BinaryAnswer(probability=answer.probability)
        case "choice":
            return ChoiceAnswer(
                choice=answer.choice,
                confidence=answer.confidence,
                probabilities={
                    p.value: p.probability for p in answer.probabilities
                },
            )
        case "score":
            return ScoreAnswer(
                score=answer.score,
                confidence=answer.confidence,
                legend={p.value: p.label for p in answer.probabilities},
                probabilities={
                    p.value: p.probability for p in answer.probabilities
                },
            )
        case "refusal":
            return RefusalAnswer()
    raise ValueError(f"Unsupported OpenAI answer type: {answer.type!r}.")
```

```python
# classifier/_jev/_model.py
def _from_sdk_answer(answer: Any) -> ClassifierAnswer:
    """Translate a TypeSafe answer to an AgentScope answer."""
    match answer.type:
        case "noul":
            return BinaryAnswer(probability=answer.noul)
        case "choice":
            return ChoiceAnswer(
                choice=answer.choice,
                confidence=answer.confidence,
                probabilities=dict(answer.probabilities),
            )
        case "score":
            return ScoreAnswer(
                score=answer.score,
                confidence=answer.confidence,
                legend=dict(answer.legend),
                probabilities=dict(answer.probabilities),
            )
    raise ValueError(f"Unsupported TypeSafe answer type: {answer.type!r}.")
```

`Noul` 原语在 question 侧的映射也真实存在（`classifier/_jev/_model.py`）：

```python
# classifier/_jev/_model.py
        case BinaryQuestion():
            # The binary question maps to TypeSafe's Noul primitive
            criteria = question.criteria and question.criteria.model_dump(
                exclude_unset=True,
            )
            return Noul(instructions=question.instructions, criteria=criteria)
```

两家都只在 `metadata` / `usage` 里记 token 与耗时（`classifier/_openai/_model.py`、`classifier/_jev/_model.py`），不做本地 softmax、不做阈值裁决——**provider 报什么概率就存什么概率**，决策阈值由调用方（如 router）自己定。

## ModelRouterMiddleware

文件位置容易记错：它在 **`middleware/_model_router.py`**，由 `agentscope.middleware` 导出（`middleware/__init__.py`），**不在 `app/middleware/`**。配套类型是 `ChatModelCandidate`（`middleware/_model_router.py`）：

```python
# middleware/__init__.py
from ._model_router import ChatModelCandidate, ModelRouterMiddleware
```

```python
# middleware/_model_router.py
@dataclass
class ChatModelCandidate:
    """A named chat model and the criteria for selecting it."""

    name: str
    """The stable name returned by the classifier."""

    model: ChatModelBase
    """The chat model used when this candidate is selected."""

    description: str
    """When this candidate should be selected."""
```

构造时校验候选名唯一，并构造一个 `ChoiceQuestion` 加一份 enum JSON schema 作兜底（`middleware/_model_router.py`）：

```python
# middleware/_model_router.py
        names = [candidate.name for candidate in candidates]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate chat model candidates: {names}")

        self.classifier_model = classifier_model
        self._models = {_.name: _.model for _ in candidates}
        criteria = {_.name: _.description for _ in candidates}
        self._question = ChoiceQuestion(
            instructions=instructions,
            criteria=criteria,
        )
        self._prompt = (
            f"{instructions}\n\n"
            "Select exactly one candidate using these criteria:\n"
            f"{json.dumps(criteria, ensure_ascii=False, indent=2)}"
        )
        self._schema = {
            "type": "object",
            "properties": {"choice": {"type": "string", "enum": names}},
            "required": ["choice"],
            "additionalProperties": False,
        }
```

`on_reply` 的完整逻辑（`middleware/_model_router.py`）：

```python
# middleware/_model_router.py
    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        """Swap ``agent.model`` for the selected candidate during the reply."""
        key = await self.get_middleware_key()
        original_model = agent.model
        # Before ReplyStartEvent, reply_id still names the previous reply
        new_reply = isinstance(input_kwargs["inputs"], (Msg, list))
        routed = agent.state.middle_context.get(key, {})
        agent.model = self._models.get(
            None if new_reply else routed.get(agent.state.reply_id),
            original_model,
        )
        try:
            async for event in next_handler(**input_kwargs):
                if isinstance(event, ReplyStartEvent):
                    name = await self._route(
                        self._latest_user_text(input_kwargs["inputs"]),
                    )
                    agent.state.middle_context[key] = {event.reply_id: name}
                    agent.model = self._models.get(name, original_model)
                yield event
        finally:
            agent.model = original_model
```

三个关键细节：

- 路由只在 `ReplyStartEvent` 触发一次，决策按 `reply_id` 存进 `AgentState.middle_context`（`middleware/_model_router.py`、`state/_state.py`），所以 HITL 恢复走的是「读回旧决策 → 重新替换」，而不是「不还原」。
- 分类抛异常或选到未知候选时记 warning 返回 `None`，`_models.get(name, original_model)` 保持 Agent 自己的模型（`middleware/_model_router.py`）：

```python
# middleware/_model_router.py
        except Exception as error:
            logger.warning(
                "Chat model routing failed, keeping the agent's model: %s",
                error,
            )
            return None
        if name not in self._models:
            logger.warning(
                "Routing model selected unknown candidate %r, keeping the "
                "agent's model",
                name,
            )
            return None
```

- `finally` 每次都还原（`middleware/_model_router.py`），所以中间件**不会污染 Agent 实例的长期配置**；同一实例被多个 Agent 共享也安全，因为状态全在 state 里。

## v2.0.11 Delta

`git diff v2.0.10..v2.0.11` 在 classifier 包里只有两处同构改动：`classifier/_openai/_model.py` 与 `classifier/_jev/_model.py` 把默认参数收进 dict 再 `**kwargs`，使 per-call 的 `model` / `input` 可以覆盖实例默认，docstring 同步更新。也就是说 **v2.0.11 的 classifier 只是让调用方能临时换模型，抽象面没动**。

```python
# classifier/_openai/_model.py
        start_time = perf_counter()
        # Per-call options override defaults.
        response = await self.client.decisions.create(
            **{
                "model": self.model,
                "input": _to_sdk_input(state),
                "questions": [
                    _to_sdk_question(name, q) for name, q in questions.items()
                ],
                **kwargs,
            },
        )
```

```python
# classifier/_jev/_model.py
        start_time = perf_counter()
        # Per-call options override defaults.
        response = await self.client.system_one(
            **{
                "state": state,
                "questions": {
                    name: _to_sdk_question(question)
                    for name, question in questions.items()
                },
                "model": self.model,
                **kwargs,
            },
        )
```

## Where It Sits

这条链路把「分类」从应用层下沉成框架内的一类模型，但它**并没有并进 credential 体系**。`credential/_base.py` 的 `TYPE_CHECKING` 只 import 了 ASR / Embedding / Chat / Realtime / TTS 的基类与 Card，里面没有 Classifier：

```python
if TYPE_CHECKING:
    from ..asr import ASRModelBase, ASRModelCard
    from ..embedding import EmbeddingModelBase
    from ..model import ChatModelBase, ModelCard
    from ..realtime import RealtimeModelBase, RealtimeModelCard
    from ..tts import TTSModelBase
    from ..tts._tts_model_card import TTSModelCard
```

`CredentialFactory` 同样只发现各家 Credential；Classifier 走 `classifier/` 下独立的 `ClassifierModelBase` 抽象基类，由 `OpenAIClassifierModel` / `JevClassifierModel` 实现。而 `ModelRouterMiddleware` 只是 7 个 Agent hook 里 `on_reply` 的一个消费者——它没有新增 hook，也没有改中间件基类，这正是 AgentScope「核心层稳定、能力靠组合扩张」的一个样本。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [AgentLoop 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md)
- [SOP 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md)
- [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — classifier/_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/classifier/_base.py)
- [AgentScope v2.0.11 — classifier/_response.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/classifier/_response.py)
- [AgentScope v2.0.11 — classifier/_jev/_model.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/classifier/_jev/_model.py)
- [AgentScope v2.0.11 — middleware/_model_router.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/middleware/_model_router.py)
- [AgentScope v2.0.11 release notes](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.11)
