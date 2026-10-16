# Workspace

## Introduction

Workspace 解决的是 Agent 与「文件世界」的关系问题：模型只能看见上下文里的文本，但真实任务几乎都要读写文件。AgentScope Java 把这件事拆成三个正交的关注点——**工作区目录**（文件放在哪、谁能改）、**文件系统访问模式**（Agent 以什么身份看这些文件）、**沙箱后端**（这些文件实际落在哪种隔离环境里）。

Python 版把这三件事揉在工具层各自实现，Java 版则提升为一等模块：同一套 Agent 代码，通过替换 Workspace 配置就能从「本地开发直接读写」切换到「容器内隔离执行」再到「K8s Pod 里跑」。

## Directory Layout

一个 Workspace 在磁盘上默认布局：

```text
<workspace-root>/
├── agent/            # 框架层文件（技能、内部状态）
│   └── skills/
├── user/             # 用户层文件（会话产出、上传附件）
├── shared/           # 多 Agent 共享交换区
└── .state/           # 元数据（manifest、锁）
```

两层读写语义：Agent 对 `agent/` 拥有完全控制权（可增删改），对 `user/` 默认只读追加，对 `shared/` 按权限配置。**用户覆盖**机制允许部署方把 `user/` 指向已有业务目录（如挂载的 OSS 桶或宿主目录），框架只记录映射不搬动数据。

## Filesystem Access Modes

Agent 通过 `AgentFileSystem` 抽象访问工作区，三种模式：

| 模式 | 视图 | 典型用途 |
|---|---|---|
| `NATIVE` | 直接操作 JVM 所在文件系统 | 本地开发、CLI 工具 |
| `SCoped` | 只能看见 Workspace 根以内的路径 | 生产服务、多租户隔离 |
| `SANDBOX` | 全部路径经沙箱后端转发 | 不可信代码执行 |

模式在 `Agent` builder 上配置，同一份工具代码无需改动。`SCOPED` 模式下路径穿越（`../`）会被拒绝并在事件流里留下 `PermissionDenied` 记录——这与 Tool 分册的权限系统是两道独立闸门。

## IsolationScope

多 Agent 协作时，`IsolationScope` 定义「哪些 Agent 共享同一份工作区」：

- `GLOBAL`：所有 Agent 共用根工作区；
- `SESSION`：同一 session 内的 Agent 共享，不同 session 隔离；
- `AGENT`：每个 Agent（含子 Agent）独占子树，通过 `shared/` 显式交换。

选 `AGENT` 时，子 Agent 的产出默认落在自己的子树里，主 Agent 要取结果必须显式读取对方路径或走 `shared/`——这避免了「子 Agent 顺手改坏了主 Agent 的文件」这类级联污染。

## Sandbox Backends

沙箱是工作区的执行环境，Java 版内置五类后端：

| 后端 | 隔离强度 | 启动开销 | 适用场景 |
|---|---|---|---|
| `Local` | 无（同进程） | 零 | 开发调试、受信工具 |
| `Process` | 进程级（子 JVM/子进程） | 低 | 半受信代码、资源限额 |
| `Docker` | 容器级 | 中 | CI、单机多租户 |
| `MicroVM`（Firecracker 类） | 硬件虚拟化级 | 较高 | 强隔离多租户 SaaS |
| `Remote` | 远端执行池 | 取决于池 | 集中治理、GPU 任务 |

后端通过统一接口暴露：`exec(command)`、`readFile(path)`、`writeFile(path, content)`、`snapshot()` / `restore(snapshot)`。上层工具（bash、编辑器、文件检索）完全不感知底层是本地还是容器。

## Snapshot And Restore

`snapshot()` 为当前沙箱文件系统生成一个快照句柄（增量基于 blob 存储），`restore()` 把沙箱回滚到该点。两个典型用法：

- **任务重试**：Agent 执行到一半失败，回滚到任务起点换个策略重来，避免半成品文件干扰；
- **会话分叉**：Session 分叉时同步分叉工作区，两个分支各自演进互不污染。

## Runtime Image Contract

容器/MicroVM 后端依赖「运行时镜像」——镜像里预装 Agent 需要的工具链（git、python、jdk 等）。框架对镜像有契约要求：入口是一个长期驻留的 exec 服务进程、工作区以约定卷路径挂入、环境变量注入框架配置。官方提供基础镜像，自定义镜像需满足同一契约。

## K8s PVC Persistence

在 K8s 上部署时，工作区通常挂在 PVC 上，使 Pod 重建后文件不丢。要点：

- `SESSION` 级工作区对应「一个 PVC（或子目录）绑一个 session」，Pod 调度到哪数据跟到哪；
- `AGENT` 级隔离在 Pod 内用目录权限实现，不强行拆 PVC（避免卷数量爆炸）；
- 官方文档提醒：PVC 的读写模式（RWO/RWX）直接决定能否多副本共享同一 session，`RWO` 下多副本必须靠 Service 层串行化，不能指望文件锁。

## Production Deployment Matrix

官方给出的选型矩阵（按隔离需求 × 运维成本）：

- **内部工具 / 受信 Agent**：`Local` + `NATIVE`，零额外运维；
- **SaaS 多租户**：`MicroVM` + `SCOPED` + `SESSION` 工作区，每租户一 VM；
- **CI / 批量任务**：`Docker` + 短生命周期 Pod，任务结束即焚；
- **强合规（金融等）**：`Remote` 执行池 + 全量审计事件外发，沙箱内无持久状态。

## Links

- [AgentScopeJava 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [Tool](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [Skill](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- https://java.agentscope.io/v2/zh/docs/harness/workspace
- https://java.agentscope.io/v2/zh/docs/harness/filesystem
- https://java.agentscope.io/v2/zh/docs/harness/sandbox
- https://java.agentscope.io/v2/zh/docs/others/going-to-production
