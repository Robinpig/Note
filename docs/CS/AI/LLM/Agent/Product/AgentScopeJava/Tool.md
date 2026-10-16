## Introduction

本分册覆盖 AgentScope Java 执行链路上的四块机制：**工具体系**（`Toolkit` 与三种工具写法、MCP）、**权限系统**（五模式 + 规则 DSL + 工具自带检查）、**中间件**（三类 hook 六个扩展点）与 **Plan Mode**（阶段级工具白名单）。四者的共同点是都挂在「一次工具调用怎么被放行、怎么被执行、怎么被拦截」这条路上，合册阅读最能看清整条链路。

与 Python 版的差异值得一提：Python 版中间件是 7 个 hook 反射自动检测，Java 版是 6 个扩展点显式声明 `activePoints()`；Python 版权限的安全 ASK 靠 `bypass_immune` 标记，Java 版靠 `checkPermissions` 不可绕过 + 危险路径强制 ASK 两层。

## Toolkit

三个概念：**Tool**（实现 `AgentTool` 接口的对象，或带 `@Tool` 注解的普通类——后者称 reflective function tool，由 `Toolkit#registerTool(Object)` 反射注册）、**Toolkit**（容器，注册 tool / MCP 客户端 / skill，向模型暴露 JSON schema，分发每次调用）、**Tool Group**（一组带名称的 tool / MCP / skill，可整体激活或停用，Agent 运行时用内置 meta tool 切换，保持上下文聚焦）。

```java
Toolkit toolkit = new Toolkit();
toolkit.registerTool(new TodoTools());      // 通过反射注册带 @Tool 的方法
toolkit.registerTool(new MyCustomTools());  // 自定义工具类
```

只调 `registerTool(Object)` 时，所有 `@Tool` 方法进特殊的 **`"basic"` 组**——该组始终激活。出现额外 tool group 或 skill 时，Toolkit 自动注册 `reset_tools` meta tool 与 `load_skill_through_path`，无需手动实例化。

## Java Tool

`ToolBase` 是 `AgentTool` 的抽象实现。向 agent 与运行时描述工具的属性：`getName()` / `getDescription()` / `getParameters()`（JSON Schema）/ `isConcurrencySafe()` / `isReadOnly()` / `isExternalTool()` / `isStateInjected()` / `isMcp()` / `getMcpName()`。接入执行与权限的方法：`checkPermissions(toolInput, context)`（必需，返回 `Mono<PermissionDecision>`）、`matchRule(ruleContent, toolInput)`（可选，权限规则自定义匹配）、`generateSuggestions(toolInput)`（可选，生成建议规则）、`callAsync(param)`（可选，返回 `Mono<ToolResultBlock>`，外部执行工具不实现）。

### Annotation Style

最轻量写法——`@Tool` + `@ToolParam`，框架自动从 Java 类型推导 JSON schema：

```java
public class SimpleTools {
    @Tool(name = "get_current_time", description = "Returns the current time in a given IANA timezone.",
          readOnly = true, concurrencySafe = true)
    public String getCurrentTime(
            @ToolParam(name = "timezone", description = "IANA timezone, e.g. Asia/Shanghai") String timezone) {
        return LocalDateTime.now(ZoneId.of(timezone)).format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
    }
}
```

`@Tool` 常用属性：`name`（默认方法名）/ `description` / `readOnly`（默认 false）/ `concurrencySafe`（默认 true）/ `stateInjected`（注入 `AgentState` 参数）/ `dangerousFiles` / `dangerousDirectories`（追加危险路径）/ `converter`（自定义返回值到 `ToolResultBlock` 的转换器）。

**执行状态要显式返回**：成功用 `ToolResultBlock.success(text)`、失败用 `ToolResultBlock.error(message)`，不要靠文本前缀判断失败；`ToolResultBlock.text(text)` 默认是 RUNNING，保留既有 JSON / 多行输出要用 `withState(...)` 明确终态。

### ToolBase Style

需要自定义权限策略、外部执行或复杂 schema 时继承 `ToolBase`，重写 `checkPermissions` 与 `callAsync`：

```java
public class WebSearchTool extends ToolBase {
    public WebSearchTool() {
        super(ToolBase.builder().name("WebSearch")
                .description("Search the web for information on a given query.")
                .inputSchema(Map.of("type", "object",
                        "properties", Map.of("query", Map.of("type", "string",
                                "description", "The search query.")),
                        "required", List.of("query")))
                .readOnly(true).concurrencySafe(true));
    }

    @Override
    public Mono<PermissionDecision> checkPermissions(Map<String, Object> toolInput, PermissionContextState context) {
        return Mono.just(PermissionDecision.allow("Web search is read-only."));
    }

    @Override
    public Mono<ToolResultBlock> callAsync(ToolCallParam param) {
        String query = (String) param.getInput().get("query");
        return doSearchAsync(query).map(text -> ToolResultBlock.builder()
                .id(param.getId()).name(getName())
                .output(List.of(TextBlock.builder().text(text).build())).build());
    }
}
```

### External Execution Tool

`externalTool(true)` 且不实现 `callAsync`：Agent 调用时发 `RequireExternalExecutionEvent` 并暂停，外部（人工操作员或外部系统）完成后回传匹配的 `ToolResultBlock`，agent 发 `ExternalExecutionResultEvent`（`replyId` 相同）后继续。这是 human-in-the-loop 工作流的基础。

### Receiving Context

`RuntimeContext` 自动透传到所在 reply 内每一次工具调用。注解式工具里**没有 `@ToolParam` 的参数**按优先级解析：`ToolEmitter`（流式中间产物）→ `Agent` → `AgentState`（经 `RuntimeContext.getAgentState()`）→ `RuntimeContext` → `ToolExecutionContext`（已废弃兼容层）→ 用户自定义 POJO（`runtimeContext.get(ParamType.class)`，即调用方 `put(ParamType.class, value)` 注册的对象）。自定义 POJO 的判定：无 `@ToolParam`、非基本类型、非 ContentBlock / Msg、不在 `java.*` / `javax.*` 包下——模型不需要把它写进 JSON 参数，schema 里也不出现。

`ToolEmitter.emit()` 发布中间进度（`ToolProgressEvent`，仅展示）；`emitter.getToolCallId()` 可把进度与前端状态关联。`ToolBase.callAsync` 则通过 `ToolCallParam` 取 context。

### MCP

MCP 客户端经 `McpClientBuilder` 构建后 `toolkit.registerMcpClient(...)`，list 到的工具包装成统一 `ToolBase`（`isMcp=true`）：

```java
McpClientWrapper amap = McpClientBuilder.create("amap")
        .streamableHttpTransport("https://mcp.amap.com/mcp?key=" + System.getenv("AMAP_API_KEY"))
        .buildAsync().block();
toolkit.registerMcpClient(amap).block();
```

工作区根目录的 `tools.json` 也可声明式配置 MCP server + 工具白名单，build 时一次性读取，`${ENV_VAR}` 语法做环境变量替换。注意 **allow / deny 在所有工具注册完之后才应用**，用 allow 列白名单时要一并列出要保留的内置工具。

## Permission System

权限回答「Agent 能不能调某个工具、在什么条件下调」。引擎评估产出 `PermissionDecision`：`allow(message)` / `deny(message)` / `ask(message)` / `passthrough(message)`——PASSTHROUGH 表示「工具不强加判断，交给引擎按 rules / mode 评估」。

### Five Modes

| Mode | 行为 | 适用场景 |
| :--- | :--- | :--- |
| `DEFAULT` | 所有操作都需要显式规则或用户确认 | 最安全，推荐默认值 |
| `ACCEPT_EDITS` | 自动放行工作目录内的文件操作 | 用户在场的活跃开发 |
| `EXPLORE` | 只读：放行读、拒绝所有写与命令 | 代码探索、规划 |
| `BYPASS` | 放行一切（deny / ask 规则仍生效） | 完全可信的沙箱 |
| `DONT_ASK` | 把所有 ASK 转为 DENY | 无人值守 / 计划任务 |

初始化经 `permissionContext(PermissionContextState.builder().mode(...).build())`；运行期可用 `agent.setPermissionMode(ctx, PermissionMode.BYPASS)` 翻转（保留该 session 已配规则，重建缓存的权限引擎，下一次 call 生效；进行中的 call 仍用启动时的引擎）。BYPASS 会关闭所有规则评估，应作为显式的按 session 主动操作并配合沙箱；想要无人值守且不弹确认但仍保留管控，用 `DONT_ASK`。

### Permission Rule

`PermissionRule`（record）把 tool + 调用模式映射到 ALLOW / DENY / ASK / PASSTHROUGH：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `toolName` | String | 规则适用的 tool 名（必填） |
| `ruleContent` | String \| null | 匹配模式，语义由该 tool 的 `matchRule()` 解释；null 表示匹配该 tool 所有调用 |
| `behavior` | PermissionBehavior | ALLOW / DENY / ASK / PASSTHROUGH |
| `source` | String | 规则来源：userSettings / projectSettings / session / suggested |

```java
PermissionContextState permCtx = PermissionContextState.builder()
        .mode(PermissionMode.DEFAULT)
        .addAllowRule("safe_read", new PermissionRule("safe_read", null, PermissionBehavior.ALLOW, "userSettings"))
        .addAskRule("dangerous_delete", new PermissionRule("dangerous_delete", null, PermissionBehavior.ASK, "userSettings"))
        .addDenyRule("drop_table", new PermissionRule("drop_table", null, PermissionBehavior.DENY, "userSettings"))
        .build();
```

ASK 决策会基于本次调用自动生成**建议规则**（挂在 `PermissionDecision` 上，权限钩子可见），把已接受的规则附在 `ConfirmResult.acceptedRules` 回传即写入引擎，今后相同调用自动放行。

### Built-in Checks: The Non-bypassable Layer

每个 tool 的 `checkPermissions(toolInput, context)` 在运行时基于真实入参执行检查，**无论 mode 或 rules 是什么都生效**。`ToolBase` 内置的危险路径列表（`ToolDangerousPathConstants`）覆盖 shell 配置（`.bashrc` / `.zshrc`）、git 配置、SSH 密钥、凭证文件（`.env` / `.npmrc` / `.aws/credentials`）与 `.git/` `.ssh/` `.aws/` `.kube/` 目录——**命中后即使在 BYPASS 模式下也强制 ASK**。自定义工具可在 `@Tool` 上追加 `dangerousFiles` / `dangerousDirectories` 并入受保护集合。

### HITL Integration

引擎返回 ASK 时 agent 暂停并发 `GenerateReason.PERMISSION_ASKING` 的响应。`call` 模式从返回 `Msg` 里筛 `ToolCallState.ASKING` 的 `ToolUseBlock`；`streamEvents` 模式直接收 `RequireUserConfirmEvent.getToolCalls()`。恢复方式相同：`ConfirmResult` 附在新消息 metadata（`Msg.METADATA_CONFIRM_RESULTS`）里再次 call。拒绝全部工具时默认继续下一轮推理（模型只看到 "Permission denied by user"，易产生无效推理）——要停止得装备一个 `onActing` middleware 观察 `AllToolsDeniedEvent` 并发 `RequestStopEvent`，此后 `Msg.getGenerateReason()` 返回 `ALL_TOOLS_DENIED`。无人值守场景用 `DONT_ASK` + allow 规则：只放行显式列出的命令，其余静默拒绝。

## Middleware

中间件在 agent 生命周期的固定点位拦截行为。三类形态：

- **Onion（洋葱式）**——包裹下一层 handler，可在 `next.apply(input)` 前后插逻辑、用 Reactor 算子观察 / 改写中间事件流。
- **Transformer（变换式）**——middleware 串成流水线，前一个输出是后一个输入，无「内层」概念。
- **Notification（通知式）**——单向同步通知，无 next 委托，固定点位按序执行。

嵌套关系（`onSystemPrompt` 嵌在 `onReasoning` 内，因为它在组装 system prompt 时触发）：

```
onAgent/
├── onAgentStateReady（call 级 AgentState 就绪，输入尚未进入流水线）
└── ReAct loop（每一轮）/
    ├── onReasoning/
    │   ├── onSystemPrompt（组装 system prompt）
    │   └── onModelCall（模型 API 调用）
    └── onActing（每次工具调用）
```

同一个 middleware 类可实现六个位置中任意子集（未实现的 Onion / Transformer 位置默认直通 `next.apply(input)`，通知式默认无操作），传给 builder 的 `middlewares(...)` 即可装备。`onActing` 只包裹 agent 运行时内部的工具执行，external execution 在 agent 外部执行的工具不被追踪。

### Built-in Middleware

| 中间件 | 作用 |
| :--- | :--- |
| `OtelTracingMiddleware`（`io.agentscope.core.tracing`） | 全生命周期 OpenTelemetry：`invoke_agent` 包裹整次 reply、`chat` 包裹每次模型调用、`execute_tool` 包裹每次工具执行。未配 SDK 时所有 hook 短路直通，近零开销。构造时（首次）会注册 JVM 级 Reactor hook 做跨线程 span 传播——**要在组装需要传播的管道之前先构造** |
| `TaskReminderMiddleware` | 配合 `enableTaskList(true)`，每个 reasoning step 前把 `AgentState.tasksContext` 渲染成 `<system-reminder>` 注入，防长任务偏离计划 |
| `FinalAnswerFilterMiddleware` | 只输出 ReAct 最终轮次文本，中间轮次文本被缓冲到模型调用结束（只有未观察到工具调用才能确认是最终轮） |

### Custom Middleware

实现 `MiddlewareBase`，只重写需要的 hook 并用 `activePoints()` 声明：

```java
public class FullObservabilityMiddleware implements MiddlewareBase {
    @Override
    public Set<ExtensionPoint> activePoints() {
        return EnumSet.of(ExtensionPoint.ON_AGENT, ExtensionPoint.ON_REASONING,
                ExtensionPoint.ON_MODEL_CALL, ExtensionPoint.ON_SYSTEM_PROMPT);
    }

    @Override
    public Flux<AgentEvent> onReasoning(Agent agent, RuntimeContext ctx,
            ReasoningInput input, Function<ReasoningInput, Flux<AgentEvent>> next) {
        return next.apply(input).doOnComplete(() -> System.out.println("[reasoning] end"));
    }

    @Override
    public Mono<String> onSystemPrompt(Agent agent, RuntimeContext ctx, String currentPrompt) {
        return Mono.just(currentPrompt);
    }
}
```

Harness 的自定义 middleware 注意：用 `.middleware(...)` 会跑在所有 Harness 内置 middleware **之前**；读身份走 `RuntimeContext`，写工作区必须用 `harnessAgent.getWorkspaceManager()`——直接 `java.nio.Files` 在沙箱 / 远端模式下会写错地方。

## Plan Mode

Plan Mode 是**阶段级工具白名单 + HITL 退出**：只读思考阶段写计划，获批后才进执行阶段。本质是「用计划文件把『想清楚』与『做出来』解耦」，实现上完全靠工具放行名单。

三个工具：`plan_enter`（进入）/ `plan_write`（写计划到 `plans/PLAN.md`）/ `plan_exit`（退出到执行阶段，HITL 确认）。`plan_write` 是专门设计的写入入口——避开把通用 `write_file` 加进白名单的安全风险。中间调用非白名单工具会被即时拒绝，模型看到 `PlanModeMiddleware.DENY_MESSAGE` 原文后自然切回「先写计划」。

Builder：`enablePlanMode()` / `planFileDirectory(String)` / `allowShellInPlanMode()`。**默认禁 shell**——shell 是双用途工具，同一次调用可能是读（cat / ls / grep）也可能是写（rm / npm install），而 Plan Mode 只按工具名判定；放开后专用文件编辑工具（`write_file` / `edit_file`）仍被拒，只读保证比默认情况弱，建议配合沙箱文件系统。

运行终态有四态，`isPlanModeActive() == false` 是有歧义的——从未进入（合法决定）/ 进入并退出成功 / 仍在 plan 且有 PLAN.md（待批准）/ 仍在 plan 且无 PLAN.md（只说不做），要在代码里区分得同时记录是否调用过 `plan_enter` / `plan_write`。程序化入口：`agent.enterPlanMode(ctx)` / `exitPlanMode(ctx)` / `isPlanModeActive(ctx)`；配了 admin starter 还有对应 HTTP 接口。

Plan Mode 状态随 `AgentState` 持久化（进程重启、跨副本恢复后仍在），计划文件写工作区 `plans/` 跟随 filesystem 模式。Plan Mode 期间 spawn 的子 agent 自动继承只读限制。与 `todo_write` 的分工：Plan Mode 管阶段与计划文件，`todo_write` 管执行阶段的结构化清单（全量替换语义，必须恰好一个 in_progress），典型工作流是 plan 写完 → plan_exit → todo 拆解 → 逐条推进。

## Links

- [AgentScope Java 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [AgentScope Java 智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [AgentScope Java 技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)
- [Permission Theory](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Tools Protocol](/docs/CS/AI/LLM/Protocol/Tools.md)
- [MCP Protocol](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [AgentScope Java 工具](https://java.agentscope.io/v2/zh/docs/building-blocks/tool)
- [AgentScope Java 权限系统](https://java.agentscope.io/v2/zh/docs/building-blocks/permission-system)
- [AgentScope Java 中间件](https://java.agentscope.io/v2/zh/docs/building-blocks/middleware)
- [AgentScope Java 计划模式](https://java.agentscope.io/v2/zh/docs/harness/plan-mode)
