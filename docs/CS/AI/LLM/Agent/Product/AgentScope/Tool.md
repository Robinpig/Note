## Introduction

AgentScope 的工具体系把「参数校验 + 结果整形」与「真正 I/O」彻底分离：内置 13 个工具自己不做任何 I/O，全部委托 `BackendBase`；同一套 `ToolBase` 接口下有三种实现（手写类 / FunctionTool / MCPTool），统一走中间件洋葱链。本分册从主干笔记拆出，保留 v2.0.8 源码事实。主干与上层机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md) 与 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## Tool System

### Toolkit

`Toolkit` 是 Agent 可调用工具的唯一来源。构造时可以注册 Python 函数、MCP 连接、Skill。

工具的两个关键属性：
- `is_concurrency_safe` —— 能否安全并发执行（决定批处理策略）
- `is_read_only` —— 是否只读（权限系统的 fast path，只读调用永远 ALLOW）

这三个来源最后统一成 `Toolkit._get_available_tools()` 返回的 `dict[name, RegisteredTool]`——模型拿到的永远是同一套 JSON schema，不管工具是 MCP server 来的还是本地 Python 函数。

### Built-in Toolset

`tool/_builtin/` 下 9 个工具类，加上 `_task/` 里的 4 个任务工具，共 13 个。它们**自己不做任何 I/O**——全部读写委托给 `BackendBase`（`tool/_builtin/_backend.py`），工具只负责参数校验、结果整形和缓存策略：

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

`_bash_parser.py` 是整套内置工具里最意外的部分：它没有用正则匹配危险命令，而是挂了 **`tree_sitter_bash` 真语法解析**（`Parser(Language(tsbash.language()))`）。有了 AST 之后下面这些检查才立得住：

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

最后一行是条重要的安全边界——MCP 工具**禁止状态注入**（源码注释原话："The mcp tools is prohibited state injection for safety reason"）。[MCP](/docs/CS/AI/LLM/Protocol/MCP.md) server 是远端第三方，让它的工具签名接受框架注入的内部状态等于开了一条数据外泄通道。

**MCP 工具改名规则**是个容易忽略的硬约束：LLM 厂商强制工具名匹配 `^[a-zA-Z0-9_-]+$`，而 MCP server 返回的名字可能带 `.` `:` 之类字符。AgentScope 的做法是把非法字符统一替换成 **`"x"` 而不是 `"_"`**：

```python
# tool/_adapters.py:246
sanitized_tool = re.sub(r"[^a-zA-Z0-9_-]", "x", tool.name)
self.name = f"mcp__{mcp_name}__{sanitized_tool}"
```

用 `x` 而不是 `_` 的理由写在注释里——避免混淆 `"__"` 这个分隔符。原始名字保留在 `self._tool.name`，回服务端调用时用。

### Compression Tool

`CompressContext` 是 AgentScope 自动注册的内置工具。Agent 可以主动调它来压缩——设计动机是「在任务边界处（比如读完文档、还没开始写代码）压缩，比跑着跑着被强制压缩更准」。这个工具的调用是 `PermissionDecision(ALLOW, bypass_immune=True)`，永远允许。



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [AgentScope 中间件分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- `src/agentscope/tool/_base.py` / `_adapters.py` / `_builtin/`
- `src/agentscope/tool/_builtin/_backend.py`
- `src/agentscope/tool/_bash_parser.py`
