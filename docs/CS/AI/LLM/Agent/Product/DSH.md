> 版本基线：核实于 2026-10-06。架构 / 权限 / 沙箱 / 工具细节以官方子系统文档与 `deepseek-harness` 源码（`main` 分支）为准；base bundle 共 94 个插件条目。

## Introduction

DeepSeek AI 开发的开源 agent harness（智能体框架）。构建于**一切皆插件**的架构之上，由 [Cordis](https://github.com/cordiverse/cordis) 驱动，设计论文：[*A Programming Paradigm for Spatiotemporal Composability*](https://arxiv.org/abs/2608.25512)

> 一句话理解：Cordis 维护一张**运行时插件图**（系统现在由什么组成），Session 维护一份**追加式事件流**（系统刚才做过什么）；Agent loop 位于两者之间——从插件图取能力，写回事件流。

## Installation

### Run via npm

安装 Node.js 后：

```sh
npm install -g @deepseek-ai/dsh   # 或免安装直接 npx
npx @deepseek-ai/dsh web
```

- 默认在 `http://127.0.0.1:3080` 启动 Web UI，本机启动时会自动用默认浏览器打开页面
- 通过 SSH 启动时只打印宿主机 URL（本地转发地址由 SSH 客户端或编辑器持有）
- `--no-open`：仅运行服务器，不打开浏览器
- `dsh --dump-config`：输出最终的插件配置树——这才是该机器实际运行的系统（排障入口）

### Run from Source

```sh
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

`pnpm run build` 准备仓库产物；`pnpm dsh web` 直接使用已构建产物，不重新构建。

## Architecture

DeepSeek Harness（简称 dsh）的架构采用**"一切皆插件"（Everything is a Plugin）**的设计哲学，核心公式：**Model + Harness = Agent**。整体架构可以从以下几个层次来理解。

### Cordis Microkernel Layer

最底层是 DeepSeek 自研的 Cordis 插件框架，只负责三件事：

1. 插件生命周期管理（加载 / 卸载 / 依赖解析）
2. 依赖注入
3. 全局事件总线

Cordis 不含任何模型、工具或 UI 逻辑；支持热重载与副作用自动回收——插件卸载时，其注册的服务和事件会被自动回滚。

但"一切皆插件"有一个前提：**一切*产品能力*皆由插件贡献，Cordis 自身仍保留插件得以存在的机制**（上下文代理、Fiber 状态机、服务存储、事件总线、Loader 属于元层）。更准确的说法是：内核不拥有模型、工具和循环等产品特权。

Cordis 真正有辨识度的地方，在于它**同时处理了五个通常彼此分离的问题**：

1. **可见性**：插件在当前位置能看到哪些能力
2. **依赖等待**：必需能力未出现时插件是否启动（Fiber 保持 PENDING）
3. **隔离**：同名 service 在不同会话/作用域解析到不同实现（isolate/realm）
4. **生命周期**：插件退出时注册项、监听器、进程和句柄由谁清理（effect/disposer）
5. **动态装配**：静态配置如何变成可更新、可检查的运行时插件树

### Seven-Layer Onion Model

架构从外到内依次为七层，**各层仅依赖内层**：

| 层 | 职责 |
| --- | --- |
| 应用表面层 | Web UI / CLI / Headless 等入口 |
| Profile 组合层 | 决定启动哪种产品形态 |
| 能力接缝层（Capability Seam） | 服务定义 → Provider → Consumer 的三角色模式 |
| 核心脊柱层 | Session、System Prompt、Tools、Agent、Agent Loop、Scope 六大核心包 |
| Cordis 框架层 | 插件引擎 |
| 基础设施层 | 文件系统、子进程、Jobs 等 |
| 外部运行时层 | 沙箱、MCP、LSP 等外部协议 |

能力接缝层的三角色模式（capability seam）是替换能力的关键：

- **Service Definition**（服务定义）：稳定调用协议，如"文件能力 = 读取/列目录/写入/编辑"
- **Service Provider**（提供方）：接入本地目录、远程沙箱等具体实现
- **Consumer（消费方）**：把能力变成模型可见工具（read/write/edit）

底层从本机文件系统换成沙箱时，模型工具和 Agent Loop 都不用变化；未来换远程环境同样只需替换 Provider。

### Eight-Layer Pluggable Business Plane (HPA Model)

在业务层面，所有 Agent 能力均被拆分为独立插件：

| 层 | 说明 |
| --- | --- |
| 模型层（Model） | 支持 DeepSeek V4 Pro/Flash 及近 40 家模型提供方，通过适配器插件切换 |
| 工具层（Tool） | 文件系统、Shell、MCP 等能力通过工具注册表管理 |
| 技能层（Skill） | 以 YAML/Markdown 定义的多步骤流程封装 |
| 会话层（Session） | 管理多轮上下文，含压缩、裁剪策略 |
| 沙箱层（Sandbox） | 文件效果隔离（read-only / workspace-write / danger-full-access），网络与进程可见性不在其词汇内 |
| 存储层（Storage） | Agent 记忆与状态持久化 |
| 主循环层（Loop） | Agent Loop 本身也是可替换插件 |
| 调度层（Scheduling） | 任务编排、子 Agent 协作与并发控制 |

当前仓库的基础配置一次加入 **94 个插件条目**（`packages/bundle/base/cordis.patch.yml`，仓库 pushed 2026-10-03；早期记录写的 78 已过期），覆盖模型、会话、工具、文件系统、沙箱、审批、Skill、子 Agent、工作流、压缩和遥测等能力。

### Configuration Is Assembly

DSH 不只是开发时扩展，更具备**部署时装配**能力。三层配置概念：

- **Bundle**：分发一组 Cordis 配置和对应插件代码
- **Profile**：决定进程堆叠哪些 Bundle（内置 `web` 与 `headless`）
- **Patch**：替换或插入配置行，用于用户配置和命令行覆盖

Loader 加载顺序（非模糊合并，后层按 id **整块替换**或插入）：

```
空 entry list
→ Profile 声明的 Bundle
→ Profile 自身 cordis.patch.yml
→ Harness home 下的 patch
→ 命令行 --patch
→ （关 telemetry 时）launcher 叠加 override
```

整块替换要求用户重述保留字段，略显笨重，却避免深度合并规则在数组、表达式和删除语义上制造歧义。配置热更新失败时，Loader 会恢复**最后一棵可用的插件树**（Group 并发启动收集全部结果，一项失败即删除新增项并重建旧配置）——接近配置事务，但不等同于数据库事务（外部副作用无法回滚）。

### Two Independent Composition Axes

- **Runtime Profile**（进程级）：`web`（Web 应用）/ `headless`（一次性 runner）
- **Agent Preset**（会话级）：`standard` / `code` / `minimal` / `cordis` 四种内置

两者是**正交的两条轴**：一个 Web 进程可同时承载不同 preset 的会话。Preset id 写入 Session header，恢复会话必须重组合同一组合。官方"四种模式"（Standard/PTC/Minimal/Creation）属于 per-session preset，不是互斥的进程启动方案。

四种 preset 的精确差异：

| Preset | 内容 |
| --- | --- |
| `standard` | 完整 coding agent 工具组合 |
| `code`（PTC） | 保留标准工具，增加 `tool-presentation` 以 Code Mode 暴露——模型看 `run_code` 与 TS SDK；是协议层改变，不是第二套调度循环 |
| `minimal` | 完整 persona，仅持久 Bash 与 `str_replace_editor`；不加载 compaction。⚠️ **2026-10-05 核实：`minimal.patch.yml` 里已完全没有 fs 相关插件**（早期记录说它提供裸 `fs-local` 已失效），且 base 配置已改用 `fs-sandbox` 而非 `fs-local` |
| `cordis` | 标准之上增运行时检查与临时插件管理；动态 package 存于共享进程内存，重启消失；执行生成 JS 近 Shell 权限，非安全隔离 |

### Key Design Mechanisms

- **事件溯源会话**：仅追加（Append-only）日志记录全链路，支持恢复、Fork 与回放；**"模型可见即已记录"（Model-visible means logged）**——进入模型请求的输入必须能从 session log 重建，插件不能偷偷改 prompt 而不留会话事实
- **分层叠加配置**：官方 Bundle → Profile Patch → 机器级 Patch → 命令行 Patch，逐层覆盖（见上文"配置即装配"）
- **四种预设模式**：本质是加载不同的插件组合（见上文 Preset 表）
- **多 Agent 编排**：Supervisor-Worker 层级，Fork（继承历史上下文）与 Spawn（新建上下文）两种子 Agent 派生机制
- **动态不毁缓存**：插件重装只要 system prompt、tool schema、历史前缀不变，LLM 前缀缓存依然命中；surface 变化（工具集改、提示词改写、模型切换、compaction）会让失效，但 compaction 是**局部**失效——只从第一个被替换的历史 token 起失效，该范围之前的前缀仍可复用

### Core Differentiators

与传统 Agent 框架"稳定核心 + 扩展插件"的模式不同，DeepSeek Harness 的核心本身也被完全拆解——**没有特权内核**（There is no privileged core to patch），连驱动 Agent 运转的主循环也只是默认插件实现之一。这种设计使得同一套运行时可以组合出不同产品形态，但也带来了较高的理解和调试成本。

**"一切皆插件"的边界**：Cordis 根 Context 构造时直接创建根 Fiber、Reflect、Registry、Events、Logger service；Session 运行对象、Boot、部分 UI 启动代码不能由尚未建立的插件图解释。它描述的是应用能力的组织方式，不是递归的字面事实。

**收益**：组合方式统一；生命周期成为一等问题；依赖晚绑定按位置替换（realm 级隔离）；模式是组合而非主程序分叉；运行时可检查、可试验。

**成本**：静态代码 ≠ 实际系统（需看最终配置树排障）；动态依赖放大因果链（Provider 变化触发 Consumer 卸载重载交错）；可逆 ≠ 事务；插件化 ≠ 安全（`inject` 不阻同进程直导 Node API）；vendor Cordis 带来元框架维护成本；性能代价缺量化基准。

## Cordis

> 参考：[Cordis 教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)（概念参考见 [Cordis 入门](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-primer)，API 见 [Cordis 核心 API](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-api/context)）

### Positioning

Cordis 是 DeepSeek Harness **底层的插件框架**：一个 TypeScript 编写的小型运行时（元框架，Meta-Framework of Spatiotemporal Composability），每项能力——工具、LLM 适配器、文件访问乃至 agent loop 本身——都是挂载到**共享上下文（Context）**中的插件。

- 由开发者 Shigma 于 2022 年创建，其 GitHub 资料显示已加入 DeepSeek
- Cordis 不提供业务功能，只提供**组织功能的方式**：谁提供能力、谁使用能力、何时启动、如何退出、不同场景加载哪组能力
- DSH 把 Cordis 源码放进 `vendor/`（固定上游提交、包名重映射到 `@deepseek-ai`），本地修改包含 Fiber 重入卸载加固、配置更新事务、HMR 精确监听、延迟配置解析——增加维护成本，换来框架层的可审计性

与面向 harness 的插件（`cordis.yml` 加载、Web UI 驱动）不同，Cordis 教程用单文件启动器在临时目录中动手构建，**无需 API 密钥**。

### Runtime Environment

```sh
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness && pnpm install

mkdir -p tmp/cordis-tutorial   # tmp/ 已被 git 忽略
cd tmp/cordis-tutorial
node --import tsx ../../vendor/cordis/bin.js   # 每一章都用这条命令
```

启动器（`vendor/cordis/bin.js`）创建根 `Context`、挂载 Loader 插件，从当前目录加载 `./cordis.yml`——有哪些插件、如何配置，全部来自 YAML 文件。`--import tsx` 让 Node 免构建直接运行 TypeScript。

### Context: A Shared "Capability Service Desk"

`ctx` 是**经 Proxy 包装的 service 解析边界**，不是装满单例的对象：

- 服务通过稳定名称出现在 `ctx` 上（`ctx.llm` / `ctx.tools` / `ctx.sessions`）；调用方只关心"我要模型能力"，不关心背后是哪家模型、哪个 SDK
- 未在 `inject` 中声明就读取 `ctx.foo` 会报错；`ctx.get("foo")` 底层读取不受限（显式接受服务可能不存在）
- 子 Context 通过原型继承父级 service，隔离映射按层遮蔽，局部配置无需复制整棵容器
- **依赖约束 ≠ 权限控制**：原生 JS 插件仍在宿主进程执行，未注入 `fs` 不代表 OS 层失去文件访问

### Fiber: Plugin Instances and State Machines

Plugin 是定义，**Fiber 是挂载实例记录**：父 Context、原始配置、解析后配置、依赖实现快照、生命周期状态、disposables。

- 依赖未就绪 → Fiber 保持 `PENDING`；就绪后进入 `LOADING` → `ACTIVE`；启动失败 → `FAILED`
- **配置文件条目顺序不承担启动顺序，依赖关系才承担**——解决了传统插件系统遍历数组依次 `init` 的隐含顺序顽疾
- Provider 消失或换实现时，Fiber 身份变化刷新依赖 epoch，触发旧 Consumer 卸载与新重载。Cordis 维护的是**随 Provider 变化刷新的运行图**，不是启动一次解析完的 DI 容器
- 卸载时按注册**逆序**执行清理并等待异步清理达到静止（quiescence）；单次 effect 内 disposer 逆序串联，**多个 Fiber 顶层 effect 是并发清理**（非严格 LIFO 栈）
- vendor 版本还处理重入边界：effect 执行 setup 前先登记所有者包装；同步卸载观察者；异步 cleanup 期间其他调用者可等待同一次清理；`UNLOADING` 状态拒绝创建新 effect

### Spatial Composition: isolate and dsh-scope

两层空间模型，分别解决"哪个服务实例"和"哪些注册项可见"：

- **`isolate` / realm（实例隔离）**：为指定服务名创建 realm 标签，服务注册和查找以标签定位——同名服务可在不同子上下文各自存在。两个 Agent 访问 `ctx.tools` 可得各自目录。适合**替换提供方**
- **`dsh-scope`（注册可见性）**：用不透明对象作 scope key，维护父子关系，创建带路由身份的事件 receiver。注册视图沿父链**向下**继承（Agent 看到 preset 的提示词和工具），事件沿链**向上**接纳（preset 级监听器收到其下 Agent 事件，兄弟 Agent 互不串线）

Agent preset 是空间组合的完整应用：preset 配置挂在长期存在的 scope 下，相同 preset 的并发首次挂载通过 single-flight 共享；文件变化后新会话加入新一代组合，已有会话保留原代际（避免会话中途换工具/提示词，代价是旧代际保留到整棵运行时退出）。DSH 还会**审计 preset 子树是否把服务发布到 root realm**——发布则拒绝挂载，防止会话级组合退化成进程全局状态。

### Time Composition: effect and Configuration Transactions

- 每次 `ctx.effect()` 登记 disposer，资源获取与释放写在同一 effect，防失配；`ctx.on()`、`ctx.provide()` 都接入 effect 所有权
- 与 React Hooks 对照：`useEffect` 把 cleanup 存进 Hook 链表，Cordis 把 disposer 存进 Fiber——都是"框架持有所有权，作者只声明建立/撤销"
- **可逆 ≠ 事务**：disposer 只能补偿，无法回滚外部世界（已发网络消息、已写共享文件不回滚）；未登记的进程/句柄不会自动消失
- **插件不仅要插得进去，还要拔得干净**；"谁创建，谁清理"不是约定，而是 Cordis 管理的运行时规则——这才让热更新和能力替换变得可信

### Event Contract: Five Dispatch Modes

插件间不只靠服务调用（那会把所有扩展变成接口方法），Cordis 同时提供类型化事件：

| 模式 | 行为 | DSH 中的用例 |
| --- | --- | --- |
| `emit` | 同步通知，忽略返回值 | 普通通知 |
| `parallel` | 并发执行，等全部完成 | 广播 |
| `serial` | 顺序执行，遇首有效结果停止 | `agent/turn-stopping` |
| `bail` | `serial` 的同步版 | 校验类拦截 |
| `waterfall` | 监听器拿到 `next()`，包裹/改写/短路余下链路 | `agent/pre-step`、`agent/request`、`llm/stream`、工具执行前后 |

- **waterfall ≈ Koa 中间件链**：审批插件可在工具执行前拒绝，重试插件可包围模型流，日志插件可观察前后——"流程"与"策略"分离，新增安全规则不用重写 Agent 大脑
- waterfall 最易出错：只想记日志的监听器忘调 `next()` 会短路整条能力链。DSH 把"必须调用 next()"写进项目级规则
- **事件的持久性被刻意分层**：`agent/*`、`tools/*` 是活跃运行时的拦截；会话事件追加日志承担恢复/fork/回放。一切皆插件 ≠ 一切皆事件——直接能力调用放 Service，策略拦截放实时事件，需持久化的事实进 session log

### Comparison with Historical Precedents

- **Eclipse**：扩展点/扩展由宿主清单定义；DSH 连 agent loop 和 UI 都可替换，核心与第三方插件共享同一挂载机制
- **OSGi**：动态服务注册表 + bundle 生命周期已有先例；Cordis 的新意是把动态依赖、作用域上下文、effect 所有权压进一个很小的进程内模型（执行单元是 Fiber——一个函数或 Service 子类即可，而非重量级 bundle）
- **DI 容器**：服务解析不陌生；新组合来自 **DI 与生命周期的绑定**——普通容器只构造对象，定时器/监听器/子进程仍由业务代码清理，Cordis 把注册动作收敛成 effect

### TypeScript Essentials

- **类型注解**（`ctx: Context`、`who: string`、`string[]`）：只描述值，不改变运行时行为
- **`import type { Context } from '@deepseek-ai/cordis'`**：仅导入类型信息，运行时消失，不增加运行时依赖
- **声明合并** `declare module '@deepseek-ai/cordis' { ... }`：为已有接口添加条目（如 `ctx.greeter` 的类型、事件名），**不产生任何运行时接线**，插件须另行提供服务或发出事件
- 第 5 章还会用到 `interface`（描述配置字段）和 `Schema<Config>`（泛型，表示 schema 校验的对象字段）

## Agent Loop and Session

### Default AgentLoop

默认 loop 依赖五项 service：`["agents", "sessions", "llm", "tools", "systemPrompt"]`。主流程：

```
输入进入 inbox
  → turn/start
  → 领取 next-step input 与一条排队消息
  → 读取 prompt sections 与 tool schemas
  → agent/pre-step 接纳、拒绝或改写输入
     → 拒绝：turn/end（blocked），不产生 step
     → 接纳：
       step/start
       → user/message 写入会话日志
       → deriveMessages() 投影模型历史
       → agent/request → llm/stream
       → assistant/chunk* → assistant/message
       → tool/call* → tools/pre-execute → tools/execute → tools/post-execute → tool/result*
       → step/end（仍有工具后续或 next-step input：进入下一 step）
  → agent/turn-stopping
  → turn/end
```

### Five-Layer Boundary of Termination Semantics

生产环境里 `while (hasToolCalls)` 远远不够——结束判断是 Agent Loop 最难的部分（它为什么继续、谁允许它继续、失败后还能不能继续、恢复后应不应该继续）。DSH 把结束拆成五层：

1. **模型请求结束**：Provider 流式输出完成（正常停止/工具调用/最大 token/错误/取消）
2. **step 结束**：一次模型调用 + 该响应发起的一整批工具执行；step 结束不代表 turn 结束（通常欠一次模型回访）
3. **turn 结束**：需同时满足 ①模型不欠回复（无未收口 tool call）②`next-step` inbox 无待处理输入——由"**模型债务 + 消息债务**"共同决定
4. **driver activity 结束**：一个 driver 连续处理多个 turn，队列耗尽回 idle
5. **长期工作流结束**：Goal Driver 监听 idle 检查持久 Goal 开启新 turn；idle 只描述当前 activity，不回答长期目标是否完成

与 Pi 的层级映射：DS step ≈ Pi turn；DS driver activity ≈ Pi invocation。Pi 保留更扁平的循环（steering/follow-up 暴露成回调，复杂度交宿主），DSH 把状态分层、事件日志作重建依据——适合多插件、持久恢复和长期任务。

### Turn / Step State Machine Details

- Driver 入口 `while (await this.turn())`；phase 状态机 `idle / maintenance / running`；`maintenance` 锁存维护期到来的唤醒意图，维护后查 inbox 决定是否重启（解决竞态）
- 领输入前写 `turn/start`，必有唯一 `turn/end` 收口（即使被 pre-step 拒绝或消息为空）
- `step()` 判断顺序（不可改）：`max-tokens` → 返回（**即使有 tool call 也不执行**，防截断 JSON 副作用）→ 无 tool call → `completed` → 有 tool call 执行整批 → 批次 declared concluded → `completed` → 普通批次 → `null`（欠回复，非错误）
- **max-tokens 粘性**：某 step 达上限后，即使后续 step 正常，`turn/end` 仍保留 `max-tokens`——记录整个 turn 的质量，防监控丢失截断事实
- **停止钩子 `agent/turn-stopping` 无布尔返回**：插件向 `next-step` inbox 写消息表示继续。数据驱动消除多插件布尔合并的优先级冲突，代价是学习成本高但可审计

### Tool Consolidation and Ordered Commit

- **收口聚合（OR）**：任一已提交结果 `concludesTurn === true` → 整批 concluded。软收口，取消模型回访债务但不压消息债务，并行工具继续跑——适合权威工具（如取得用户最终决定）。Pi 用 **AND 聚合**（全部 `terminate: true` 才终止），更保守，防单工具吞掉其他结果
- **并行执行、顺序提交**：scheduler 维护 `slots`，工具并行跑，但提交严格按模型调用顺序（`commitReady()` 连续提交就绪 slot）——保证日志/replay/插件观察顺序稳定
- **取消三原则**：①停止补充未启动调用 ②清空已启动调用 ③为跳过的工具写合成错误结果（配对 `tool/call` + `tool/result(error)` 维持协议）；已启动工具可能产生副作用，等 settle 按序提交
- **TurnEndReason 结构化 union**：`completed / blocked / max-tokens / aborted / error / interrupted`（最后者由持久化恢复层产生，闭合进程崩溃留下的开放 turn）；Pi 主要用 provider 的 `stopReason`

### Goal Outer Loop

Round Driver 监听 idle → 检查 Goal 有效/phase active/round 上限 → 构造 goal user message 开新 turn。**持久 phase（active/complete/blocked/paused）与进程内 activation（armed/disarmed）分离**：恢复后 active Goal 默认 disarmed，需人工授权（fail-safe）。Goal 收尾：先 `update_goal` 改持久状态并注入收尾指令，模型生成总结后 turn completed——解决"状态完成"与"用户看到输出"的时间差。

### Session Persistence Design

#### Two Sources of user/message

消息来源有两种：**用户直接输入**和**插件注入的上下文**。

- 插件注入：① 通过 inject 直接注入一条 UserMessage；② 通过 `systemPrompt.context` 注册动态上下文，Agent 在发送消息给 LLM 前拼接系统提示词时注入
- 用户输入有三种注入方式：

| 方式 | 语义 | 是否唤醒 Agent |
| --- | --- | --- |
| `followup` | 下一个 turn 进入，进消息队列等待 | 立即唤醒 |
| `steer` | 消息补充，进入下一个 step（类似 Codex 中 Cmd+Enter 强插消息） | 立即唤醒 |
| `inject` | 与 steer 类似，但**静默**，不主动唤醒 | 否 |

#### Why tool/call Is Defined Separately

`assistant/message` 输出的调用指令与 `tool/call` 内容非常相似，为何不直接让 `assistant/message` 和 `tool/result` 结对？——设计层面：`assistant/message` 是**模型输出节点**，`tool/call` 是**工具执行前置条件**。不拆出来，执行链路就"隐性"藏在代码后面；显式拆分后节点变多但链路更清晰，且：

- 工具执行时间戳独立，崩溃恢复有据可查
- 配对的 `tool/call` / `tool/result` 降低消息格式错误导致模型调用失败的概率

#### request/header: Incremental Recording of Request Parameters

```ts
export interface EpochHeader {
  config: LlmCallConfig
  adapterDefaults?: LlmCallConfigAdapterDefaults
  system?: string        // 系统提示词
  tools?: ToolSchema[]   // 工具定义
}
export interface LlmCallConfig {
  provider: string
  model: string
  reasoningEffort?: ReasoningEffortId
  temperature?: number
  maxTokens?: number
  stop?: string[]
}
```

除 messages 外几乎一次完整 LLM 请求参数的记录。**变动时才追加写入**，多次请求复用同一份内容——省空间且保留了每次请求的完整上下文快照。

#### Plugin Extension Point Events (9)

| 事件 | 模式 | 作用 |
| --- | --- | --- |
| `system-prompt/assemble` | waterfall | 组装系统提示词、动态上下文和工具列表 |
| `agent/pre-step` | waterfall | 执行门禁：决定是否进入 Step、带什么消息进入；返回 reject 则直接 turn/end |
| `agent/request` | waterfall | 改变模型供应商/型号/配置参数，**不能修改消息** |
| `llm/stream` | waterfall | 包装或替换自定义流式迭代器 |
| `agent/request-error` | waterfall | 模型请求失败后的恢复，控制重试 |
| `tools/pre-execute` | waterfall | 工具执行前权限校验，返回 `allow / deny / ask`——插件接管权限模块的入口 |
| `tools/execute` | waterfall | 包装实际工具执行函数，可做超时、重试 |
| `tools/post-execute` | waterfall | 操作工具结果，决定以什么形式交给模型（替换内容、做标记） |
| `agent/turn-stopping` | **serial**（唯一） | Turn 即将关闭的最后机会 |

#### Notification Events (emit, 5 related to the main chain)

| 事件 | 作用 |
| --- | --- |
| `agent/session-start` | 获取完整 Agent 对象和启动信息 |
| `agent/status` | 获取当前 Agent 状态（执行中/已结束）+ 完整 Agent 对象 |
| `tools/result` | 拿到工具执行链路完整信息（结果+参数），**只能读不能改** |
| `agent/error` | `{ agent, turn, step, error }` 详细错误定位 |
| `session/event` | 每条持久化事件写入 session 存储时立即通知订阅者——前端显示推送、驱动统计/投影重算 |

#### Projection: init / apply / view Three Functions

适配模块用三个函数决定一切行为：**init** 初始化数据结构、**apply** 收到更新时计算、**view** 控制展示给前端的数据。

保证**唯一数据源**是 session 持久化文件（Agent 的数据底座）：上下文由它决定，前端显示只是"只读投影"，所有投影适配器的原始数据都来自同一份。设计哲学：把 Agent 上下文作为整个 Harness 最核心的东西，开发专注力放在"Session 文件该放什么、怎么设计"上——有点像上下文驱动整个 Harness 启动。

## Context / Memory / Knowledge

上下文、记忆、知识三者不是三个独立系统，围绕 Session Log 协同，共享一条约束：**模型看到的内容必须有可追踪来源，且能从会话记录重建。**

核心链路：

```
SystemPrompt.assemble() 组装上下文
→ ReactLoopAgent.preStep() 决定动态内容是否进入会话
→ Session.append() 保存事件
→ Session.deriveMessages() 生成模型历史
→ buildRequest() 构建最终请求
→ llm.stream() 完成模型调用
```

### Context Management

- **四类上下文、各有归属**：系统规则（SystemPrompt）/ 动态状态（Runtime Context）/ 会话历史（Session）/ 工具定义（ToolRuntime），模型调用前统一装配；AgentLoop 只管执行流程，不承担拼接
- `SystemPrompt.assemble()` 收集 `sections`（稳定提示）、`contexts`（动态环境）、`tools`、`variables`，各插件只注册自己的内容，每次生成本轮快照
- **避免重复注入**：`RuntimeContextProjection` 比较本轮与上轮快照——不变则沿用，变化才生成新上下文消息写入 Session（省 token + 保留状态变化轨迹；投影状态可从 Session 恢复，重启不重复注入）
- **三层结构**：**Log**（完整原始事件）→ **Surface**（当前参与派生的事件视图）→ **Messages**（发给模型的协议消息）。`deriveMessages()` 是唯一出口——模型输入不是各模块临时修改的消息数组，而是会话记录的派生
- `buildRequest()` 同时记录 `request/header` 和 `request/context`：可回答"模型当时看到了哪些历史/哪版系统提示/哪些工具/异常是推理问题还是输入问题"

### Memory Compaction (Compaction = Session Memory)

跨 Session 的长期记忆目前**没有形成完整系统**，现有记忆能力是 Compaction——服务于当前会话的连续运行。

- **只改 Surface**：摘要作为 replacement 节点遮蔽旧历史，原始事件留盘（比"删除前 N 条"安全：可审计压缩范围和摘要来源）——但**模型无法取回**，召回工具（`recall_history` 式）仍是 proposed 状态的 Agent Note
- **触发**：`floor(min(W × thresholdRatio, W − O − headroomTokens))`，默认 `thresholdRatio = 0.8`、`headroomTokens = 65536`（`W` 上下文窗口、`O` 单次请求输出预留）。两个入口——`agent/pre-step` 的 `pressure` 前瞻检查 + `agent/request-error` 的 `context-overflow` 兜底（后者绕过常规阈值与保留策略，`maxOverflowRetries` 默认 1）
- **区域选择**：优先折叠旧历史、保留近期（`retainRatio = 0.16`，按 `W − O` 计）；`validateSurfaceRegion()` 校验不切开 tool-call/tool-result 配对；surface 节点 0 的 `system/message` 永不被遮蔽
- **摘要固定模板**（8 节，以源码为准）：`Primary Request and Intent / Key Technical Concepts / Files and Code / Errors and Fixes / Pending Jobs / Current Work / Next Step / Critical Context`——防摘要退化成流畅但执行接不上的对话概述
- **替换事务**：`compaction/start` → 摘要 → `user/message`（`surfaceOp: replace`，`sourceEventSeqs` 关联被覆盖事件）→ `compaction/end`；三个 compaction 事件**仅写日志、绝不进 surface**，摘要由那条 `user/message` 承载；压缩失败时旧 surface 继续可用
- **收缩校验**：若摘要的 frame 后 token 数 ≥ 被遮蔽内容的 route 定价 token 数，直接抛错拒绝提交——摘要必须真的变小
- **有损风险**：摘要漏掉约束后模型可能执行错误命令——Log 完整性解决审计，没解决信息恢复；改进方向是 `recall_history` 式历史召回工具（按 turn/step/event seq/tool call id/文件路径结构化检索）
- **调度延迟**：压缩调一次 LLM 且在主流程上，长会话会卡顿；已落地的缓解是把指令放在回放前缀**之后**作为最后一条 user 消息，使辅助请求复用热前缀缓存（换 provider/model 或压缩非头部范围则放弃复用）

### Knowledge Acquisition (without vector store)

DSH **没有传统统一向量知识库**。知识入口 = 文件路径引用 + Web 搜索抓取 + 工具结果写回 Session。代码仓库有路径/符号/引用结构，统一切块进向量库会损失结构信息。

- **文件引用分层**：`file-reference-local` 只负责找到路径（`@path` 插入输入框），`read` 工具负责读取内容——选择路径时就展开文件会占满上下文、绕过 guard、丢失版本记录；`WorkspaceFileSearch` 控制目录边界、拒绝 `..`/符号链接跳出 workspace
- **检索四层逻辑**（优先消耗确定性信息）：已知路径直接 read → 已知文本 grep → 已知符号 LSP（定义/引用/诊断）→ 只有概念描述才考虑语义检索
- **Web 检索三层**：`WebRuntime` 定义能力 → search/fetch provider 具体请求 → `tool-web` 注册为模型可见工具；provider 选择严格（指定 id 或唯一可用，多 provider 报错，避免加载顺序影响线上行为）
- **网络边界**：HTTP fetch provider 限制协议/私网地址/重定向/字节数/固定 DNS；模型生成的 URL 是不可信输入，Prompt Injection 可能诱导请求内网——**网络策略必须在模型之外执行**

## Permissions and Sandbox

> 核实于 2026-10-06，来源 `docs/subsystems/approval.md` 与 `docs/subsystems/sandbox.md`（官方子系统文档，与源码 `packages/interaction/user-approval`、`packages/sandbox/*` 同步生成）。通用机制（沙箱形态分档、权限判定层级、fail-closed 实现）见 [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md)；本节约 DSH 自己的实现。

DSH 把「能不能做」拆成两个正交的 knob：**审批策略**（`approval/policy`，管「要不要问人」）与**沙箱模式**（`sandbox/mode`，管「进程能碰什么文件」）。二者由 `dsh-permission-presets` 捆绑成客户端可见的具名预设，但底层始终是两个独立事件。

### Approval Subsystem

`ctx.approval` 是闭合的审批 seam，回答「这个具体操作能不能继续」。结果类型把 fail-closed 写进了类型系统：

```ts
type ApprovalOutcome = 'allowed-once' | 'rejected' | 'cancelled' | 'unavailable'
```

- **唯一授权是 `allowed-once`**：类型层面就不存在「永久授权」——这是 DSH 在几家产品里最保守的设计（详见 [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 的审批粒度对比）。`rejected` / `cancelled` / `unavailable` 对调用方一律按拒绝处理。
- **`unavailable` 是 fail-closed 的兜底**：应答者缺失、不负责该请求、抛异常、返回词表外的值，或不合规，结果都是 `unavailable` 而非放行——沉默的故障不会变成放行。
- **按会话策略 `ask` / `never`**：`ask`（默认）委托给组合的应答者链，链无应答则落到 `unavailable`（fail closed）；`never` 在分发前、waterfall 之外确定性返回 `rejected`，是 headless / CI 的严格姿态。生效值由会话日志最后一条 `approval/policy` 事件决定，回放可重建。
- **入口是 `approval/request` waterfall**：UI 通道提供人类应答者，ACP（Agent Client Protocol）自动化桥接层为它拥有的 agent 提供一次性机器决策；调用方（`dsh-tools`、`dsh-tool-bash`）消费闭合结果，非 `allowed-once` 即拒绝。每个请求有独立的品牌化 `ApprovalRequestId`，把 `approval/asked` 与 `approval/decided` 审计事件配对，不与 tool call id 或会话 id 混淆。

### Two Forms of the Sandbox Subsystem

DSH 的「沙箱」其实是两个不同层次的能力，常被人混为一谈：

| 形态 | 提供方 | 隔离性质 | 作用范围 |
| --- | --- | --- | --- |
| **文件系统策略围栏**（fs-sandbox） | `dsh-fs-sandbox`（文件系统 seam 的一部分） | **策略层，不是内核边界** | 路径级：把 read / write / edit 限制在 workspace 根与后端承诺的临时区 |
| **进程沙箱**（sandbox-local） | `dsh-sandbox-local` | **真内核边界**（namespace / LSM / token） | 子进程的文件效果（写入被拒、目录视图受限） |

`SandboxMode` 只管**文件效果**三态：`read-only`（拒绝写入，POSIX runner 仅给 `/dev/null` 接收器）、`workspace-write`（允许在工作区根与临时区写）、`danger-full-access`（绕过隔离，消费方直接 spawn 不调 `ctx.sandbox`）。**网络可见性与进程可见性不在 `SandboxMode` 的词汇内**——这部分由沙箱后端外的其它机制负责。

- **fs-sandbox（策略围栏）**：文件系统后端在 `writeText` / `editText` 上携带 `sandboxPolicy`；策略插件（`dsh-fs-observation-policy`）通过 `fs/write-intent`、`fs/edit-intent` 两个单槽 waterfall 裁决，未加载策略插件时退化为「无条件裸写入」。它本质是 canonicalize-then-contain 的路径围栏，错误码 `FS_SANDBOX_DENIED` 区别于内核拒绝的 `FS_PERMISSION_DENIED`。
- **sandbox-local（内核边界）**：`dsh-sandbox-local` 提供平台后端——**Linux 用 bwrap / Landlock、macOS 用 Seatbelt、Windows 用受限令牌（restricted-token）ACL**。强制完整性由后端报告：`full`（管控了模式承诺的全部文件效果）或 `partial`（老旧 Landlock ABI、Windows ACL 的硬链接 / 宽松读 / AppContainer 缺口，归为 `partial`——要求绝对边界的消费方必须拒绝或向上暴露）。消费方按后端方言（`denialSignatures`：bwrap 的 EROFS、Landlock 的 EACCES、Seatbelt 的 EPERM）从 stderr 识别「沙箱正常工作但命令被拦」，与「runner 本身故障」区分开。
- **per-call 策略 + fail closed**：完整策略（`SandboxExecutionPolicy`）逐次能力调用解析并携带，因此 bash 与受限子 agent 可在同一瞬间向同一提供方请求不同边界；无可用后端时 `ctx.sandbox.confine()` 抛 `SandboxUnavailableError`（`SANDBOX_UNAVAILABLE`），**静默的无隔离透传永远不合法**。

### Permission Preset Layer

`dsh-permission-presets` 把上面的两个 knob 捆绑成具名预设，供客户端作为单一 Permissions 选择器。**默认配置表**自带两项：`workspace-write`（`workspace-write` + `ask`）与 `danger-full-access`（`danger-full-access` + `never`）；`custom` 与 `auto` 是保留名（派生态 / Auto review 集成），不可配置。Auto review 集成在其 effect 生命周期内发布当前会话专属的 `auto` 预设（`danger-full-access` + `ask`，委派子会话固定 `never`）。切换写 `permission/preset` 日志事件，再经各 knob 自己的 setter 落到 `sandbox/mode` 与 `approval/policy`——该层不拥有执行策略，只做组合。

## Subprocess Management: Let a Command Die Cleanly

> 这个包的 `spawn.ts` 有 543 行，真正把进程拉起来的 spawn 调用只有 12 行，剩下五百多行在回答同一个问题：**怎么让这个进程死干净**。起进程从来不难，难的是收。

主线案例是 bash 执行器跑一条 `npm run build`：npm 自己是 node 进程，它再拉起构建器，构建器还自带进程池。从 Harness 视角看，这不是"一个子进程"，而是**一棵进程树**。围绕这棵树，六种死法各自长出一层机制。

| 死法 | 症状 | 机制 |
| --- | --- | --- |
| 孤儿进程 | 命令超时了机器却越来越烫 | `detached` 独立进程组 + 负 pid 组信号 |
| pid 复用 | 探活误判，SIGKILL 打死别人进程 | 首次确认树亡 = 永久停手边界 |
| leader 死、树没死 | 优雅退出宽限期被打断 | `graceTimer` 刻意不清、kill 前重探活 |
| 2GB 构建日志 | Node 先 OOM | 字节精确的尾部窗口 + 有上限的 spill 文件 |
| exit 来了 close 不来 | 工具调用挂死在 await 上 | 同一个 `graceMs` 兜底强制结算 |
| 宿主先死 | 活树留在系统里 | `prependListener('exit')` 队首同步 SIGKILL |

### Independent Process Group and Negative pid

`child_process` 的默认 spawn 治不了孤儿：信号发给 npm，到不了它 fork 的构建器。DSH 的解法写在一个参数里——POSIX 上 `detached: true` 让孩子拥有自己的进程组，组 id 等于它的 pid：

```ts
const child = spawn(program, args, {
  cwd: spec.cwd,
  env,
  stdio: [
    stdinMode === 'ignore' ? 'ignore' : 'pipe',
    outMode === 'inherit' ? 'inherit' : 'pipe',
    errMode === 'inherit' ? 'inherit' : 'pipe',
  ],
  // `detached` gives teardown a tree root on POSIX (its own process group);
  // Windows terminates by root pid through taskkill /T instead.
  detached: platform !== 'win32',
})
```

`process.kill(pid)` 杀一个，`process.kill(-pid)` 杀一组——**一个负号，就是"杀一个"和"杀一棵树"的全部区别**。后面所有终止逻辑都建立在这个负号上。

顺带看 `env`：`childEnv(spec.env)` 先取基类提供的 `scrubbedParentEnv()`，把父环境的凭据类变量剔干净再叠加调用方条目，所以 `aws.env` 里的 key 不会跟着构建命令泄进子进程。

Windows 没有进程组，换一种砍法，`/T` 砍整棵树、`/F` 强杀：

```ts
export function taskkillProcessTree(pid: number): void {
  if (pid <= 0) return
  // Outcome deliberately unchecked: an already-absent tree (status 128), exit
  // races, and a missing taskkill binary (spawnSync reports, never throws) are
  // as tolerable here as ESRCH is for a POSIX group signal.
  spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
}
```

注释里"结果故意不检查"是重点：**终止逻辑必须幂等**，第二次杀一棵死树不能抛异常，否则收尾代码会自己把自己绊倒。

### pid Reuse: First Confirmation Is a Permanent Boundary

发完 TERM 怎么知道树死了？POSIX 惯例是 `process.kill(-pid, 0)` 探活（0 号信号只做存在性检查），DSH 用 **15ms 一次的轮询**做这件事。

风险在于 pid 会回收：树全退 → 组 id 进回收池 → 系统把同一个数字发给不相干的新进程且它恰好成了组长 → 下一轮探活成功 → 升级梯到点，SIGKILL 打死别人的进程。DSH 立了一道**不可逆**的边界：

```ts
/**
 * Start or reuse the handle's single whole-tree exit observer. The first
 * confirmed absence is a permanent no-more-signals boundary: it cancels a
 * pending escalation before this process-group id can be reused.
 */
const observeTreeExit = (): Promise<void> => {
  treeExitObservation ??= (async () => {
    while (treeAlive()) await sleepTick()
    treeExitObserved = true
    if (graceTimer !== undefined) clearTimeout(graceTimer)
    graceTimer = undefined
  })()
  return treeExitObservation
}
```

`treeExitObserved` 一旦置 true 就永不回头，`treeAlive()` 第一行就是它：确认过树亡，此后一切探活直接返回死，待发的 SIGKILL 也被撤掉。两个配套细节：

- `sleepTick` 的 timer 保持 **ref'd**——被 await 的收尾必须保住事件循环直到树真退出，否则父进程一边宣称一切已安静一边退出，留下的正是它承诺要收割的孤儿。
- 只剩僵尸的组对 `kill(0)` 同样应答成功（僵尸占着进程表条目，杀不死，只能等父进程收尸）。因此 Linux 上还有一层精化：`linuxProcessGroupHasLiveMembers(pid)` 扫 `/proc` 判断组内成员是否全是 Z/X，但**只在直接孩子结算之后才扫**——活跃期的轮询保持一次 syscall 的成本，不拖家带口扫全表。

### Leader Death Does Not Mean Tree Death

`terminate()` 是终止的全部：已观测退出或已有 `graceTimer` 就直接返回，否则先 `observeTreeExit()`，发 SIGTERM 给整组，再挂一个 `graceMs` 的定时器到点升级 SIGKILL。

```ts
const terminate = (): void => {
  if (treeExitObserved || graceTimer !== undefined) return
  void observeTreeExit()
  if (treeExitObserved) return
  kill('SIGTERM')
  // The escalation must survive direct-child settlement — the leader dying
  // does not mean the tree died — so settle does not clear this timer, and
  // kill() re-probes tree liveness before force-killing. …
  graceTimer = setTimeout(() => { kill('SIGKILL') }, spec.graceMs)
}
```

反直觉的地方在下一层：npm 收到 TERM 退出了，exit 事件来了，直觉是"孩子都死了，SIGKILL 定时器该清了"——**不清**。npm fork 的某个 helper 可能捕获了 TERM，正慢慢写临时文件，它还活着，还欠着一次可能的 SIGKILL。所以结算函数里刻意不清 `graceTimer`，且 `kill()` 每次执行前重新 `treeAlive()` 把关。

`graceMs` 自身也有硬上限：spawn 前校验它必须是正数且不超过 `2^31-1`（`MAX_TIMER_DELAY_MS`）——这是 Node 定时器能表示的最大延迟，更大的数塞进 `setTimeout` 会被立即触发，升级梯当场失效。

超时归谁管？**这个包自己不定超时**，只监听调用方传进来的 `AbortSignal`，abort 一到就 terminate。超时语义在消费侧，bash-local 里只有三行：

```ts
// One deadline combines timeout and upstream cancellation; disposal clears its timer.
using d = deadline(spec.signal, spec.timeoutMs, 'BASH_TIMEOUT')
const handle = this.ctx.subprocess.spawn(this.spawnSpec(spec, argv, spec.stdoutMaxBytes, d.signal))
```

`using` 在作用域结束时自动 dispose 定时器，超时与上游取消在上层合成一个信号，下层只管响应——两层各认各的账。

### Output: Byte-Precise Diagnostic Tail

构建挂掉时编译器把每个文件的错误全吐出来，stdout 两 GB，全量缓存进内存 Node 先 OOM。截断该截头部还是尾部？依据是**错误和最终结果聚在命令输出的末尾**（引自 pi / OpenCode 的实践），所以内存里只留尾部。

```ts
push(chunk: Buffer): void {
  this.total += chunk.length
  const overflows = this.bytes + chunk.length > this.maxBytes
  if (!this.spillDisabled && (overflows || this.spillFd !== undefined)) this.spillAll(chunk)
  this.chunks.push(chunk)
  this.bytes += chunk.length
  while (this.bytes > this.maxBytes) {
    const head = this.chunks[0] as Buffer
    const excess = this.bytes - this.maxBytes
    if (head.length <= excess) {
      // Drop the whole head chunk (length ≥ 1 is guaranteed while over cap).
      this.chunks.shift()
      this.bytes -= head.length
    } else {
      // Trim the head so the retained window is byte-exact at the cap — a
      // diagnostic tail (an LSP server's stderr) must hold the LAST
      // maxBytes regardless of how the stream was chunked.
      this.chunks[0] = head.subarray(excess)
      this.bytes -= excess
    }
    this.dropped = true
  }
}
```

两个分支的意义是**与流怎么分块无关**——诊断尾部永远精确装着最后 N 字节。头部丢之前先救一步：首次溢出时 `spillAll` 把已收集的块写入 spill 文件（`'wx'` 标志、`0o600` 权限、6 字节随机后缀，防的是共享 tmp 目录里的路径预测与 symlink 种植），此后追加；spill 也有总量上限，超限则关 fd、删文件并永久禁用，磁盘绝不无限增长。不配 spill 的 collect 模式就是纯粹的"诊断尾部"形态，比如 LSP server 的 stderr——只留内存尾部，不落文件。

### exit Arrives, close Does Not

孩子退出不等于输出齐了：Node 的 `close` 事件要等 stdio 流全部关闭，而 npm 退场时留下的后台子进程继承了 stdout 管道、攥着写端不放，于是 exit 触发了 close 永远不来，工具调用挂死在 `await` 上。兜底是两条路先到先得：

```ts
child.on('exit', (exitCode, signal) => {
  // A surviving descendant that inherited a pipe must not hold the
  // outcome open indefinitely: after exit, the same bounded grace that
  // governs kills also bounds the close wait.
  pipeDrainTimer = setTimeout(() => {
    settle(exitCode, signal)
  }, spec.graceMs)
})
child.on('close', settle)
```

close 正常来就 settle，graceMs 内没来就强制 settle 并 destroy 掉服务自己 collect 的管道（`'pipe'` 模式的流属于调用方，不动）。注意这里**复用的又是 `graceMs`**——杀树的宽限和等管道的宽限是同一个数。settle 的产物是 `{ exitCode, signal }`：正常退出带 exitCode、被信号杀带 signal，terminal 那条线上再做一次归一（exit 带非零信号时 exitCode 记 null），两个入口吐同一种形状，上层不用分辨。

### Host Dies First

最坏的时序是 dsh 自己要退出：插件树开始 dispose，promise 链还在飞，而 Node 的 `exit` 事件是同步的，里面 promise 不会 resolve、await 全部失效。所以兜底挂在队列**最前面**：

```ts
constructor(ctx: Context) {
  super(ctx)
  ctx.effect(() => {
    const onHostExit = (): void => { this.terminateForHostExit() }
    process.prependListener('exit', onHostExit)
    return async () => {
      try {
        await this.disposeManagedProcesses()
      } finally {
        process.off('exit', onHostExit)
      }
    }
  }, 'local subprocess teardown')
}
```

用 `prependListener` 而非 `on`，是因为 exit 监听器按注册顺序同步执行，插到队首才能抢在其他清理逻辑前面拿到执行权。正常退出走 `disposeManagedProcesses`：对每棵活树 `terminate()`，然后等的不是直接孩子的 `done`，而是 `waitForExit()` 的**整树退出**；任何一次等待失败立刻降级为 `terminateForHostExit`——遍历全部句柄逐个同步 `kill('SIGKILL')`，单个失败不拦下一个（同步 exit 阶段能用的原语只剩这个）。

所有权释放条件也钉在同一根线上：**handle 从 live 集合删除要等整树退出之后**。trap 了 TERM 的 helper 必须保持"被服务拥有"，teardown 才来得及升级它。

### This Half Is PTY, and Why There Is No Config

包的另一半 `spawnTerminal` 起 node-pty 会话给终端面用，自成一套难题（shell 在自己的会话里，前台进程组归 tty 管，**负 pid 一刀切不适用**）。其中最深的是一个布尔值 `isStdinWaiting`——前台进程组是不是在等输入。Linux 实现扫 `/proc/<pid>/task/<tid>/syscall`，按体系结构查表：

```ts
const SYSCALLS: Partial<Record<NodeJS.Architecture, SyscallTable>> = {
  x64: { read: 0, select: 23, pselect: 270, poll: 7, ppoll: 271, epollWait: 232, epollPwait: 281 },
  arm64: { read: 63, pselect: 72, ppoll: 73, epollPwait: 22 },
}
```

`read` 看第一个参数是不是 fd 0；`poll` 更进一步，`readMemory` 直接读目标进程内存、把 pollfd 数组解析出来看有没有 stdin。Agent 靠这个区分"前台在等输入，该发 Ctrl-C"和"前台在跑长任务，该等"。Windows 侧则用 koffi 绑 Toolhelp32 快照枚举 + `GetProcessTimes` 取创建时间，用**创建时间戳**实现 pid 复用防御——`ProcessIdentity` 这套契约三个平台各写一遍原语，把语义拉平。

还有一件值得记住的小事：**这个插件没有 Config**。文件头注释写明 every disposition and limit arrives on the spec——stdio 怎么处置、尾部留多少、宽限多长，全由调用方的 spec 逐次带来；部署相关选择留在 bash 执行器、LSP host 各自的配置里，进程管理本身无配置可言。

### Three Counter-Intuitive Points, All in the Comments

- **Windows 的树语义弱一档吗**：spawn 线确实弱（无组、无探活，`taskkill /F` 直接强杀，没有 TERM 宽限），但 terminal 线用 Windows inspector 补上了创建时间戳防御。
- **15ms 轮询浪费吗**：对比 `SIGCHLD`/`waitid` 方案——信号不排队、要配 `waitpid` 循环、跨平台语义碎。规模小（每棵活树一个 observer）时，轮询是白捡的简单。
- **改这个包的人要先信注释**：`graceTimer` 刻意不清、首次确认即永久停手、活跃轮询单 syscall，这三处行为都反直觉，也都把理由写在旁边了。动这几行之前先读注释，否则很容易"顺手优化"掉一道防线。

## Tool Layer

> 核实于 2026-10-06，来源 `docs/subsystems/tools.md` / `filesystem.md` / `shell.md`。base bundle 一次挂入 14 个 `dsh-tool-*` 插件。

### Tool List

DSH 面向模型的工具由独立插件提供，base 配置默认包含：

| 工具插件 | 能力 |
| --- | --- |
| `dsh-tool-fs` | read / write / edit（字面替换），经 `ctx.fs` 与 `fs/*` 事件，渲染行窗口 |
| `dsh-tool-fs-search` | glob / grep 文件检索（进程支撑，带 `timeoutMs`，由 `dsh-tool-call-timeout-policy` 强制） |
| `dsh-tool-bash` | Bash 执行器消费方（沙箱化，消费 `ctx.sandbox`） |
| `dsh-tool-pwsh` | PowerShell 执行器消费方（Windows） |
| `dsh-tool-web` | Web 检索 / fetch（消费 `ctx.web`，网络策略在模型之外执行） |
| `dsh-tool-skill` | 加载并执行 YAML / Markdown 定义的 Skill |
| `dsh-tool-todo` | 任务清单 |
| `dsh-tool-goal` | 持久 Goal，驱动 Goal 外循环 |
| `dsh-tool-jobs` | 后台任务管理 |
| `dsh-tool-workflow` | 工作流编排 |
| `dsh-tool-subagent` | 派生子 agent（Fork / Spawn） |
| `dsh-tool-subagent-control` | 子 agent 控制 |
| `dsh-tool-ralph` | ralph 工作流工具 |
| `dsh-tool-call-timeout-policy` | `tools/execute` 包裹器，强制 `timeoutMs`（永不发给模型） |

工具后端由 `dsh-fs`（抽象的 `ctx.fs` + 原子文本操作）、`dsh-fs-local`（本地磁盘后端）、`dsh-shell`（抽象的 `ctx.shell` + Bash / PowerShell 提供方）支撑；MCP（`dsh-mcp-*`）与 LSP 经各自的 capability seam 接入，不混进工具内核。

### ToolDefinition Pipeline

一个已注册工具 = `ToolSchema`（面向模型的字段）+ 必需规范输出声明 `output` + `execute` 函数 + 宿主专用的调度元数据（`timeoutMs` / `isConcurrencySafe` / 展示回调）。注册表 `schemas()` 用显式允许列表构建面向模型的 `ToolSchema[]`，`output` / `execute` / 展示字段**绝不泄漏到模型请求**。

- **canonical output contract**：`output.schema` 用 JSON Schema 校验每个成功值，`render()` 把校验后的参数与值投影成 Native / model content——内容与展示分离，replay 安全。
- **并行工具调用**：`isConcurrencySafe(args)` 返回 `true` 才允许加入并行组；opt-in 的执行不得改动父拥有状态，共享状态必须容忍并发或 fail closed。
- **超时**：`timeoutMs` 是协作式预算，由 `dsh-tool-call-timeout-policy`（`tools/execute` 包裹器）强制，从不被送往模型；fs 的 read / write / edit **不设超时**——本地系统调用至多尽力中止，超时无法迫使进行中的 `fsync` / `rename` 停下，故 `timeoutMs` 在此处会成为 seam 无法强制的截止时间。

### File System Defaults to "Read Before Write"

`dsh-tool-fs` 加载时应同时加载 `dsh-fs-observation-policy`，使默认行为是「先读后写 / 先读后编辑」：策略插件用 `WeakMap<owner, Map<targetKey, FsObservation>>` 记录已观测状态（存在带版本 / 确认缺失），在 `fs/write-intent`、`fs/edit-intent` 单槽 waterfall 上按「未见 / 缺失 / 存在」决策。带版本守卫的写入若后端版本与观测版本不符报 `FS_STALE_VERSION`（而非「匹配失败」），原子地把匹配、行尾处理、陈旧检查与原子替换放进一个变更临界区。错误用稳定 `FsErrorCode` 字符串携带（`FS_NOT_FOUND` / `FS_STALE_VERSION` / `FS_SANDBOX_DENIED` / `FS_PERMISSION_DENIED` / `FS_TOO_LARGE` …），重试 / 权限 / UI 层按 code 分支而不解析文本。

## Plugin

> 参考：[第一个插件](https://deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/)（前置：完成[从源码运行](https://github.com/deepseek-ai/deepseek-harness#run-from-source)）

### What Is a Plugin

插件是一个**导出 `apply` 函数的 TypeScript 模块**。框架加载时调用 `apply`，传入 `ctx`（上下文对象），通过 `ctx` 注册能力——这就是完整的插件配置。

```ts
import type { Context } from '@deepseek-ai/cordis'

export const name = 'hello-plugin'

export function apply(ctx: Context) {
  console.log('[hello-plugin] plugin loaded!')
}
```

### Register to Web UI

创建 `scratch-plugin/cordis.yml` 作为本地插件的 Web 覆盖层（插件路径必须是**绝对路径**；patch 文件只贡献配置，不改变 loader 解析模块路径的 profile 目录）：

```yaml
- insert:
    - id: hello
      name: '/absolute/path/to/deepseek-harness/scratch-plugin/src/my-plugin.ts'
```

用覆盖层启动 Web UI：

```sh
pnpm dsh web --patch ./scratch-plugin/cordis.yml
```

打开 `http://127.0.0.1:3080`，启动时终端会打印 `[hello-plugin] plugin loaded!`。

### Lifecycle and Automatic Cleanup

通过 `ctx` 注册的一切（事件监听、工具、定时器）在插件卸载时**自动清理**，无需手动 `removeListener` / `clearInterval`。需要手动清理的资源（如网络连接）用 `ctx.effect()`：

```ts
export function apply(ctx: Context) {
  ctx.effect(() => {
    const timer = setInterval(() => console.log('heartbeat'), 5000)
    return () => clearInterval(timer) // 插件卸载时执行
  })
}
```

真实例子——存储插件登记可撤销的 backend 注册：

```ts
export const inject = ["storage"]

export function apply(ctx, config) {
  const backend = new JsonStorageBackend(config.root)

  ctx.effect(() => {
    const unregister = ctx.storage.backend.register("json", backend)
    return async () => {
      unregister()
      await backend.close()
    }
  })

  ctx.provide("storageBackend:json", backend)
}
```

### Declare Dependencies (inject)

需要其他服务（如 `tools`、`llm`）时声明 `inject`，框架确保依赖服务就绪后才加载插件：

```ts
export const name = 'my-tool-plugin'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(/* ... */) // ctx.tools 已就绪
}
```

### Composition Example: minimal preset File System

`isolate` + `inject` + Provider/Consumer 三角色的真实组合（`agent.cordis.yml`）：

```yaml
- id: filesystem
  name: cordis:group
  group: true

  # 为这棵子树创建私有的 fs service realm
  isolate:
    fs: true

  config:
    # Consumer：tools 或当前 realm 的 fs 缺失时，Fiber 保持 PENDING
    - id: editor
      name: '@deepseek-ai/dsh-tool-str-replace-editor'
      inject: [tools, fs]
      config:
        maxOutputChars: 16000

    # Provider：在上面的私有 realm 中发布 ctx.fs
    - id: fs-provider
      name: '@deepseek-ai/dsh-fs-local'
      config:
        cwd: !!js process.env.DSH_CWD ?? process.cwd()
```

### Three Forms of Plugins

| 形态 | 适用场景 |
| --- | --- |
| 函数形式 `export function apply(ctx)` | 大多数情况 |
| 对象形式 `export default { name, inject, apply }` | 需要打包 name/inject 声明 |
| 类形式 `class MyService extends Service` | 需要向其他插件提供服务（见[服务与依赖](https://deepseek-harness.github.io/deepseek-harness/develop/framework/service)） |

```ts
// 类形式
import { Service, type Context } from '@deepseek-ai/cordis'

export default class MyService extends Service {
  static inject = ['tools']

  constructor(ctx: Context) {
    super(ctx, 'myService')
    // 构造函数中做同步初始化
  }
}
```

## Positioning Differences from Similar Products

DSH 与其它 coding agent harness 的核心差异在「内核是否可被插件替换」与「审批 / 沙箱的保守程度」，细节见各产品笔记：

| 维度 | DSH 的立场 | 详见 |
| --- | --- | --- |
| 架构 | 没有特权内核——连 Agent Loop、UI 都是可替换插件（Cordis） | [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) |
| 审批 | 类型层面只有 `allowed-once`，永久授权不存在（四家里最保守） | [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md) |
| 沙箱 | fs-sandbox（策略围栏）+ sandbox-local（bwrap / Landlock / Seatbelt / ACL 内核边界）双形态 | 同上 |
| 工具收口 | OR 聚合（任一 concluded 即收口），`agent/turn-stopping` 无布尔返回、数据驱动 | [Pi](/docs/CS/AI/LLM/Agent/Product/Pi.md)（AND 聚合对照） |
| 压缩 | `pressure` 前瞻 + `context-overflow` 兜底双入口 | [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) |
| 长期记忆 | 无完整跨会话系统，仅 Compaction 服务当前会话 | [ClaudeCode](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)（CLAUDE.md 对照） |

## Links

- [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) / [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 上下文压缩的通用机制与各家实现对比（展开本篇「记忆压缩」一节）
- [Pi](/docs/CS/AI/LLM/Agent/Product/Pi.md) — 另一种 Agent Loop 结束判断（AND 聚合）的实现
- [TypeScript](/docs/CS/TypeScript/TypeScript.md) / [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)

## References

1. [开发一个工具](https://deepseek-harness.github.io/deepseek-harness/develop/basic/tool)
2. [插件配置](https://deepseek-harness.github.io/deepseek-harness/develop/basic/config)
3. [Cordis 框架教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)
4. [Cordis](https://github.com/cordiverse/cordis) / [时空可组合性论文](https://github.com/cordiverse/paper)

### Community Deep Analysis (2026-08 ~ 2026-09, technical details in each section are mainly distilled from this batch of articles)

其中「源码深读」系列一个包一篇往下钻，基于 DeepSeek Harness 源码（MIT，`0.1.1-rc.1`）与官方 Agent Notes 整理：

- [DSH：DeepSeek Harness 架构解析](https://mp.weixin.qq.com/s/Kf87hcNdSmY4ODWI4UZ8cg)
- [为什么 DSH 把一切都做成插件？Cordis 又是什么？](https://mp.weixin.qq.com/s/EDx6e1AEKalz6dEXdyWFSg)
- [DeepSeek Harness 底层原理图解（时序图 + 流程图）](https://mp.weixin.qq.com/s/1NWC0Qk-bDkvr8QIVPr1Zg)
- [DSH 和 Pi 的 Agent Loop 循环结束判断架构细节解析](https://mp.weixin.qq.com/s/7KJgpnKQ0VVHe-oMnS2L5Q)
- [DSH 的 Cordis 插件架构](https://mp.weixin.qq.com/s/XFWvHB8ke_LjcSZ06IajsA)
- [DSH 的上下文管理、记忆和知识库剖析](https://mp.weixin.qq.com/s/RG5oQ6rpNDNn7Fwo9GoqIA)
- [DSH 的宝藏之一：Session 持久化的设计](https://mp.weixin.qq.com/s/uH3vuY9nNCmp-q4yUtRRYA)
- [源码深读 04：起一个子进程只要十行，送走它用了五百行（subprocess-local）](https://mp.weixin.qq.com/s/mmprMkOaTMP2IBTeH6uQuw)

#### Three Clues for Reading Source (lencx's suggested path)

1. 看 Loader 输出的配置树（`dsh --dump-config`）
2. 追踪 `provide`/`inject`、Context realm、Fiber effect
3. 沿 Session event 到 `deriveMessages()`，检查模型实际所见

#### Engineering Adoption Recommendations (Pan Jin)

自建类似架构前先确认三个条件：①能力确实需要独立替换（存在两个生产提供方或明确外部扩展需求）②同一进程需要多套组合并存，或运行期间需要可靠更新 ③团队愿意为卸载、回滚和真实组合测试持续付费。缺这些条件，插件框架容易沦为复杂的工厂模式。

设计纪律：**先问如何撤销，再问如何注册；先证明局部挂载不会泄漏，再讨论全局复用；先定义失败后保留哪棵树，再讨论热更新速度。**

- 官方子系统文档（与源码同步生成，本篇「权限与沙箱」「工具层」主要提炼自这些页）：[approval](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md) / [sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md) / [filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/filesystem.md) / [tools](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/tools.md) / [shell](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/shell.md) / [permission-presets](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/permission-presets.md)
