## Introduction

AgentScope 的工具体系把「参数校验 + 结果整形」与「真正 I/O」彻底分离：内置 14 个工具自己不做任何 I/O，全部委托 `BackendBase`；同一套 `ToolBase` 接口下有三种实现（手写类 / FunctionTool / MCPTool），统一走中间件洋葱链。本分册从主干笔记拆出，按 v2.0.11 源码重核。主干与上层机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md) 与 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## Tool System

### Toolkit

`Toolkit` 是 Agent 可调用工具的唯一来源。构造时可以注册 Python 函数、MCP 连接、Skill。

工具的两个关键属性：
- `is_concurrency_safe` —— 能否安全并发执行（决定批处理策略）
- `is_read_only` —— 是否只读（权限系统的 fast path，只读调用永远 ALLOW）

这三个来源最后统一成 `Toolkit._get_available_tools()` 返回的 `dict[name, RegisteredTool]`——模型拿到的永远是同一套 JSON schema，不管工具是 MCP server 来的还是本地 Python 函数。

### Built-in Toolset

`tool/_builtin/` 下 10 个工具类（v2.0.9 新增 `AskUser`），加上 `_task/` 里的 4 个任务工具，共 **14 个**。但 `AskUser` 是外部工具、不做 I/O 也不实现 `__call__`，下面「自己不做任何 I/O」的说法适用于其余 13 个。它们**自己不做任何 I/O**——全部读写委托给 `BackendBase`（`tool/_builtin/_backend.py`），工具只负责参数校验、结果整形和缓存策略：

| 工具 | 文件 | 主要约束 |
| :--- | :--- | :--- |
| `Bash` | `_bash.py` | 走 parser 安检（见下） |
| `PowerShell` | `_powershell.py` | Windows 场景的对等物 |
| `Read` | `_read.py` | `offset` 1-based、`limit ≤ 2000`；单行超 `max_line_characters=2000` 截断并标 `[truncated]`；PDF 无 `pages` 参数时最多 10 页、单次最多 20 页；按扩展名分派 pdf/image/text 三路渲染 |
| `Write` | `_write.py` | 必须绝对路径；**read-before-write**——目标已存在时先查 mtime 缓存，没有读过就报错；写前 `mkdir -p`；返回值 `metadata` 带 unified diff |
| `Edit` | `_edit.py` | 必须绝对路径、文件必须存在、`old_string != new_string`、命中多于一次必须显式 `replace_all`；同样强制先 Read |
| `Grep` | `_grep.py` | `DEFAULT_HEAD_LIMIT=250`，`limit=0` 表示不限；拼 `rg` 参数经 `exec_shell` 执行，30s 超时 |
| `Glob` | `_glob.py` | base 目录必须是目录；调 `_glob_helper.py` 脚本执行，30s 超时 |
| `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate` | `_task/` | 继承自 `_TaskToolBase`，`check_permissions` 恒 ALLOW；数据模型在 `state/_task.py` |
| `SkillViewer` | `_skill.py` | 注册名是 `Skill`，供 Agent 主动读 skill 正文 |
| `ResetTools` | `_meta.py` | 注册名 `reset_tools`，切换激活的 tool group |

Read / Write / Edit 共用 `AgentState.tool_context.read_file_cache`（`state/_state.py`），这是一个 **LRU + 字节双限**缓存：`max_cache_files=100`、`max_cache_bytes=25000`，按 mtime 判失效。一个细节值得注意——单个缓存项超过 `max_cache_bytes` 时直接丢弃，而不是去驱逐别人。

### BashCommandParser: Real Parsing, Not Regex

`_bash_parser.py` 是整套内置工具里最意外的部分：它没有用正则匹配危险命令，而是挂了 **`tree_sitter_bash` 真语法解析**（`Parser(Language(tsbash.language()))`）。类定义与解析器初始化：

```python
class BashCommandParser:
    """Parse Bash commands using tree-sitter for accurate syntax analysis."""

    def __init__(self) -> None:
        """Initialize the parser with tree-sitter-bash language."""
        self.parser = Parser(Language(tsbash.language()))

    def is_read_only_command(self, command: str) -> bool:
```

有了 AST 之后下面这些检查才立得住：

- `split_compound_command()` —— 递归 AST，把 `&&` `||` `;` `|` `|&` 串起来的复合命令拆成子命令，逐条判定
- `check_dangerous_command()` —— 危险命令表匹配，词边界判定而非子串
- `check_sed_constraints()` —— `sed` 专项约束
- `check_injection_risk()` —— 注入风险检测
- `is_read_only_command()` —— 只读判定，喂给权限系统当 fast path
- `extract_command_prefixes()` / `extract_file_paths()` / `extract_redirections()` —— 提取命令前缀和涉及路径，**用于生成 `suggested_rules` 建议规则**

这也解释了为什么权限系统能给出形如 `Bash(git *)` 的建议规则——它不是把整条命令塞进规则，而是从 AST 提取前缀。

### Three Adapters: ToolBase / FunctionTool / MCPTool

同一套 `ToolBase` 接口（`tool/_base.py`）下有三种实现，`__call__` 统一走中间件洋葱链，差别只在复写点与默认策略：

| | `ToolBase`（子类化） | `FunctionTool`（`_adapters.py`） | `MCPTool`（`_adapters.py`） |
| :--- | :--- | :--- | :--- |
| 包装对象 | 手写的类 | 任意 Python 函数 | `mcp.types.Tool` |
| schema 来源 | 手写 `input_schema` | 从签名 + docstring 自动生成 | MCP server 的 `inputSchema` |
| `check_permissions` | 抽象方法，必须实现 | 默认 ASK | read-only 则 ALLOW，否则 ASK |
| `is_concurrency_safe` | 自定 | 默认 `True` | 默认 **`False`** |
| `is_state_injected` | 自定 | 可设 | 硬编码 `False` |

最后一行是条重要的安全边界——MCP 工具**禁止状态注入**（源码注释原话："The mcp tools is prohibited state injection for safety reason"）。[MCP](/docs/CS/AI/LLM/Protocol/MCP.md) server 是远端第三方，让它的工具签名接受框架注入的内部状态等于开了一条数据外泄通道。真实定义：

```python
class MCPTool(ToolBase):
    """Adapter to convert an MCP tool to ToolProtocol.

    This class wraps an MCP tool and makes it compatible with the
    ToolProtocol interface. It handles the conversion between MCP's
    result format and AgentScope's ToolChunk format.
    """

    is_mcp: bool = True
    """Whether this tool is an MCP tool."""
    is_state_injected: bool = False
    """The mcp tools is prohibited state injection for safety reason."""
```

**MCP 工具改名规则**是个容易忽略的硬约束：LLM 厂商强制工具名匹配 `^[a-zA-Z0-9_-]+$`，而 MCP server 返回的名字可能带 `.` `:` 之类字符。AgentScope 的做法是把非法字符统一替换成 **`"x"` 而不是 `"_"`**，`_adapters.py` 里的真实源码：

```python
        # LLM providers enforce ^[a-zA-Z0-9_-]+$ on tool names.
        # mcp_name is validated in MCPClient.model_post_init;
        # tool.name comes from the MCP server and may contain dots,
        # colons, etc. — replace illegal chars with "x" (not "_")
        # to avoid collisions with the "__" separator.
        # self._tool.name retains the original for server-side calls.
        sanitized_tool = re.sub(r"[^a-zA-Z0-9_-]", "x", tool.name)
        self.name = f"mcp__{mcp_name}__{sanitized_tool}"
```

用 `x` 而不是 `_` 的理由写在注释里——避免混淆 `"__"` 这个分隔符。原始名字保留在 `self._tool.name`，回服务端调用时用。

### FunctionTool in Practice

把任意 Python 函数变成可被 Agent 调用的工具，只需包一层 `FunctionTool`，schema 从签名 + docstring 自动抽（可用 `Annotated[..., Field(...)]` 补约束），然后塞进 `Toolkit`：

```python
from pydantic import BaseModel, Field
from agentscope.agent import Agent
from agentscope.tool import FunctionTool, Toolkit
from agentscope.model import OpenAIChatModel
from agentscope.credential import OpenAICredential

def get_weather(
    city: str = Field(description="城市名，如 Hangzhou"),
) -> str:
    """查询指定城市的实时天气。"""
    return f"{city}: 晴 22°C"

tool = FunctionTool(
    func=get_weather,
    is_read_only=True,          # 只读 → 权限系统 fast path 直接 ALLOW，不弹确认
    # is_concurrency_safe 默认 True；is_state_injected 默认 False
)

agent = Agent(
    name="assistant",
    system_prompt="你是天气助手。",
    model=OpenAIChatModel(
        credential=OpenAICredential(api_key="sk-..."), model="gpt-4.1",
    ),
    toolkit=Toolkit(tools=[tool]),   # tools 接受 list[ToolBase]
)
```

两个关键点：① `description` 默认从 docstring 第一行抽，参数描述从 `Field(description=...)` 抽（纯 annotation 不带说明时 schema 只剩类型）；② `is_read_only=True` 让该工具在**所有五个 mode** 下都走 `read_only` fast path 直接 `ALLOW`，配合 `FunctionTool` 默认的 `check_permissions` 返回 ASK——即「只读默认放行、其它默认问」的语义落地到自定义函数上。`Toolkit` 还支持 `mcps=[...]`（直接挂 MCP client）和 `skills_or_loaders=[...]`（注册 skill 目录），三者统一进 `"basic"` 工具组，重名工具组会 `ValueError`。

### I/O Delegation: LocalBackend

13 个做 I/O 的内置工具「自己不做任何 I/O」不是比喻——真正的文件系统读写在 `tool/_builtin/_backend.py` 的 `LocalBackend`（`BackendBase` 的唯二实现之一，另一个是抽象基类）里。`Read` / `Write` / `Edit` / `Grep` / `Glob` / `Bash` 这类工具只负责三件事：

- **参数校验**：路径是否绝对、文件是否存在、命中数是否超额；
- **结果整形**：把 `LocalBackend` 返回的原始字节/字符串包成 `ToolChunk`；
- **缓存策略**：`read-before-write` 的 mtime 校验依赖 `AgentState.tool_context.read_file_cache`（LRU + 字节双限，见上）。

`LocalBackend` 持有进程内的实际句柄（如 `rg` 子进程、`open()` 文件描述符），工具层只调它的方法拿结果。这套分离的好处是——沙箱场景只需替换 `BackendBase` 的具体实现，把 I/O 转发到远端 workspace（见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md) 的 WorkspaceManager 后端矩阵），工具层的校验与整形逻辑一行不用动。

### Compression Tool

`CompressContext` 是 Agent 可以主动调用的压缩工具——设计动机是「在任务边界处（比如读完文档、还没开始写代码）压缩，比跑着跑着被强制压缩更准」。但它**并非自动注册**：`ContextConfig.compression_tool_enabled` 默认 `False`，且只在 `_prepare_model_input()` 里惰性 `add_tool`。权限是 `PermissionDecision(behavior=ALLOW, message="CompressContext is always allowed.")`，**没有** `bypass_immune=True`（该字段默认 False）——旧笔记这一条无出处。压缩流水线与记忆分层见 [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)。`compression_tool_enabled` 的真实定义：

```python
    compression_tool_enabled: bool = Field(
        default=False,
        description=(
            "Whether to expose a context compression tool to the agent. "
            "When runtime-state injection is enabled, the agent is prompted "
            "to use the tool between tasks as the context approaches the "
            "hard compression threshold."
        ),
    )
```



### ToolBase: The Protocol

`ToolBase`（`src/agentscope/tool/_base.py`）是三种实现的公共抽象。v2.0.11 下它暴露的属性全集（新增的外部执行契约见下一节）：

- 标识与契约：`name`、`description`、`input_schema`——`input_schema` 始终是 JSON schema，模型拿到的就是它；
- 安全布尔量：`is_concurrency_safe`、`is_read_only`；
- 执行形态：`is_external_tool=False`（外部工具走 Agent 透传、不实现 `__call__`）、`is_state_injected=False`（为 `True` 时由框架注入 `_agent_state`）、`is_mcp=False` / `mcp_name`；
- 危险路径白名单：`dangerous_files` / `dangerous_directories`（类属性，默认值见 `tool/_constants.py`，由 `_is_dangerous_path` 做大小写不敏感匹配）。

`ToolBase` 的类属性声明（连续一段）：

```python
    name: str
    """The name presented to the agent."""
    description: str
    """The agent-oriented tool description."""
    input_schema: dict[str, Any]
    """The input schema of the tool, following JSON schema format."""
    is_concurrency_safe: bool
    """If this tool is concurrency safe."""
    is_read_only: bool
    """If this tool is read-only, which will be used in the permission
    checking."""
    is_external_tool: bool = False
    """If this tool is an external tool, which doesn't need to implement the
    __call__ method and the agent will yield the external tool call event."""
    is_state_injected: bool = False
    """If this tool requires agent state to be injected when called. If `True`,
    the state will be injected by an argument named `_agent_state`. Note your
    tool should be able to accept such argument.
    """
    metadata_schema: dict[str, Any] | None = None
    """What an external executor must put in
    :attr:`~..message.ToolResultBlock.metadata`, as a JSON schema.

    The counterpart of :attr:`input_schema`: that one tells the model how
    to call the tool, this one tells whoever executes it how to answer.
    ``output`` stays whatever reads well to the model — this is the half
    a caller may depend on. ``None`` means nothing is promised."""

    is_mcp: bool = False
    """If this tool is an MCP tool, which will be used in the permission"""
    mcp_name: str | None = None
    """The name of the MCP server this tool belongs to, which is required if
    this tool is an MCP tool."""
```

**两个 override 点**是易错点：`ToolBase.call()` 是新版复写入口，子类应 override `call()` 而非 `__call__`；`__call__` 只负责把 `_middlewares` 串成洋葱链（`execute_chain`），并把 `call()` 的两种形态（async generator 或返回单个 `ToolChunk` / generator）统一成 `AsyncGenerator[ToolChunk, None]`。工具调用**必须**走关键字参数，传位置参数直接 `TypeError`。`call()` 的真实定义：

```python
    async def call(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ToolChunk | AsyncGenerator[ToolChunk, None]:
        """Execute the tool logic.

        This is the new override point for tool implementations.
        Subclasses should override this method instead of
        :meth:`__call__`.  The base implementation raises
        :exc:`NotImplementedError` for non-external tools and
        :exc:`RuntimeError` for external tools.
```

权限相关的几个方法：

- `check_permissions()` 是抽象方法，必须实现；
- `check_read_only(tool_input)` 默认返回静态 `is_read_only`，但**输入相关语义的工具会覆写**——`Bash` 静态标 `False`，却通过 `_bash_parser.is_read_only_command` 对 `ls`/`cat`/`git status` 之类判定为真。基类默认实现：

```python
    async def check_read_only(
        self,
        tool_input: dict[str, Any],
    ) -> bool:
        """Decide whether this specific invocation is read-only.

        Returns the static :attr:`is_read_only` attribute by default.
```

- `match_rule()` 决定是否匹配某条权限规则：`None` 表示「工具名级规则、匹配所有调用」，Bash/Read/Write/Edit/Glob/Grep 覆写以支持细粒度模式匹配；
- `generate_suggestions()` 由工具产出建议规则（文件工具建议父目录 glob、Bash 建议命令前缀），供权限系统提示用户一键放行。

### External Execution Contract

旧版分册整段 NOTE 断言 `AskUser` / `metadata_schema` / `check_external_result()` 「不存在」，在 v2.0.11 已全部反转，而且版本归属也写错了——它们是 **v2.0.9** 引入，不是 v2.0.10。

`ToolBase` 新增两个成员：`is_external_tool: bool = False`（外部工具无需实现 `__call__`）与 `metadata_schema: dict[str, Any] | None = None`（见上块）。后者的注释把语义写得很清楚：`input_schema` 告诉模型怎么调，`metadata_schema` 告诉**外部执行方怎么答**；`output` 保持「模型读起来顺」的自由文本，`metadata` 才是调用方可依赖的那一半，`None` 表示什么都不承诺。

`check_external_result(result)` 仅在 `metadata_schema` 非 None 且 `result.state == SUCCESS` 时用 `jsonschema.validate` 校验 `result.metadata`；抛 `ValidationError` 时 reply 保持 parked，允许执行方重发。全仓唯一调用点是 `Agent` 处理 `ExternalExecutionResultEvent` 的分支。真实判定：

```python
        if (
            self.metadata_schema is not None
            and result.state == ToolResultState.SUCCESS
        ):
            jsonschema.validate(result.metadata, self.metadata_schema)
```

首个内置消费方 `AskUser`（`tool/_builtin/_ask_user.py`）：`is_external_tool=True`、`is_read_only=True`、`is_concurrency_safe=True`，1–4 题每题 2–4 选项，`check_permissions` 恒 ALLOW，`metadata_schema = AskUserMetadata.model_json_schema()`，**故意不实现** `__call__` / `call`。其类定义里的真实属性：

```python
    input_schema: dict[str, Any] = AskUserParams.model_json_schema()

    metadata_schema: dict[
        str,
        Any,
    ] | None = AskUserMetadata.model_json_schema()

    is_read_only: bool = True
    is_state_injected: bool = False
    is_concurrency_safe: bool = True
```

执行侧在 ALLOW 后先把 tool call 置 `SUBMITTED`，再 yield `RequireExternalExecutionEvent` 并立即 return。

配套安全修复：`_is_dangerous_path` 改用 `os.path.realpath` 解析符号链接（原为 `abspath`）；offload 的 docstring 现在写 `workspace://` URL 而非 `file://`。

### ToolMiddlewareBase

工具中间件基类 `ToolMiddlewareBase` **就定义在 `tool/_base.py` 里**，并非独立文件。子类只需实现 `on_tool_call(tool, input_kwargs, next_handler)`，签名已固定：用 `next_handler(**input_kwargs)` 驱动内层，在其前后插入 pre/post 逻辑并 `yield` `ToolChunk`。类 docstring 与抽象方法：

```python
class ToolMiddlewareBase(ABC):
    """Base class for tool middlewares.

    A tool middleware wraps the execution of a tool in an onion fashion: the
    first registered middleware is the outermost layer and runs its pre-logic
    before any inner layer, then its post-logic after all inner layers have
    completed. Subclass this and implement :meth:`on_tool_call` — the signature
    is already spelled out, so second-party developers only need to fill in the
    body without reasoning about the wrapping protocol.

    Streaming and non-streaming tools are unified: ``next_handler`` always
    returns an async generator, so a middleware never needs to know whether the
    underlying tool yields a stream of chunks or returns a single chunk.
```

关键设计——**流式与非流式工具在中间件层被统一**：`next_handler` 永远返回 `AsyncGenerator[ToolChunk, None]`，中间件无需关心底层工具是逐块 yield 还是一次性返回。`ToolBase.__call__` 的 `execute_chain` 负责把这条链真正跑起来，第一个注册的中间件是最外层。抽象方法的签名：

```python
    @abstractmethod
    async def on_tool_call(
        self,
        tool: "ToolBase",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[ToolChunk, None]],
    ) -> AsyncGenerator[ToolChunk, None]:
```

### Built-in Tool Safety Matrix

内置工具的静态安全属性（来自各自类定义，见下表）；`check_permissions` 除 `ResetTools` / `SkillViewer` / 四个 Task 工具恒 `ALLOW` 外，`Bash` 走自己的多步判定（注入 / 只读 / 危险命令 / 危险路径等，自 `_bash.py` 起），其余文件工具默认交给权限引擎做规则匹配：

| 工具 | 文件 | `is_read_only` | `is_concurrency_safe` | `is_state_injected` |
| :--- | :--- | :--- | :--- | :--- |
| `Read` | `_read.py` | `True` | `True` | — |
| `Glob` | `_glob.py` | `True` | `True` | — |
| `Grep` | `_grep.py` | `True` | `True` | — |
| `Skill`（`SkillViewer`） | `_skill.py` | `True` | `True` | `True` |
| `Bash` | `_bash.py` | `False`（按调用覆写） | `False` | — |
| `PowerShell` | `_powershell.py` | `False` | `False` | — |
| `Write` | `_write.py` | `False` | `False` | — |
| `Edit` | `_edit.py` | `False` | `False` | — |
| `reset_tools`（`ResetTools`） | `_meta.py` | `False` | `True` | `True` |
| `TaskCreate`/`Get`/`List`/`Update` | `_task/_task_tool_base.py` | `False` | `True` | `True` |

读工具（Read / Grep / Glob）标 `is_read_only=True`，因此在权限系统的 read-only fast path 下**所有模式**直接 `ALLOW`；而 `Write` / `Edit` / `Bash` / `PowerShell` 都是 `is_concurrency_safe=False`，即不能安全并发（批处理时会被串行化）。`Bash` 虽静态 `is_read_only=False`，但 `check_read_only` 按命令内容判只读，让 `ls -a` 这类命令也走 fast path。

### Toolkit: Registration and Groups

`Toolkit` 是 Agent 取工具的唯一入口。`__init__` 把传入的 `tools` / `skills_or_loaders` / `mcps` **全部塞进一个名为 `"basic"` 的保留工具组**；`"basic"` 不允许出现在 `tool_groups` 参数里，否则 `ValueError`，重复组名同样 `ValueError`。状态式 MCP client 必须在构造时已连接。真实源码把「basic 保留」「重名报错」「状态式 client 校验」写在一起：

```python
        if tool_groups is not None and any(
            _.name == "basic" for _ in tool_groups
        ):
            raise ValueError(
                "The 'basic' tool group is reserved for the default tool "
                "group. Don't include 'basic' in the tool_groups argument "
                "when you also provide tools, skills or mcps in the "
                "constructor.",
            )

        self.tool_groups = [
            ToolGroup(
                name="basic",
                tools=tools or [],
                skills_or_loaders=skills_or_loaders or [],
                mcps=mcps or [],
            ),
        ] + (tool_groups or [])

        # Check name conflict for tool groups
        if len(set(_.name for _ in self.tool_groups)) != len(
            self.tool_groups,
        ):
            raise ValueError(
                "Tool groups must not contain duplicate tool groups.",
            )

        # The stateful MCP clients should be initialized already
        for group in self.tool_groups:
            for client in group.mcps:
                if client.is_stateful and not client.is_connected:
                    raise ValueError(
                        f"The MCP client '{client.name}' is stateful, but "
                        f"not connected.",
                    )
```

两个 meta tool 在构造时自动注册：

- `builtin_meta_tool = ResetTools`（注册名 `reset_tools`），其 `input_schema` 是**动态生成**的——从每个非 `basic` 组抽一个 `bool` 字段；
- `builtin_skill_viewer = SkillViewer`（注册名 `Skill`）。

`_get_available_tools(groups)` 是统一出口，规则是：`"basic"` 组永远包含；有 skill 时挂 `Skill`；**只有当存在至少一个非 `basic` 组时**才挂 `reset_tools`。各组的 MCP 工具通过 `client.list_tools()` 拉取——**单个 MCP client 拉取失败只 `logger.warning` 一行，绝不抛错中断整个回复**（注释明确「一个不可达的 MCP 不能把整轮对话拖垮」）。重名工具按组覆盖并告警。

Jinja2 模板的渲染时机：skill 指令模板（`skill_instruction_template`）**不是**在 skill 加载时渲染，而是在 `get_skill_instructions()` 里、准备挂到 system prompt 时才 `Template(...).render(...)`，渲染时把已注册的 skill 列表与 `Skill` 工具名喂进去。`call_tool` 真正执行时做状态注入——仅当 `is_state_injected and not is_mcp and not is_external_tool` 时把 `_agent_state` 作为关键字参数注入。

### FunctionTool Schema Extraction

`FunctionTool`（`_adapters.py`）把任意 Python 函数适配成 `ToolBase`。schema 来源有三级优先级：

1. 构造时显式传入 `input_schema`（可以是 JSON schema `dict`，也可以是 pydantic `BaseModel` 子类——后者经 `model_json_schema()` 再去掉 `title` 字段）；
2. 否则从函数签名 + docstring 自动抽：`description` 默认取 docstring 首段（`_extract_func_description`），`input_schema` 取 `_extract_input_schema`，约束可用 `typing.Annotated[_, Field(...)]` 表达；
3. 两者最终都经 `_remove_title_field` 去掉 pydantic 自动加的 `title`。

默认值与签名（`is_concurrency_safe=True` / `is_read_only=False` / `is_state_injected=False`）：

```python
    def __init__(
        self,
        func: Function,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict | type[BaseModel] | None = None,
        is_concurrency_safe: bool = True,
        is_read_only: bool = False,
        is_state_injected: bool = False,
        middlewares: list[ToolMiddlewareBase] | None = None,
        permission: PermissionDecision | None = None,
    ) -> None:
```

`check_permissions` 默认返回 `ASK`（除非构造时给了 `permission`）。`call()` 把函数返回值（str / 可 JSON 序列化对象 / `ToolChunk` / 同步或异步 generator）统一归一成 `ToolChunk` 或 `AsyncGenerator[ToolChunk, None]`。

### MCPTool

`MCPTool`（`_adapters.py`）包装 `mcp.types.Tool`。关键事实：

- `is_concurrency_safe` **默认 `False`**——与 `FunctionTool` 的默认 `True` 相反；
- `is_read_only` 从 server 返回的 `annotations.readOnlyHint` 抽，没有就 `False`；
- `is_state_injected` 硬编码 `False`，源码注释原话「The mcp tools is prohibited state injection for safety reason」——远端第三方工具不能接收框架注入的 `_agent_state`（见上块）；
- 连接分两类：`client_gen`（无状态，每次临时建 session）或 `session`（有状态），二者必须且只能给一个，否则 `ValueError`；
- 工具名清洗沿用现有规则：非法字符替换为 `"x"`（「Three Adapters」一节已给），原始名留在 `self._tool.name` 供回服务端调用；
- `call()` 走 `session.call_tool` 并把 MCP content 转成 `TextBlock` / `DataBlock`（`_convert_mcp_content_to_blocks`）。

### BashCommandParser: Source Map

现有「BashCommandParser: Real Parsing, Not Regex」一节已讲清它用 `tree_sitter_bash` 做真实 AST 解析；下表列出 `src/agentscope/tool/_builtin/_bash_parser.py` 的方法及其作用：

| 方法 | 作用 |
| :--- | :--- |
| `is_read_only_command` | 只读判定，喂权限 fast path |
| `extract_file_paths` | 提取涉及路径，用于 `suggested_rules` |
| `extract_redirections` | 提取重定向 |
| `extract_command_prefixes` | 提取命令前缀，用于建议规则 |
| `split_compound_command` | 递归拆 `&&` / `\|\|` / `;` / `\|` 复合命令 |
| `check_dangerous_command` | 危险命令表匹配（词边界） |
| `check_sed_constraints` | `sed` 原地编辑专项约束 |
| `check_injection_risk` | 注入风险检测（`$(...)` / `<(...)`） |

### BackendBase: Three Primitives

`BackendBase`（`tool/_builtin/_backend.py`）只有三个抽象原语，且**语义上区别于普通 shell 字符串**。`BackendBase` 的类 docstring 把这一点写明：

```python
class BackendBase(ABC):
    """Filesystem + subprocess interface consumed by builtin tools.

    Subclasses must implement three abstract primitives — ``exec_shell``,
    ``read_file``, and ``write_file`` — which are the only operations
    whose mechanism genuinely differs per environment.  The remaining
    filesystem helpers are implemented here on top of ``exec_shell`` and
    work for any backend whose shell is POSIX-like; a backend with a
    cheaper native path may override them (see :class:`LocalBackend`).
    """
```

`exec_shell(command: list[str], *, cwd, timeout)` 直接以 argv 列表起进程、**不经过 shell**，需要管道 / 重定向时由调用方自己包 `["/bin/sh", "-c", line]`；`read_file(path) -> bytes`、`write_file(path, data: bytes)` 读写原始字节。`exec_shell` 的真实签名：

```python
    @abstractmethod
    async def exec_shell(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
```

其余十余个能力全部在基类上**基于 `exec_shell` 的默认实现**（`LocalBackend` 重写为原生 `os.*` 更快更稳）：`getcwd`（跑 `pwd`）、`expanduser`（`printenv HOME`）、`file_exists`（`test -e`）、`is_dir`（`test -d`）、`list_dir`（`find -print0`）、`scandir`、`stat`、`stat_mtime`（GNU/BSD `stat` 双路回退）、`delete_path`（`rm -rf`）、`write_stream` / `read_stream`。

这个抽象的关键点在于 `_path_module` 与 `os_name` 两个类属性：`BackendBase` 默认用 `posixpath` / `"posix"`，`LocalBackend` 改成 `os.path` / `os.name`，从而让「Windows 宿主机驱动 Linux 容器」时路径处理与命令选择都落到正确环境。真实类属性：

```python
    _path_module: ModuleType = posixpath
```

```python
    os_name: str = "posix"
```

返回的 `ExecResult` 带 `exit_code` / `stdout` / `stderr`，`exit_code == 0` 即 `.ok()`；`LocalBackend.exec_shell` 对找不到的可执行文件返回 `127`、超时返回 `-1`。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [SOP](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) / [Classifier](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — tool/_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tool/_base.py)
- [AgentScope v2.0.11 — tool/_builtin/_ask_user.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tool/_builtin/_ask_user.py)
- `src/agentscope/tool/_base.py` / `_adapters.py` / `_builtin/`
- `src/agentscope/tool/_builtin/_backend.py`
- `src/agentscope/tool/_bash_parser.py`
