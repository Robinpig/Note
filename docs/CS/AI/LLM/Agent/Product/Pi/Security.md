## Introduction

Pi **不内置权限系统**：它跑在哪个目录就能访问该目录的全部文件，工具调用不弹确认框，收到删文件指令就执行——运行身份就是启动它的那个操作系统用户。这不是疏漏而是定位（minimal harness），安全边界因此全部外移：**project trust 管「加载什么」，隔离环境管「够得着什么」**。本页把这两层加上凭证处理一次讲完。

> 官方安全模型的第一性原理：把模型生成的命令与代码当作**不可信输入**。文件、注释、指令、命令输出、模型回复都能经 prompt injection 操纵模型；看转录、用 trust、review 改动**都不构成安全边界**——它们降低暴露或加速恢复，但不限制生成动作能碰到什么。

## Project Trust

Project trust 控制一个工作文件夹的哪些资源会被加载，防的是「打开一个陌生仓库，它的可执行扩展悄悄跑起来」。发现以下任一项时 Pi 要求信任决策：

```text
.pi/settings.json / .pi/mcp.json
.pi/extensions / .pi/skills / .pi/prompts / .pi/themes
.pi/SYSTEM.md / .pi/APPEND_SYSTEM.md
项目 .agents/skills（当前目录或其祖先）
```

（裸 `.pi` 目录不触发。）授予后加载：项目设置、`.pi/mcp.json` 的 MCP server、上述扩展/技能/模板/主题、设置里声明但缺失的包、项目级与项目包的扩展。决策链自上而下：

1. CLI `--approve` / `--no-approve`（一次性进程级）；
2. 用户级/命令行扩展处理 `project_trust` 事件——第一个返回 yes/no 的扩展说了算；
3. 已存决策：`~/.pi/agent/trust.json`，取**最近祖先目录**的记录（`/trust` 手动存）；
4. 全局 `defaultProjectTrust` 设置，默认 `"ask"`。

print / JSON / RPC 模式弹不出交互提示：无覆盖时 `"always"` 加载受保护资源，`"ask"`/`"never"` 跳过。两个边界要记牢：**`sessionDir` 先于 trust 解析**（拒绝信任撤不回那次会话目录查找）；**上下文文件（`AGENTS.md` 等）不受 trust 约束**——拒绝信任也要把文件夹里的指令当不可信输入。

## Isolation Methods

Pi 自己不带沙箱，隔离靠外部环境。四种方法的差别在「Pi 进程在哪」和「凭证怎么处理」：

| 方法 | Pi 运行位置 | 隔离范围 | 凭证处理 |
| :--- | :--- | :--- | :--- |
| Plain Docker | 容器内 | Pi、内置工具、`!` 命令、扩展全在内 | 凭证随环境变量进容器 |
| Docker Sandboxes | 托管沙箱内 | 同上 | **真凭证留宿主机**，代理在出口替换 |
| OpenShell（NVIDIA） | 本地/远程沙箱内 | 文件、进程、网络、凭证、推理路由全策略化 | 策略化凭证 + 推理路由，原始密钥可不出沙箱 |
| Gondolin 扩展 | **宿主机** | 只把内置工具与 `!` 命令路由进 Linux 微虚拟机 | Pi 凭证留宿主机，但 VM 内命令继承宿主机环境变量 |

选 Docker Sandboxes 的典型动机是凭证：配好 `sbx secret` 后沙箱里只拿到 OAuth 形状的占位符，代理仅对配置主机替换真值；OpenShell 额外提供 inference routing，可把模型流量指向网关的兼容端点；Gondolin 最轻（Node ≥ 23.6 + QEMU，覆盖 `read`/`write`/`edit`/`bash`/`grep`/`find`/`ls` 七个工具），但**其他扩展工具仍在宿主机跑**，除非它们自己显式委派——别把它当凭证边界用，除非先清掉敏感环境变量。

Plain Docker 的最小形态：

```dockerfile
FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent
WORKDIR /workspace
ENTRYPOINT ["pi"]
```

```bash
docker run --rm -it -e ANTHROPIC_API_KEY -v "$PWD:/workspace" -v pi-agent-home:/root/.pi/agent pi-sandbox
```

`pi-agent-home` 这个命名卷让容器内的设置/凭证/会话跨次保留；**别把宿主机 `~/.pi/agent` 挂进去**，除非容器本来就应该拿到你的全部 Pi 配置与凭证。挂载即授权：读写挂载 = 可改宿主机文件，传进去的环境变量 = 容器内进程可见，网络开放 = 代码与输出可能外流。

## Credentials

凭证默认存 `~/.pi/agent/auth.json`（`/login` 写入，`/logout` 清除）；CI 等场景可改用 provider 环境变量，让 Pi 不落盘。解析顺序：运行时 `--api-key` > `auth.json` > `models.json` 的 `apiKey` > 环境变量/云 ambient 凭证。原则：只给任务所需的最小权限、用短时效窄范围凭证、能放宿主机就别放进隔离环境。

## Reduce Impact and Improve Recovery

不构成边界但降低暴露的实践：只暴露任务所需文件与服务；大改前快照/备份/版本控制；装扩展和包前过源码（扩展跑在 Pi 进程内）；导出的会话先 review 再外发；把生成的 diff 应用到别的系统前先看。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md) — 扩展与包的信任门槛
- [Approval 与沙箱（Codex）](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) — 对照：内置审批流的另一种设计
- [Permission 理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md) — 权限模型的通用框架

## References

- [Pi Security](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/security.md)
- [Pi Containerization](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/containerization.md)
- [Pi Configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md)
