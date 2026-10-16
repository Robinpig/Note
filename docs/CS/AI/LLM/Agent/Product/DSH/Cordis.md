> 版本基线：核实于 2026-10-06。Cordis 是 DeepSeek Harness 底层的 TypeScript 插件框架，设计论文：[*A Programming Paradigm for Spatiotemporal Composability*](https://arxiv.org/abs/2608.25512)。参考：[Cordis 教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)（概念参考见 [Cordis 入门](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-primer)，API 见 [Cordis 核心 API](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-api/context)）

## Introduction

Cordis 是 DeepSeek Harness **底层的插件框架**：一个 TypeScript 编写的小型运行时（元框架，Meta-Framework of Spatiotemporal Composability），每项能力——工具、LLM 适配器、文件访问乃至 agent loop 本身——都是挂载到**共享上下文（Context）**中的插件。

- 由开发者 Shigma 于 2022 年创建，其 GitHub 资料显示已加入 DeepSeek
- Cordis 不提供业务功能，只提供**组织功能的方式**：谁提供能力、谁使用能力、何时启动、如何退出、不同场景加载哪组能力
- DSH 把 Cordis 源码放进 `vendor/`（固定上游提交、包名重映射到 `@deepseek-ai`），本地修改包含 Fiber 重入卸载加固、配置更新事务、HMR 精确监听、延迟配置解析——增加维护成本，换来框架层的可审计性

与面向 harness 的插件（`cordis.yml` 加载、Web UI 驱动）不同，Cordis 教程用单文件启动器在临时目录中动手构建，**无需 API 密钥**。

## Runtime Environment

```sh
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness && pnpm install

mkdir -p tmp/cordis-tutorial   # tmp/ 已被 git 忽略
cd tmp/cordis-tutorial
node --import tsx ../../vendor/cordis/bin.js   # 每一章都用这条命令
```

启动器（`vendor/cordis/bin.js`）创建根 `Context`、挂载 Loader 插件，从当前目录加载 `./cordis.yml`——有哪些插件、如何配置，全部来自 YAML 文件。`--import tsx` 让 Node 免构建直接运行 TypeScript。

## Context: A Shared "Capability Service Desk"

`ctx` 是**经 Proxy 包装的 service 解析边界**，不是装满单例的对象：

- 服务通过稳定名称出现在 `ctx` 上（`ctx.llm` / `ctx.tools` / `ctx.sessions`）；调用方只关心"我要模型能力"，不关心背后是哪家模型、哪个 SDK
- 未在 `inject` 中声明就读取 `ctx.foo` 会报错；`ctx.get("foo")` 底层读取不受限（显式接受服务可能不存在）
- 子 Context 通过原型继承父级 service，隔离映射按层遮蔽，局部配置无需复制整棵容器
- **依赖约束 ≠ 权限控制**：原生 JS 插件仍在宿主进程执行，未注入 `fs` 不代表 OS 层失去文件访问

## Fiber: Plugin Instances and State Machines

Plugin 是定义，**Fiber 是挂载实例记录**：父 Context、原始配置、解析后配置、依赖实现快照、生命周期状态、disposables。

- 依赖未就绪 → Fiber 保持 `PENDING`；就绪后进入 `LOADING` → `ACTIVE`；启动失败 → `FAILED`
- **配置文件条目顺序不承担启动顺序，依赖关系才承担**——解决了传统插件系统遍历数组依次 `init` 的隐含顺序顽疾
- Provider 消失或换实现时，Fiber 身份变化刷新依赖 epoch，触发旧 Consumer 卸载与新重载。Cordis 维护的是**随 Provider 变化刷新的运行图**，不是启动一次解析完的 DI 容器
- 卸载时按注册**逆序**执行清理并等待异步清理达到静止（quiescence）；单次 effect 内 disposer 逆序串联，**多个 Fiber 顶层 effect 是并发清理**（非严格 LIFO 栈）
- vendor 版本还处理重入边界：effect 执行 setup 前先登记所有者包装；同步卸载观察者；异步 cleanup 期间其他调用者可等待同一次清理；`UNLOADING` 状态拒绝创建新 effect

## Spatial Composition: isolate and dsh-scope

两层空间模型，分别解决"哪个服务实例"和"哪些注册项可见"：

- **`isolate` / realm（实例隔离）**：为指定服务名创建 realm 标签，服务注册和查找以标签定位——同名服务可在不同子上下文各自存在。两个 Agent 访问 `ctx.tools` 可得各自目录。适合**替换提供方**
- **`dsh-scope`（注册可见性）**：用不透明对象作 scope key，维护父子关系，创建带路由身份的事件 receiver。注册视图沿父链**向下**继承（Agent 看到 preset 的提示词和工具），事件沿链**向上**接纳（preset 级监听器收到其下 Agent 事件，兄弟 Agent 互不串线）

Agent preset 是空间组合的完整应用：preset 配置挂在长期存在的 scope 下，相同 preset 的并发首次挂载通过 single-flight 共享；文件变化后新会话加入新一代组合，已有会话保留原代际（避免会话中途换工具/提示词，代价是旧代际保留到整棵运行时退出）。DSH 还会**审计 preset 子树是否把服务发布到 root realm**——发布则拒绝挂载，防止会话级组合退化成进程全局状态。

## Time Composition: effect and Configuration Transactions

- 每次 `ctx.effect()` 登记 disposer，资源获取与释放写在同一 effect，防失配；`ctx.on()`、`ctx.provide()` 都接入 effect 所有权
- 与 React Hooks 对照：`useEffect` 把 cleanup 存进 Hook 链表，Cordis 把 disposer 存进 Fiber——都是"框架持有所有权，作者只声明建立/撤销"
- **可逆 ≠ 事务**：disposer 只能补偿，无法回滚外部世界（已发网络消息、已写共享文件不回滚）；未登记的进程/句柄不会自动消失
- **插件不仅要插得进去，还要拔得干净**；"谁创建，谁清理"不是约定，而是 Cordis 管理的运行时规则——这才让热更新和能力替换变得可信

## Event Contract: Five Dispatch Modes

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

## Comparison with Historical Precedents

- **Eclipse**：扩展点/扩展由宿主清单定义；DSH 连 agent loop 和 UI 都可替换，核心与第三方插件共享同一挂载机制
- **OSGi**：动态服务注册表 + bundle 生命周期已有先例；Cordis 的新意是把动态依赖、作用域上下文、effect 所有权压进一个很小的进程内模型（执行单元是 Fiber——一个函数或 Service 子类即可，而非重量级 bundle）
- **DI 容器**：服务解析不陌生；新组合来自 **DI 与生命周期的绑定**——普通容器只构造对象，定时器/监听器/子进程仍由业务代码清理，Cordis 把注册动作收敛成 effect

## TypeScript Essentials

- **类型注解**（`ctx: Context`、`who: string`、`string[]`）：只描述值，不改变运行时行为
- **`import type { Context } from '@deepseek-ai/cordis'`**：仅导入类型信息，运行时消失，不增加运行时依赖
- **声明合并** `declare module '@deepseek-ai/cordis' { ... }`：为已有接口添加条目（如 `ctx.greeter` 的类型、事件名），**不产生任何运行时接线**，插件须另行提供服务或发出事件
- 第 5 章还会用到 `interface`（描述配置字段）和 `Schema<Config>`（泛型，表示 schema 校验的对象字段）

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Plugin 开发](/docs/CS/AI/LLM/Agent/Product/DSH/Plugin.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)

## References

- [Cordis](https://github.com/cordiverse/cordis) / [时空可组合性论文](https://github.com/cordiverse/paper)
- [Cordis 框架教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)
- [DSH 的 Cordis 插件架构](https://mp.weixin.qq.com/s/XFWvHB8ke_LjcSZ06IajsA)
- [为什么 DSH 把一切都做成插件？Cordis 又是什么？](https://mp.weixin.qq.com/s/EDx6e1AEKalz6dEXdyWFSg)
