> 版本基线：核实于 2026-10-06。架构 / 权限 / 沙箱 / 工具细节以官方子系统文档与 `deepseek-harness` 源码（`main` 分支）为准；base bundle 共 94 个插件条目。

## Introduction

DeepSeek AI 开发的开源 agent harness（智能体框架）。构建于**一切皆插件**的架构之上，由 [Cordis](https://github.com/cordiverse/cordis) 驱动，设计论文：[*A Programming Paradigm for Spatiotemporal Composability*](https://arxiv.org/abs/2608.25512)

> 一句话理解：Cordis 维护一张**运行时插件图**（系统现在由什么组成），Session 维护一份**追加式事件流**（系统刚才做过什么）；Agent loop 位于两者之间——从插件图取能力，写回事件流。

DSH 是 Agent 产品里**架构哲学最激进**的一个——没有特权内核，连驱动 Agent 运转的主循环都只是默认插件实现之一。这种设计使得同一套运行时可以组合出不同产品形态（`web` / `headless` 进程形态 × `standard` / `code` / `minimal` / `cordis` 会话预设），但也带来了较高的理解和调试成本。

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

## Architecture Overview

DeepSeek Harness 的架构采用**"一切皆插件"（Everything is a Plugin）**的设计哲学，核心公式：**Model + Harness = Agent**。整体架构可以从以下几个层次来理解。

### Cordis Microkernel Layer

最底层是 DeepSeek 自研的 Cordis 插件框架，只负责三件事：

1. 插件生命周期管理（加载 / 卸载 / 依赖解析）
2. 依赖注入
3. 全局事件总线

Cordis 不含任何模型、工具或 UI 逻辑；支持热重载与副作用自动回收——插件卸载时，其注册的服务和事件会被自动回滚。

但"一切皆插件"有一个前提：**一切*产品能力*皆由插件贡献，Cordis 自身仍保留插件得以存在的机制**（上下文代理、Fiber 状态机、服务存储、事件总线、Loader 属于元层）。更准确的说法是：内核不拥有模型、工具和循环等产品特权。

> Cordis 的完整运行时模型（Context、Fiber、isolate/realm、effect、事件分派五模式）见 [DSH Cordis](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)。

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

## Knowledge Map

下表把 DSH 的核心主题分布到各子文件中。如果是第一次接触 DSH，建议按从上到下的顺序读——Cordis 是底座，Agent Loop 是主流程，Permission 和 Subprocess 是最容易出 bug 的两块。

| 主题 | 覆盖内容 | 文件 |
| --- | --- | --- |
| **Cordis 微内核** | Context/Fiber/isolate/effect/事件分派五模式、与 Eclipse/OSGi/DI 容器对比、TypeScript 必需知识点 | [Cordis.md](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md) |
| **Agent Loop & Session** | 五层结束语义边界、Turn/Step 状态机、工具收口 OR 聚合、Goal 外循环、Session 持久化事件溯源、9 个扩展点事件 | [AgentLoop.md](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md) |
| **Context / Memory / Knowledge** | 四类上下文装配、Compaction（压缩机制与热前缀缓存）、知识获取（无统一向量库、文件引用分层、检索四层逻辑、Web 三层） | [Context.md](/docs/CS/AI/LLM/Agent/Product/DSH/Context.md) |
| **Permission & Sandbox** | ApprovalSubsystem（`allowed-once` 唯一授权、fail-closed 兜底）、fs-sandbox 策略围栏 vs sandbox-local 内核边界、Permission Preset 层 | [Permission.md](/docs/CS/AI/LLM/Agent/Product/DSH/Permission.md) |
| **Subprocess Management** | 进程树收割六类死法、负 pid 组信号、pid 复用不可逆边界、诊断尾部 spill 文件、PTY `isStdinWaiting`、宿主退出 prependListener | [Subprocess.md](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md) |
| **Tool Layer** | 14 个 `dsh-tool-*` 插件逐一分组说明、ToolDefinition Pipeline、read-before-write 观测策略 | [Tools.md](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md) |
| **Plugin Development** | 三种插件形态、`ctx.effect()` 生命周期管理、inject 依赖声明、Patch YAML 装配、minimal preset 文件系统组合示例、完整开发工作流 | [Plugin.md](/docs/CS/AI/LLM/Agent/Product/DSH/Plugin.md) |

## Reading Source: Three Clues

lencx 建议的三条源码阅读路径：

1. 看 Loader 输出的配置树（`dsh --dump-config`）
2. 追踪 `provide`/`inject`、Context realm、Fiber effect
3. 沿 Session event 到 `deriveMessages()`，检查模型实际所见

## Engineering Adoption Recommendations

自建类似架构前先确认三个条件：①能力确实需要独立替换（存在两个生产提供方或明确外部扩展需求）②同一进程需要多套组合并存，或运行期间需要可靠更新 ③团队愿意为卸载、回滚和真实组合测试持续付费。缺这些条件，插件框架容易沦为复杂的工厂模式。

设计纪律：**先问如何撤销，再问如何注册；先证明局部挂载不会泄漏，再讨论全局复用；先定义失败后保留哪棵树，再讨论热更新速度。**

## Positioning Differences from Similar Products

DSH 与其它 coding agent harness 的核心差异在「内核是否可被插件替换」与「审批 / 沙箱的保守程度」，细节见各产品笔记：

| 维度 | DSH 的立场 | 详见 |
| --- | --- | --- |
| 架构 | 没有特权内核——连 Agent Loop、UI 都是可替换插件（Cordis） | [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) |
| 审批 | 类型层面只有 `allowed-once`，永久授权不存在（四家里最保守） | [Permission 理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md) |
| 沙箱 | fs-sandbox（策略围栏）+ sandbox-local（bwrap / Landlock / Seatbelt / ACL 内核边界）双形态 | 同上 |
| 工具收口 | OR 聚合（任一 concluded 即收口），`agent/turn-stopping` 无布尔返回、数据驱动 | [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)（AND 聚合对照） |
| 压缩 | `pressure` 前瞻 + `context-overflow` 兜底双入口 | [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) |
| 长期记忆 | 无完整跨会话系统，仅 Compaction 服务当前会话 | [ClaudeCode](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)（CLAUDE.md 对照） |

## Links

- [DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) / [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 上下文压缩的通用机制与各家实现对比
- [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md) — 另一种 Agent Loop 结束判断（AND 聚合）的实现
- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) — 另一种"本地优先 + 多 agent 路由"的 agent 网关
- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md) — 通用 Python Agent 框架
- [AgentScopeJava](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md) — 同族不同语言的 Java 版 Agent 框架（Session Log 持久化、Workspace/沙箱、Skill 市场）
- [TypeScript](/docs/CS/TypeScript/TypeScript.md) / [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)

## References

### Official Docs

- [Cordis 框架教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)
- [Cordis](https://github.com/cordiverse/cordis) / [时空可组合性论文](https://github.com/cordiverse/paper)
- 官方子系统文档（与源码同步生成）：[approval](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md) / [sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md) / [filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/filesystem.md) / [tools](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/tools.md) / [shell](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/shell.md) / [permission-presets](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/permission-presets.md)

### Community Deep Analysis (2026-08 ~ 2026-09)

源码深读系列，基于 DeepSeek Harness 源码（MIT，`0.1.1-rc.1`）与官方 Agent Notes 整理：

- [DSH：DeepSeek Harness 架构解析](https://mp.weixin.qq.com/s/Kf87hcNdSmY4ODWI4UZ8cg)
- [为什么 DSH 把一切都做成插件？Cordis 又是什么？](https://mp.weixin.qq.com/s/EDx6e1AEKalz6dEXdyWFSg)
- [DeepSeek Harness 底层原理图解（时序图 + 流程图）](https://mp.weixin.qq.com/s/1NWC0Qk-bDkvr8QIVPr1Zg)
- [DSH 和 Pi 的 Agent Loop 循环结束判断架构细节解析](https://mp.weixin.qq.com/s/7KJgpnKQ0VVHe-oMnS2L5Q)
- [DSH 的 Cordis 插件架构](https://mp.weixin.qq.com/s/XFWvHB8ke_LjcSZ06IajsA)
- [DSH 的上下文管理、记忆和知识库剖析](https://mp.weixin.qq.com/s/RG5oQ6rpNDNn7Fwo9GoqIA)
- [DSH 的宝藏之一：Session 持久化的设计](https://mp.weixin.qq.com/s/uH3vuY9nNCmp-q4yUtRRYA)
- [源码深读 04：起一个子进程只要十行，送走它用了五百行（subprocess-local）](https://mp.weixin.qq.com/s/mmprMkOaTMP2IBTeH6uQuw)
