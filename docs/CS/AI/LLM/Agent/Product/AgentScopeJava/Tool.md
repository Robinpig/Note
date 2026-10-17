# Tool

## Introduction

本分册覆盖 AgentScope Java 执行链路上的四块机制：**工具体系**（`Toolkit` 与三种工具写法、MCP）、**权限系统**（五模式 + 规则 DSL + 工具自带检查）、**中间件**（5 个 hook）与 **Plan Mode**（阶段级工具白名单）。四者的共同点是都挂在「一次工具调用怎么被放行、怎么被执行、怎么被拦截」这条路上，合册阅读最能看清整条链路。

本分册所有类名、方法签名、枚举值与默认值均核对自本地 `v2.0.4` 源码树（`agentscope-core/.../tool/`、`.../permission/`、`.../middleware/`、`.../state/PlanModeContextState.java`，`agentscope-harness/.../middleware/`），与官方文档冲突处以源码为准。

与 Python 版的差异值得一提：Python 版中间件是 7 个 hook 反射自动检测，Java 版是 **5 个 hook**（4 洋葱 + 1 管道）+ `order()` 显式排序；Python 版权限的安全 ASK 靠 `bypass_immune` 标记，Java 版靠 `checkPermissions` 的 bypass-immune 求值次序 + 危险路径强制 ASK 两层。

## Toolkit And Tool Registration

`Toolkit` 是工具总入口，两类注册 API（`tool/Toolkit.java`）：

```java
// 1. 流式 builder（registration() 返回 ToolRegistration）
toolkit.registration()
        .tool(toolObject)                       // POJO，反射 @Tool 方法
        .agentTool(agentTool)                   // AgentTool 实例
        .mcpClient(mcpClientWrapper)            // MCP 客户端
        .subAgent(provider)                     // 子 Agent 提供者（可带 SubAgentConfig）
        .mcpToolNamePrefix(prefix)              // MCP 工具名前缀
        .enableTools(List.of(...))              // 只启用列出的工具
        ...;

// 2. 直接方法
public void registerTool(Object toolObject);
public void registerAgentTool(AgentTool tool);
public Mono<Void> registerMcpClient(McpClientWrapper wrapper);   // 异步：要握手
public Mono<Void> removeMcpClient(String name);
public void closeMcpClients();
public void registerMetaTool();
public Toolkit copy();
```

工具组（运行时切换，配合元工具）：`createToolGroup(name, desc, active)`、`registerToolGroup(ToolGroup)`、`addToolToGroup(group, tool)`、`updateToolGroups(names, active)`、`setActiveGroups(...)` / `getActiveGroups()`、`removeToolGroups(...)`、`createSkillToolGroup(...)`、`findSkillToolGroupsByActivateOnSkill(skillName)`。

执行侧：`callTool(ToolCallParam)` → `Mono<ToolResultBlock>`、`callTools(...)` 三个重载、`setChunkCallback(BiConsumer<ToolUseBlock, ToolResultBlock>)`、`isExternalTool(name)`、`getToolSchemas(Collection<String> activeGroups)`。

⚠️ `copy()` 的语义要读注释（`Toolkit.java:928-946`）：**构建期隔离用，不要 per-call 用**。用户工具实例按引用共享（必须线程安全），工具组与激活标志深拷贝；框架元工具重新绑到新 registry。per-call 的工具面差异应该用 `ToolRequestConfig` 组合表达（`getTool(name, requestConfig)` / `getToolSchemas(groups, requestConfig)`），而不是拷贝 toolkit。

### Three Ways To Write A Tool

| 写法 | 基类/注解 | 适用 |
| :--- | :--- | :--- |
| 注解反射 | POJO 方法打 `@Tool` | 最常用，框架反射生成 schema |
| 继承 `ToolBase` | `public abstract class ToolBase implements AgentTool` | 要自定义 `checkPermissions` / `matchRule` / `generateSuggestions` |
| 直接实现 `AgentTool` | 接口 | 完全手工（元工具、远程代理就是这么写的） |

`@Tool` 注解的**全部 11 个属性**（`tool/Tool.java`）：

```java
String name() default "";
String description() default "";
boolean strict() default false;                    // schema 严格模式
boolean readOnly() default false;                  // EXPLORE 模式放行判据
boolean concurrencySafe() default true;
boolean externalTool() default false;              // 外部执行（HITL 挂起）
boolean stateInjected() default false;             // 注入 AgentState 参数
boolean returnDirect() default false;              // 结果直接作为 agent 回复
String[] dangerousFiles() default {};              // 追加危险文件
String[] dangerousDirectories() default {};        // 追加危险目录
Class<? extends ToolResultConverter> converter() default DefaultToolResultConverter.class;
```

`ToolBase` 的关键方法：`getName()` / `getDescription()` / `getParameters()`（均 final）、`isConcurrencySafe()` / `isReadOnly()` / `isReturnDirect()` / `isExternalTool()` / `isStateInjected()` / `isMcp()`、`callAsync(ToolCallParam)`、`checkPermissions(input, context)`、`matchRule(ruleContent, toolInput)`、`generateSuggestions(toolInput)`、`isDangerousPath(filePath)`。

### Meta Tool

**只有一个元工具，名字是 `reset_equipped_tools`**（`tool/MetaToolFactory.java:51`，`Toolkit.registerMetaTool()` 注册，日志原文 "Registered meta tool: reset_equipped_tools"）。它的语义是**替换而非增量**——javadoc 原文强调「The input list is the FINAL set of active tool groups, not incremental changes. Any group not included in the list will be deactivated」，并建议「只激活当前任务需要的、用完立刻停用以节省上下文空间」。参数 `to_activate`（数组，enum 只含 **META scope** 的组名）。

`ToolGroupScope` 两值决定谁能动一个组（`tool/ToolGroupScope.java:29-42`）：**META**（元工具可管，进 enum、跟替换语义）与 **EXTERNAL**（只归开发者代码管，元工具看不见也改不了）。

## Permission

### Five Modes

`PermissionMode`（`permission/PermissionMode.java:33-38`）5 值，JSON 值小写：

| 枚举 | JSON | 行为（javadoc 原文） |
| :--- | :--- | :--- |
| `DEFAULT` | `default` | 所有操作都要求显式 allow 规则 |
| `ACCEPT_EDITS` | `accept_edits` | 工作目录内的文件编辑自动放行 |
| `EXPLORE` | `explore` | 只读模式，修改类工具一律 DENY |
| `BYPASS` | `bypass` | 不求值规则，全部放行 |
| `DONT_ASK` | `dont_ask` | ASK 决策降级为 DENY（无人值守跑） |

`PermissionBehavior`（`PermissionBehavior.java:32-36`）4 值：`ALLOW` / `DENY` / `ASK` / **`PASSTHROUGH`**（工具把决策踢回引擎做规则匹配）。

### Evaluation Order

`PermissionEngine.checkPermission(ToolBase tool, Map<String,Object> toolInput)` → `Mono<PermissionDecision>`（`PermissionEngine.java:139-178`），六步次序，**引擎构造时把规则快照进自己的可变表，原始 context 永不被修改**；`addRule()` 可在运行时扩充：

```text
1. deny 规则            （最高优先级）
2. ask 规则             （命中时挂上 tool.generateSuggestions(input) 的建议规则）
3. 工具自带检查          （bypass-immune：EXPLORE/ACCEPT_EDITS 只读处理 + 危险路径 + ToolBase.checkPermissions）
4. allow 规则
5. BYPASS 模式兜底
6. 默认 ASK（DONT_ASK 模式下变 DENY）
```

第三步的 bypass-immune 体现在：即使 `BYPASS` 模式，工具自带检查仍先于 allow 规则求值——`continueAfterToolCheck()` 里的 BYPASS 兜底排在工具检查之后（`:188-196`）。工具返回 `PASSTHROUGH` 时引擎走空（`Mono.empty()`）继续往后匹配（`:222-224`）。

模式与只读判定：`EXPLORE` 下 `tool.isReadOnly()` 为真才 ALLOW，否则 DENY；`ACCEPT_EDITS` 下只读工具直接 ALLOW，非只读继续走后续步骤（`checkExploreMode`，`:229-263`）。

### Rule DSL

`PermissionRule` 是个四字段 record（`PermissionRule.java:33-37`）：

```java
public record PermissionRule(
        @JsonProperty("tool_name")     String toolName,        // 目标工具，非空
        @JsonProperty("rule_content")  String ruleContent,     // 工具特定的匹配模式，可空
        @JsonProperty("behavior")      PermissionBehavior behavior,
        @JsonProperty("source")        String source) {}       // 如 "userSettings" / "suggested"
```

**匹配语义（`ruleMatches`，`PermissionEngine.java:310-316`）**：

```java
String content = rule.ruleContent();
if (content == null || content.isEmpty()) {
    return true;                          // 规则内容为空 = 对该工具的所有调用生效
}
return tool.matchRule(content, input);    // 否则交给工具自己的匹配器解释
```

也就是说**规则内容的语法由工具定义**，引擎不解释——`ToolBase.matchRule` 是扩展点。规则按 `toolName` 分三个表（allow / deny / ask）存，命中即返回对应 `PermissionDecision`（带 `message` 与 `decisionReason`，如 `"Rule: " + rule.ruleContent()`）。

### Dangerous Paths

`ToolDangerousPathConstants`（`tool/ToolDangerousPathConstants.java`）三张默认表：

- `DEFAULT_DANGEROUS_FILES`（23 项）：shell rc（`.bashrc` / `.zshrc` / `.profile` …）、`.ssh/config`、`.ssh/authorized_keys`、`.netrc`、`.npmrc`、`.pypirc`、`.gitconfig`、`.gitmodules`、以及 8 个 `.env*` 变体（`.env` / `.envrc` / `.env.local` / `.env.development[.local]` / `.env.test[.local]` / `.env.staging` / `.env.production[.local]`）。javadoc 明确「Aligned with Python `tool/_constants.py`」。
- `DEFAULT_DANGEROUS_DIRECTORIES`（4 项）：`.git` / `.vscode` / `.idea` / `.ssh`——路径中**任何一段**命中即算敏感。
- `DANGEROUS_COMMANDS`（11 项）：`rm -rf` / `sudo rm` / `dd` / `mkfs` / `fdisk` / `format` / `chmod 777` / `chmod -R 777` / `chown -R` / `kill -9` / `> /dev/`。

⚠️ 一个覆盖语义坑（类 javadoc 原文）：「Tools that override the fields on `ToolBase` **replace the defaults entirely rather than appending to them**」——子类覆写 `dangerousFiles` / `dangerousDirectories` 是整体替换，不是追加，容易把默认保护悄悄关掉。

`ToolBase.isDangerousPath(filePath)` 是引擎第三步调用的判定入口；`@Tool(dangerousFiles=...)` / `@Tool(dangerousDirectories=...)` 则让单个工具方法自带额外清单。

### External Execution And Suspend

标记 `@Tool(externalTool = true)`（或 `SchemaOnlyTool` 注册）的工具不在框架内执行：抛 `ToolSuspendException`（`tool/ToolSuspendException.java`）把执行权交出去，框架发 `RequireExternalExecutionEvent`，结果由调用方回传，见 [智能体分册 HITL](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)。

## Middleware

`MiddlewareBase` 是**接口**（`middleware/MiddlewareBase.java:59`），提供 **5 个 hook**，分两种模式：

**洋葱型（4 个，before/after 包裹）**：

```java
default Flux<AgentEvent> onAgent(Agent agent, RuntimeContext ctx, AgentInput input,
                                 Function<AgentInput, Flux<AgentEvent>> next);
default Flux<AgentEvent> onReasoning(Agent agent, RuntimeContext ctx, ReasoningInput input,
                                 Function<ReasoningInput, Flux<AgentEvent>> next);
default Flux<AgentEvent> onActing(Agent agent, RuntimeContext ctx, ActingInput input,
                                 Function<ActingInput, Flux<AgentEvent>> next);
default Flux<AgentEvent> onModelCall(Agent agent, RuntimeContext ctx, ModelCallInput input,
                                 Function<ModelCallInput, Flux<AgentEvent>> next);
```

**管道型（1 个，顺序变换字符串）**：

```java
default Mono<String> onSystemPrompt(Agent agent, RuntimeContext ctx, String currentPrompt);
```

排序：`order()` 默认 **1**，数值越大越靠外层（`2` 在 `1` 之前执行），同级保持 builder 注册顺序。所有 hook 默认直接委托 `next`，子类只覆写关心的。

一个高价值细节写在 `onModelCall` 的 javadoc 里（`:127-131`）：**中间件对返回流中 `TextBlockDeltaEvent` 的变换会反映进最终回复消息**，因此可以在原生结构化输出解析之前归一化模型文本。

配套输入类型：`AgentInput`（消息）、`ReasoningInput`（消息 + 工具 + 选项）、`ActingInput`（工具调用）、`ModelCallInput`（消息 + 工具 + 选项 + model）、`MiddlewareChain`。

### Built-in Middleware

**core 两个**：`FinalAnswerFilterMiddleware`（最终答复过滤）、`TaskReminderMiddleware`（任务提醒）。

**harness 二十个**（`agentscope-harness/.../middleware/`，按职责分组）：

| 分组 | 类 |
| :--- | :--- |
| 上下文与压缩 | `CompactionMiddleware`（onReasoning，阈值超限时 5 步压缩）、`ToolResultEvictionMiddleware`（超大工具结果卸载到文件系统）、`WorkspaceContextMiddleware`（onSystemPrompt 注入 AGENTS.md / MEMORY.md / knowledge） |
| 记忆 | `MemoryFlushMiddleware`（onAgent 的 doOnComplete，fire-and-forget 抽取事实）、`MemoryMaintenanceMiddleware`（周期维护：过期日文件归档 + LLM 合并，节流执行） |
| 技能 | `HarnessSkillMiddleware`（harness 原生技能合成，onSystemPrompt 渲染 `<available_skills>`）、`SkillUsageMiddleware`（ SkillBox 技能调用计数，只记 `created_by="agent"`/`"agent-draft"`）、`SkillCuratorMiddleware`（call 结束后调度 curator，单线程守护Executor，不阻塞 agent loop）、`DynamicSkillMiddleware`（core 侧 legacy，已被 HarnessSkillMiddleware 取代） |
| 子 Agent 与团队 | `SubagentsMiddleware`（默认模式造 `AgentSpawnTool` + `DefaultAgentManager`；session 模式注入外部 `SessionsTool` 替换之）、`DynamicSubagentsMiddleware`（每轮推理重新解析子 agent 集合，两层加载）、`SubagentEntry`、`TeamsMiddleware`（注入 AgentTeams 上下文 + 角色裁剪的 `TeamTool`） |
| 输入与信箱 | `AtPathExpansionMiddleware`（展开用户消息里的 `@path`，追加 `<attached_file>`）、`InboxMiddleware`（每轮推理前 drain 信箱，以 `HintBlock` 注入并发 `HintBlockEvent`）、`AsyncToolMiddleware`（acting 超时的工具转后台，占位结果 + 完成推送 inbox） |
| 运行时与沙箱 | `HarnessRuntimeMiddleware`（框架装配标记，`fromAgent(...)` 不复制）、`SandboxLifecycleMiddleware`（每次 call 前后借还沙箱会话、4 分支工作区初始化）、`TranscriptMiddleware`（每次 call 结束持久化 transcript，独立于 memory flush） |
| 可观测 | `AgentTraceMiddleware`（INFO 摘要 / DEBUG 详单） |

`DynamicSubagentsMiddleware` 的两层加载值得单记（javadoc）：**Layer 1（override）** `filesystem.glob("*.md", "subagents")` + 逐文件 read，后端的 `NamespaceFactory` 透明生效，每个用户看到自己的覆盖；**Layer 2** 继承静态声明。

中间件要动态注册工具时，必须用 `Agent.getToolkit()` 拿**运行时 toolkit**（`Agent.java:101-113` javadoc 原文提醒：agents may deep-copy the toolkit during construction，build 时捕获的引用可能不是 agent 实际用的那个）。

## Plan Mode

`PlanModeContextState`（`state/PlanModeContextState.java:37-40`）只有两个字段，但存放位置是关键：

```java
private boolean planActive;
private String currentPlanFile;   // workspace 相对路径，markdown 蓝图
```

类 javadoc 说明了为什么它在 `AgentState` 里而不是进程内存：「agentscope agents are distributed and resumable: a plan-mode session must survive process restarts and hand-offs across nodes. Toggling the flag and persisting the `AgentState` is therefore the canonical way to switch modes dynamically at runtime.」

执行者是 `PlanModeMiddleware`（harness），javadoc 原文要点：

- 求值发生在 **`onActing`**，且是确定性的；
- 放行条件：**只读工具**，或计划控制工具之一（`plan_enter` / `plan_write` / `plan_exit` / `todo_write`）；
- 其余工具得到一条**合成 `DENIED` tool result**（写进上下文并作为事件流出）而不真正执行；
- 刻意**不复用 `PermissionMode`**——计划模式是阶段级约束，与权限模式正交。

计划文件落 `plans/PLAN.md`（可用 `.planFileDirectory("design-docs")` 改路径），跨调用保留；Plan Mode 下 spawn 的子 Agent 会自动继承只读限制，详见 [技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)。

## MCP And Tool Groups

`mcp/` 包：`McpClientManager`（客户端生命周期）、`McpClientWrapper`（`Toolkit.registerMcpClient` 的参数）、`RegisteredToolFunction` / `ReflectiveFunctionTool` / `SchemaOnlyTool` / `MetaToolFactory` / `SimpleExtendedModel` / `ExtendedModel`（扩展模型能力）、`ToolExecutor` / `ToolMethodInvoker`（反射调用）、`ToolSchemaGenerator` / `ToolSchemaModule` / `ToolSchemaProvider`（JSON Schema 生成）、`SkillToolGroup`（技能工具组）、`ToolMergeMode`。

工具组相关：`ToolGroup`、`ToolGroupManager`（`replaceMetaActiveGroups(toActivate)` 是元工具的落点、`getMetaGroupNames()`、`isActiveTool(name, activeGroups)`）、`ToolGroupScope`（META / EXTERNAL）、`ToolkitConfig`（`parallel` 默认 **true**——同一轮多个同步工具调用并行推进）。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [AgentScope Java 工具](https://java.agentscope.io/v2/zh/docs/building-blocks/tool)
- [AgentScope Java 权限系统](https://java.agentscope.io/v2/zh/docs/building-blocks/permission-system)
- [AgentScope Java 中间件](https://java.agentscope.io/v2/zh/docs/building-blocks/middleware)
- [AgentScope Java Plan Mode](https://java.agentscope.io/v2/zh/docs/harness/plan-mode)
