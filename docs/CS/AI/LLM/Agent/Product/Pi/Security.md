## Introduction

Pi **不内置权限系统**：它跑在哪个目录就能访问该目录的全部文件，工具调用不弹确认框，收到删文件指令就执行——运行身份就是启动它的那个操作系统用户。这不是疏漏而是定位（minimal harness），安全边界因此全部外移：**project trust 管「加载什么」，隔离环境管「够得着什么」**。本页按 v1.5.2（commit `b4afdddf`）源码核验，把这两层加上凭证处理一次讲完。

> 官方安全模型的第一性原理：把模型生成的命令与代码当作**不可信输入**。文件、注释、指令、命令输出、模型回复都能经 prompt injection 操纵模型；看转录、用 trust、review 改动**都不构成安全边界**——它们降低暴露或加速恢复，但不限制生成动作能碰到什么。

## Project Trust

Project trust 控制一个工作文件夹的哪些资源会被加载，防的是「打开一个陌生仓库，它的可执行扩展悄悄跑起来」。v1.5.2 把判定收在 `resolveProjectTrusted()` 一条决策链里（`src/core/project-trust.ts`）：

```typescript
export async function resolveProjectTrusted(options: ResolveProjectTrustedOptions): Promise<boolean> {
	if (options.trustOverride !== undefined) {
		return options.trustOverride;
	}
	if (!hasTrustRequiringProjectResources(options.cwd)) {
		return options.trustStore.get(options.cwd) ?? true;
	}

	if (options.extensionsResult) {
		const { result, errors } = await emitProjectTrustEvent(
			options.extensionsResult,
			{ type: "project_trust", cwd: options.cwd },
			options.projectTrustContext,
		);
		for (const error of errors) {
			options.onExtensionError?.(`Extension "${error.extensionPath}" project_trust error: ${error.error}`);
		}
		if (result) {
			const trusted = result.trusted === "yes";
			if (result.remember === true) {
				options.trustStore.set(options.cwd, trusted);
			}
			return trusted;
		}
	}
```

决策链自上而下：

1. **CLI 覆盖**：`--approve` / `--no-approve`（一次性进程级，`trustOverride`）直接返回；
2. **无信任资源短路**：工作目录没有任何需信任资源时，取 `trustStore.get(cwd)`，无记录则默认 `true`；
3. **`project_trust` 扩展事件**：用户级/命令行扩展处理该事件，**第一个**返回 yes/no 的扩展胜出（`remember: true` 时还会写回存储）；
4. **已存决策**：`trustStore.get(cwd)`，包含**父目录**查找；
5. **`defaultProjectTrust` 设置**：`always` → true、`never` → false、`ask` → 继续问；
6. **无 UI 返回 false**：print/json/rpc 模式弹不出提示，`ask` 且 `hasUI` 为假时直接拒绝；
7. **`ui.select` 四选项**：交互模式弹出信任选择器。

链尾的源码补上后三步：

```typescript
	const decision = options.trustStore.get(options.cwd);
	if (decision !== null) {
		return decision;
	}

	switch (options.defaultProjectTrust ?? SETTINGS_DEFAULTS.defaultProjectTrust) {
		case "always":
			return true;
		case "never":
			return false;
		case "ask":
			break;
	}

	if (!options.projectTrustContext.hasUI) {
		return false;
	}

	const selected = await selectProjectTrustOption(options.cwd, options.projectTrustContext);
	if (selected !== undefined) {
		saveProjectTrustPromptResult(options.trustStore, selected);
		return selected.trusted;
	}
	return false;
}
```

`ui.select` 的选项来自 `getProjectTrustOptions()`，带 session-only 时是四项：Trust / Do not trust / Trust parent folder / Do not trust (this session only)——「信任父目录」让一次决策覆盖整个仓库树。

### Trust Store

决策存 `agentDir/trust.json`，结构是 `Record<path, true | false | null>`，`null` 表示**不信任父级**（写入时 null 被删键、只保留显式 yes/no）。值为 `true`/`false` 的键按规范路径匹配，读取时从 cwd 逐级向父目录找最近一条：

```typescript
function findNearestTrustEntry(data: TrustFile, cwd: string): ProjectTrustStoreEntry | null {
	let currentDir = normalizeCwd(cwd);
	while (true) {
		for (const key of findTrustFileKeys(data, currentDir)) {
			const value = data[key];
			if (value === true || value === false) {
				return { path: key, decision: value };
			}
		}

		const parentDir = dirname(currentDir);
		if (parentDir === currentDir) {
			return null;
		}
		currentDir = parentDir;
	}
}
```

读写经 **proper-lockfile 同步锁**串行化，避免多进程同时改 trust 文件（`acquireTrustLockSync`，`src/core/trust-manager.ts`）：

```typescript
	for (let attempt = 1; attempt <= maxAttempts; attempt++) {
		try {
			return lockfile.lockSync(trustDir, { realpath: false, lockfilePath: `${path}.lock` });
		} catch (error) {
			const code =
				typeof error === "object" && error !== null && "code" in error
					? String((error as { code?: unknown }).code)
					: undefined;
			if (code !== "ELOCKED" || attempt === maxAttempts) {
				throw error;
			}
			lastError = error;
			const start = Date.now();
			while (Date.now() - start < delayMs) {
				// Sleep synchronously to avoid changing trust store callers to async.
			}
		}
	}
```

### Trust-Requiring Resources

`hasTrustRequiringProjectResources()` 判定哪些资源触发信任：`.pi` 目录下命中以下任一，或**当前目录及其祖先**存在 `.agents/skills`（用户级 `~/.agents/skills` 永远视为可信、不在此列，即使 cwd 是 `$HOME`）。资源清单（`src/core/trust-manager.ts`）：

```typescript
const TRUST_REQUIRING_PROJECT_CONFIG_RESOURCES = [
	"settings.json",
	"mcp.json",
	"extensions",
	"skills",
	"prompts",
	"themes",
	"SYSTEM.md",
	"APPEND_SYSTEM.md",
] as const;
```

（裸 `.pi` 目录不触发。）授予后加载：项目设置、`.pi/mcp.json` 的 MCP server、上述扩展/技能/模板/主题、设置里声明但缺失的包、项目级与项目包的扩展。两个边界要记牢：**`sessionDir` 先于 trust 解析**（拒绝信任撤不回那次会话目录查找）；**上下文文件（`AGENTS.md` 等）不受 trust 约束**——拒绝信任也要把文件夹里的指令当不可信输入。print / JSON / RPC 模式弹不出交互提示：`"always"` 加载受保护资源，`"ask"`/`"never"` 跳过。

## Isolation Methods

Pi 自己不带沙箱，隔离靠外部环境。四种方法的差别在「Pi 进程在哪」和「凭证怎么处理」——Docker 拆成两类，加 OpenShell 与 Gondolin extension 共四种：

| 方法 | Pi 运行位置 | 隔离范围 | 凭证处理 |
| :--- | :--- | :--- | :--- |
| Plain Docker | 容器内 | Pi、内置工具、`!` 命令、扩展全在内 | 凭证随环境变量进容器 |
| Docker Sandboxes | 托管沙箱内 | 同上 | **真凭证留宿主机**，代理在出口替换 |
| OpenShell（NVIDIA） | 本地/远程沙箱内 | 文件、进程、网络、凭证、推理路由全策略化 | 策略化凭证 + 推理路由，原始密钥可不出沙箱 |
| Gondolin 扩展 | **宿主机** | 只把内置工具与 `!` 命令路由进 Linux 微虚拟机 | Pi 凭证留宿主机，VM 内命令继承宿主机环境变量 |

选 Docker Sandboxes 的典型动机是凭证：配好 `sbx secret` 后沙箱里只拿到 OAuth 形状的占位符，代理仅对配置主机替换真值；OpenShell 额外提供 inference routing，可把模型流量指向网关的兼容端点；Gondolin 最轻（Node ≥ 23.6 + QEMU，覆盖 `read`/`write`/`edit`/`bash`/`grep`/`find`/`ls` 七个工具），但**其他扩展工具仍在宿主机跑**，除非它们自己显式委派。尤其注意：**Gondolin 的命令继承宿主机环境变量，它不是凭据边界**——别把它当凭证隔离用，除非先清掉敏感环境变量。

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
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Approval 与沙箱（Codex）](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)
- [Permission 理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [MCP：客户端与 OAuth](/docs/CS/AI/LLM/Agent/Product/Pi/MCP.md)

## References

- [Pi Security（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/security.md)
- [Pi Containerization（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/containerization.md)
- [resolveProjectTrusted 信任决策链（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/project-trust.ts)
- [ProjectTrustStore / 触发资源（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/trust-manager.ts)
- [Pi Configuration（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/configuration.md)
