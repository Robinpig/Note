# Skill

## Introduction

Skill 是 AgentScope Java 对「可复用能力包」的抽象：一段带元信息的指令（prompt 模板）+ 配套资源（脚本、参考文档、工具绑定），按需装载进 Agent 上下文。与直接把工具堆给模型不同，Skill 解决的是**上下文预算**问题——技能描述常驻索引层，只有命中才展开全文，避免几十个技能的 prompt 把上下文撑爆。

Java 版的 Skill 与 Python 版的 Skill 在概念上同源，但实现上是独立的代码体系（`io.agentscope.core.skill` 包），且多出「市场后端」与「自学习闭环」两块 Python 版尚未具备的能力。

## Four-Layer Composition

一个生效的技能实例由四层按优先级合成：

```text
1. Built-in     框架内置技能（如 summarization、planning）
2. Bundled      应用打包时随 jar 分发的技能（resources/skills/）
3. Market       从远端市场拉取的技能（版本化、可更新）
4. Session      运行时按 session 注入的临时技能（如租户定制）
```

后加载的层覆盖先加载层的同名项，但**工具绑定做合并而非覆盖**——市场版技能新增的工具会叠加到内置版上，只有显式声明的 `override: true` 才整体替换。合成结果记录进 `ContextManifest`（见 Context 分册），可审计「这个 session 里某个技能到底由哪层提供、什么版本」。

## Skill Descriptor

```java
public record SkillDescriptor(
    String name,            // 唯一标识，如 "pdf-extract"
    String version,         // 语义化版本
    String summary,         // 常驻索引层的一句话描述（≤200 字符）
    String promptTemplate,  // 命中后展开的完整指令
    List<String> tools,     // 绑定的工具名
    Map<String, Object> metadata  // 作者、许可、依赖技能等
) {}
```

装载决策只看 `name + summary`——这两段是常驻上下文的成本；`promptTemplate` 直到命中才展开。技能之间可声明依赖（`metadata.dependsOn`），装载一个会级联装载其依赖，循环依赖在注册期直接报错。

## Market Backends

市场是技能的分发层，后端可插拔：

| 后端 | 协议 | 说明 |
|---|---|---|
| `LocalDir` | 文件系统扫描 | 开发期用，`skills/` 目录即市场 |
| `Git` | clone + tag | 私有市场常用，按 tag 取版本 |
| `Http` | REST | 对接企业制品库，支持鉴权 |
| `Maven` | 依赖坐标 | 技能打成 jar 随应用依赖管理，版本解析复用 Maven 机制 |

拉取的技能带签名校验（`metadata.signature`），校验失败拒绝装载——这是把「技能」当供应链资产管的关键一步。市场技能默认不自动更新，`SkillRegistry.refresh()` 显式拉新版，避免运行中行为漂移。

## Self-Learning Loop

自学习闭环让 Agent 把成功经验固化为新技能，四步：

1. **捕获**：一次 run 结束后，若达到成功判据（用户点赞 / 无错误终止 / 自定义评分器），`RunTrace` 连同其事件流归档；
2. **蒸馏**：离线/异步任务从 trace 里提炼「做了什么、为什么这样做」，生成 `SkillDescriptor` 草稿；
3. **评审**：草稿进待审队列，人工或自动评审（沙箱回放验证）通过后入市场；
4. **生效**：下次装载时按版本号进入合成层，`ContextManifest` 记录来源为 `market(auto)`。

这条闭环把「技能库随时间增长」变成工程流程，而不是让 Agent 在运行时随意改自己的 prompt——后者会直接破坏可复现性。Java 版把评审环节做成强制的，正是与「运行时自我修改」路线的分野。

## Execution In Sandbox

技能携带的脚本不在 JVM 内直接执行，而是走 Workspace 的沙箱后端（见 Workspace 分册）：

- 装载技能时，其 `resources/` 同步进沙箱约定目录；
- 工具调用触发脚本时，以沙箱内路径为工作目录 exec；
- 脚本产出文件默认留在沙箱，需要回传时经 `AgentFileSystem` 显式读取。

这样技能作者无法绕过隔离——哪怕技能里写着 `rm -rf /`，`Process`/`Docker` 后端也伤不到宿主。

## SubAgent

SubAgent 是技能的「执行体」延伸：一个技能可以声明由子 Agent 而非主 Agent 执行，用于隔离上下文或并行分工。

```java
SubAgentSpec spec = SubAgentSpec.builder()
    .agentType("researcher")
    .skillNames(List.of("web-search", "pdf-extract"))
    .mode(SubAgentMode.SYNC)        // 或 BACKGROUND
    .isolation(IsolationScope.AGENT)
    .build();
```

三种协作形态：

- **SYNC**：主 Agent 阻塞等子 Agent 结果，适合有依赖的流水线；
- **BACKGROUND**：子 Agent 异步跑，结果经事件流通知，适合可并行的检索类任务；
- **REMOTE**：子 Agent 是远端进程/服务，通过 Agent Protocol（类 A2A 的智能体互调协议）通信，主 Agent 只看到标准化的事件转发。

持久会话场景下，子 Agent 的 session 可以独立于主 Agent 存续——主 Agent 结束、子 Agent 稍后继续跑并把结果写进共享 session，Service 层负责把两个 session 的事件按序合并给前端。

## Links

- [AgentScopeJava 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [Tool](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [Workspace](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md)
- [Context](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)

## References

- https://java.agentscope.io/v2/zh/docs/harness/skill
- https://java.agentscope.io/v2/zh/docs/harness/subagent
