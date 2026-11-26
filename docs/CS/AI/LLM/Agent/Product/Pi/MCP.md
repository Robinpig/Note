## Introduction

`pi-mcp` 是 Pi 自带的 **Model Context Protocol 客户端**：自己实现 JSON-RPC 2.0、四种 transport、OAuth 流程与结果裁剪，不依赖官方 MCP TypeScript SDK。但「完全自研」也不准确——OAuth 那一支明确标注改编自官方 SDK v1.29.0 的 `client/auth.ts`，去掉了 SDK/Zod 依赖并改用 WebCrypto 做 PKCE。本页按 v1.5.2（commit `b4afdddf`）源码核验。

它只负责**连上 server、收发 JSON-RPC、把结果变成 Pi 能用的内容**；在 coding-agent 里以内置扩展 `createMcpExtension()` 接入，工具默认注册为 `mcp__<server>__<tool>` 且 `exposure: "codemode"`（模型工具声明里看不到，只能从脚本可达），详见 [CodeMode](/docs/CS/AI/LLM/Agent/Product/Pi/CodeMode.md)。协议本身见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)。

三个容易写错的点：① 客户端的 `initialize` **不可取消**（MCP 规范要求），其他请求可取消；② `McpTransport.send()` 拿到的是 `AbortSignal`，取消后**不得再派发**（例如 token 刷新后的重试）；③ 工具名不保证唯一——`a-b` 与 `a_b` 会清洗成同一个名字，需要冲突时追加 SHA-256 后缀。

## Protocol Layer

`protocol/jsonrpc.ts` 是纯函数层：JSON-RPC 2.0 的类型守卫（`isJsonRpcRequest` / `isJsonRpcResponse` / `isJsonRpcNotification`）、错误码表、解析与 `toError()`。所有 transport 共用一个 `McpTransport` 接口，`send()` 的第二个参数带可取消信号；监听器注册统一由抽象基类 `TransportEvents` 记账，`emitClose()` 保证每个 transport 最多触发一次 close：

```ts
export interface McpTransport {
	start(): Promise<void>;
	send(message: JsonRpcMessage, options?: McpTransportSendOptions): Promise<void>;
	close(): Promise<void>;
	onMessage(listener: McpTransportMessageListener): () => void;
	onError(listener: McpTransportErrorListener): () => void;
	onClose(listener: McpTransportCloseListener): () => void;
	setProtocolVersion?(version: string): void;
}
```

`DEFAULT_MAX_MESSAGE_BYTES` 是 16 MiB。这里的取消语义很细：`AbortSignal` 在「请求被取消 / 超时 / 已收到回复 / 客户端关闭」时触发，transport 不能再派发消息（比如授权刷新后的重试），但它**不能撤销已经派发出去的消息**。

## Client and Correlation

连接后客户端持有 transport 与状态（`disconnected` / `connecting` / `connected` / `closing` / `closed`）。每个请求分配递增数字 id，用 `pending: Map<id, PendingRequest>` 做响应关联；`onProgress` 存在时把 id 作为 `progressToken` 塞进 `_meta`。关键约束写在 `requestInternal` 里：

```ts
		const id = this.nextRequestId++;
		const progressToken = options.onProgress ? id : undefined;
		const requestParams =
			progressToken === undefined
				? params
				: { ...params, _meta: { ...(isObject(params?._meta) ? params._meta : {}), progressToken } };
		const message: JsonRpcRequest = {
			jsonrpc: "2.0",
			id,
			method,
			...(requestParams === undefined ? {} : { params: requestParams }),
		};
		return new Promise<unknown>((resolve, reject) => {
			const entry: PendingRequest = {
				resolve,
				reject,
				timeoutMs: options.timeoutMs ?? this.options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
				timer: undefined,
				signal: options.signal,
				// The spec forbids cancelling `initialize`.
				onAbort: () =>
					this.cancelPending(
						id,
						new McpAbortError(),
						method !== "initialize",
						String(options.signal?.reason ?? "Aborted"),
					),
				sendController: new AbortController(),
				cancellable: method !== "initialize",
				onProgress: options.onProgress,
				progressToken,
			};
```

`handleMessage()` 按响应 / server 发起的请求 / notification 分派：响应找 `pending` 并结算；server 请求查 `requestHandlers`，未注册就回 `methodNotFound`；notification 走 `notifications/progress` 与 `notifications/cancelled` 后广播给监听器。分页辅助 `listAll()` 会一路跟 `nextCursor`，但用 `Set` 检测重复 cursor（防 server 死循环），上限 `MAX_LIST_PAGES`，超限直接抛错。`callTool()` 的结果经过 `validateCallToolResult()` 校验后才返回——自研客户端仍有严格的结果形状检查。

## Transports

| Transport | 适用 | 特点 |
| :--- | :--- | :--- |
| `stdio` | 本地子进程 | child_process 管道，换行分隔的 JSON-RPC |
| `pipe` | 显式传入的 duplex 流 | 与 stdio 共用分帧逻辑，但不自己 spawn |
| `lines` | 任意 `ReadableStream` / writer | 纯换行分帧，不绑定进程 |
| `streamable-http` | 远程 HTTP server | POST 请求 + SSE 回传，带 session id、断线重连、401 后刷新 token |
| `in-memory` | 测试 | 成对的 client/server 端，无 I/O |

`streamable-http` 的难度在 SSE：`consumeSseStream()` 自己解析 `data:` / `event:` / `id:` / `retry:`，兼容 CRLF / LF / 裸 CR 三种行结束，并对**未闭合事件的数据量**设上限，防止大量短 `data:` 行无限增大缓冲区：

```ts
		if (field === "data") {
			dataBytes += Buffer.byteLength(value) + (dataLines.length > 0 ? 1 : 0);
			if (dataBytes > maxEventBytes) throw new Error(`MCP SSE event exceeds ${maxEventBytes} bytes`);
			dataLines.push(value);
		} else if (field === "event") eventName = value;
		else if (field === "id" && !value.includes("\0")) {
			eventId = value;
			options.onId?.(value);
		} else if (field === "retry" && /^\d+$/.test(value)) options.onRetry?.(Number(value));
```

重连用指数退避（默认 1s 起、30s 上限、5 次），`onId` 收到 SSE `id` 用于恢复，`onRetry` 尊重服务端建议。401 时先走 `AuthProvider` 刷新再重放——这正是 `send()` 的 `signal` 存在的原因：一旦请求已结算，刷新后的重放必须放弃。

## OAuth

`oauth/flow.ts` 的文件头把来源讲得很清楚：

```ts
/*
 * Adapted from modelcontextprotocol/typescript-sdk v1.29.0 src/client/auth.ts.
 * Copyright (c) 2024 Anthropic, PBC. Licensed under MIT; see THIRD_PARTY_NOTICES/.
 * Modified to remove SDK/Zod dependencies and use WebCrypto for PKCE.
 */
```

`OAuthClientProvider` 是宿主实现的接口，包本身不碰浏览器跳转与持久化：宿主提供 `redirectUrl`、`clientMetadata`、`tokens()` / `saveTokens()`、`saveCodeVerifier()` / `codeVerifier()`、`redirectToAuthorization()`，可选 `clientMetadataDocument()` 用 CIMD（Client ID Metadata Document）代替动态注册，`invalidateCredentials()` 分类清除 client / tokens / verifier / discovery。发现阶段解析 `WWW-Authenticate`、AS metadata 与 resource 选择，并校验 issuer 一致性。PKCE 用 WebCrypto 生成，因此没有 Zod、没有 SDK、浏览器和 Node 都能跑。

## Naming and Schemas

工具名规则固定在 `naming.ts`，同时服务于模型工具声明和 codemode 脚本调用：

```ts
export function createMcpToolName(
	server: string,
	tool: string,
	isTaken: (name: string) => boolean = () => false,
): string {
	const name = `mcp__${server}__${tool}`.replace(/[^A-Za-z0-9_]/g, "_");
	if (name.length <= MAX_TOOL_NAME_LENGTH && !isTaken(name)) return name;
	const hash = createHash("sha256").update(`${server}\0${tool}`).digest("hex").slice(0, 8);
	return `${name.slice(0, MAX_TOOL_NAME_LENGTH - hash.length - 1)}_${hash}`;
}
```

provider 对工具名的限制是 64 字符 `[A-Za-z0-9_-]`；非字母数字下划线一律变 `_`（与 Codex 一致），超长或撞名就截短并附 8 位 SHA-256 后缀。`mcpNamespace(server)` 把 server 名的 `-` 换成 `_`——所以配置里同时出现 `foo-bar` 和 `foo_bar` 会共享命名空间，属于配置错误。

`input-schema.ts` 把 server 返回的 JSON Schema 转成三种用途：`toInputSchema()` 保留原 schema 给 provider，`flattenUnionBranches()` 把 `anyOf` / `$ref` 的候选分支摊平用于工具搜索排序，`forTool()` / `forModel()` 做 provider 侧裁剪。`output-limit.ts` 则处理「MCP 工具返回一大坨文本」：上限 20 KiB，从中间切开保留首尾，把全文存到文件并把路径告诉模型：

```ts
export const MCP_OUTPUT_MAX_BYTES = 20 * 1024;

function truncateMiddle(text: string, maxBytes: number): MiddleTruncation | undefined {
	const buf = Buffer.from(text, "utf-8");
	if (buf.length <= maxBytes) return undefined;
	// Continuation bytes (10xxxxxx) are not character starts.
	const isBoundary = (index: number) => index >= buf.length || (buf[index] & 0xc0) !== 0x80;
	let headEnd = Math.floor(maxBytes / 2);
	while (headEnd > 0 && !isBoundary(headEnd)) headEnd--;
	let tailStart = buf.length - (maxBytes - Math.floor(maxBytes / 2));
	while (tailStart < buf.length && !isBoundary(tailStart)) tailStart++;
	const head = buf.subarray(0, headEnd).toString("utf-8");
	const tail = buf.subarray(tailStart).toString("utf-8");
	const removedChars = Array.from(buf.subarray(headEnd, tailStart).toString("utf-8")).length;
	// A final newline ends the last line instead of starting another.
	const lines = text.split("\n").length - (text.endsWith("\n") ? 1 : 0);
	return { content: `${head}…${removedChars} chars truncated…${tail}`, totalBytes: buf.length, totalLines: lines };
}
```

切点按 UTF-8 字节边界回退 / 前进，不会切出半个汉字；图片块不受截断影响，原样跟在文本块后面。

## Corrections

| 常见误述 | 源码事实 |
| :--- | :--- |
| 直接用官方 MCP TypeScript SDK | JSON-RPC / transport / 结果校验自研；只有 OAuth 明确改编自官方 SDK v1.29.0 的 `client/auth.ts`（去 Zod、改 WebCrypto PKCE） |
| `initialize` 和普通请求一样可取消 | 规范禁止；源码用 `cancellable: method !== "initialize"` 显式关掉 |
| transport 拿到取消信号后可以随便重试 | 信号一旦触发就不得再派发；它也不撤销已发出的消息 |
| 工具名 `mcp__<server>__<tool>` 唯一且不限长 | provider 限 64 字符；非法字符清洗后可能撞名，冲突或超长追加 8 位 hash |
| 长输出直接截断给模型 | 20 KiB 中间截断，保留首尾、报告总行数与估算 token，并可保存全文供模型用 `offset/limit` 读取 |
| Pi 把 MCP 工具直接列进模型工具声明 | 默认是 `exposure: "codemode"`（deferred），只从脚本可达；只有显式 `direct` 才直接暴露 |

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [CodeMode：脚本调工具](/docs/CS/AI/LLM/Agent/Product/Pi/CodeMode.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Tools：默认工具集](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)
- [Security：信任与隔离](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)

## References

- [pi-mcp README（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/README.md)
- [McpClient（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/client.ts)
- [JSON-RPC 协议层（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/protocol/jsonrpc.ts)
- [Transport 契约（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/transports/transport.ts)
- [Streamable HTTP transport（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/transports/streamable-http.ts)
- [OAuth flow（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/oauth/flow.ts)
- [工具命名与输出裁剪（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/mcp/src/naming.ts)
