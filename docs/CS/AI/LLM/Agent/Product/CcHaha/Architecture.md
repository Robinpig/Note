## Introduction

cc-haha 的架构可以拆成两层：**Electron 桌面外壳**与 **`claude-haha` CLI 内核**。内核是从 Claude Code 源码修复而来的 agentic harness（负责模型推理、工具行动、上下文管理）；桌面外壳提供 GUI 工作区、可视化审批、内置预览与远程访问。两者通过**子进程 + NDJSON 管道**和**本地 HTTP 服务**通信。

本页覆盖外壳与内核的**边界与连接机制**，底层 agentic loop / hooks / memory / subagents / skills / MCP 的细节见 [ClaudeCode 家族](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)（同源，不在此重写）。事实基线：GitHub `main` 分支（最近 push 2026-10-17），源码路径相对仓库根。

## Tech Stack

Electron + React + Vite（桌面渲染）+ Bun（运行时）+ Ink + Commander.js + Anthropic SDK。CLI 内核用 Bun 运行，桌面端用 React / Vite，Ink 用于终端 UI 部分。

## Shell Wires the Engine as a Child Process

桌面**不把引擎嵌进渲染进程**，而是把 `claude-haha` 作为**子进程 spawn 出来、用 stdin/stdout 走 NDJSON 管道**驱动（`sessionRunner.ts:335` `spawn(execPath, args, {stdio:['pipe','pipe','pipe']})`）：

- 启动参数含 `--print --sdk-url <ingress> --session-id --input-format stream-json --output-format stream-json --replay-user-messages`（`sessionRunner.ts:287-304`）。
- 子进程 stdout 按行解析为 NDJSON 事件（`sessionRunner.ts:369-446`），stdin 回写控制消息（含 token 刷新 `sessionRunner.ts:527-542`）。
- 认证 / 传输经环境变量：`CLAUDE_CODE_SESSION_ACCESS_TOKEN`、`CLAUDE_CODE_USE_CCR_V2`、`CLAUDE_CODE_WORKER_EPOCH`（`sessionRunner.ts:306-323`）。

引擎侧另跑一个**进程内 REPL bridge**（`replBridge.ts`），把子会话接到远端后端（`claude.ai/code` 的「code sessions」）：v1 走 `HybridTransport`/WebSocket，v2 走 SSE + CCR（`replBridge.ts:34-39`）。所以链路是：**桌面 spawn 引擎子进程 → 引擎内 REPL 桥接服务端 → 服务端再与桌面回环控制消息**。

## IPC Channel Model

Electron 主进程与 React 渲染进程之间约 **90 个 IPC 通道**（`desktop/electron/ipc/channels.ts` 的 `ELECTRON_IPC_CHANNELS`，`ipcMain.handle` 请求 / 响应），分三类：

- **`ELECTRON_IPC_CHANNELS`**：`app` / `runtime`（server URL、token）/ `public-access` / `clipboard` / `shell` / `pets` / `dialog` / `update` / `notification` / `window` / `terminal`（node-pty）/ `preview` / `workspace-browser` / `adapters` / `zoom` / `appearance` 等。
- **`ELECTRON_EVENT_CHANNELS`**（`webContents.send` 推送）：`previewEvent` / `workspaceBrowserEvent` / `terminalOutput|Exit` / `migrationProgress` / `pet*` 等。
- **`ELECTRON_INTERNAL_CHANNELS`**：`preview:message-from-view`（preload → main 的原始中继）。

每个通道都有 payload 校验器（`capabilities.ts:327-420` 的 `ELECTRON_IPC_VALIDATORS`，外加桌面宠物窗口白名单 `capabilities.ts:426-439`），全部经 `registerHandler` 注册（`main.ts:472-502`）。

## Local HTTP Server

本地 HTTP 服务由 Electron 主进程的 `ElectronServerRuntime`（`desktop/electron/services/serverRuntime.ts`）管理，它把 **`claude-server` 作为独立 sidecar 进程**拉起（`serverRuntime.ts:382` `spawnSidecar(createServerPlan({...port}))`），而非 in-process。职责与端口：

- **绑定地址**：`http://{SERVER_CONTROL_HOST}:{port}`（`serverRuntime.ts:366`），端口优先用固定配置、再退回上一轮端口，让手机书签 / 二维码 / 反代在重启后仍然有效（`serverRuntime.ts:360-365`，注释 #767）。
- **H5 远程访问**：sidecar 把打包好的 H5 前端 dist（`h5DistDir`，默认 `desktopRoot/dist`）经 HTTP 提供给手机浏览器——即 **H5 远控 / 移动端控制 + public-access API + staticH5**，不是会话协作。访问受本地令牌 `CC_HAHA_LOCAL_ACCESS_TOKEN`（32 字节 base64url，`serverRuntime.ts:131,499-511`）约束。
- **IM adapter sidecar**：同一运行时还会按 `--feishu / --telegram / --wechat / --dingtalk / --whatsapp / --wecom / --qq / --slack` 拉起**八个 IM adapter 独立 sidecar**（`serverRuntime.ts:457-466`），每个连到 server URL。这解释了 `adapters/` 下为何有 8 个平台目录。

> 注：`src/server/server.ts` 在外部构建里是 `@generated stub` 占位，真实实现就是上面的 `serverRuntime.ts`（已核实，非推测）。

- 端口范围与安全源：`fixedPort` 1024–65535（避开浏览器禁用端口）、`allowedOrigins`（`h5AccessService.ts:8-37,83-84`）。传输层是 Bun `serve`。

## Built-in Browser Preview

不是 CEF，而是 **Electron `WebContentsView` + `preview-agent.js` sidecar + `preview-preload.cjs`**（`main.ts:338-361` 的 `getPreviewService`）：预览视图用独立的**沙箱 partition**（`createPreviewSessionPartition()`，`main.ts:349`），cookie / 登录态保存在该 partition 内，所以预览页带着登录态渲染。注意 `main.ts:916,927` 的 `<webview>` 属于另一个 **Workspace Browser** 功能，与预览无关。

## Branch and Worktree Launch

由 `config.spawnMode` 驱动：`single-session`（`session`）/ `same-dir` / `worktree`（`bridgeMain.ts:1720-1727` 的 `parseSpawnValue`）。轮询循环里（`bridgeMain.ts:963-1015`）：当 `spawnMode==='worktree'` 且非预创建的初始会话时，调用 `createAgentWorktree(\`bridge-${id}\`)`（`bridgeMain.ts:983-993`），子进程跑在 `wt.worktreePath`，初始会话仍留在 `config.dir`。分支 / git 仓库细节在 `src/utils/worktree.ts` 的 `createAgentWorktree`（未纳入本快照）。

## Desktop Shell versus Terminal Claude Code

| 维度 | 终端 Claude Code | cc-haha 桌面外壳 |
| :--- | :--- | :--- |
| 界面 | 终端滚动输出 | GUI 工作台：左项目 / 历史、中对话、右改动面板 |
| 多会话 | 多终端 / tmux | 标签页 + 项目切换 + Cmd+K 全局搜索 |
| Diff 审批 | 终端 inline | 文件级 diff，逐文件 undo 整轮 |
| 权限 | 终端 prompt | GUI 5 档权限集中审批 |
| 预览 | 无 | 内置浏览器预览（带 cookie / 登录态） |
| 远程 | 无 | H5 扫码 + IM 接入 |

## Under the Hood

内核 `claude-haha` 复用 Claude Code 的 machinery：三阶段 agentic loop、权限判定、subagent、Skills、MCP、memory（默认 `~/.claude`）。外壳并未替换这套机制，而是在其上叠加 GUI 层与远程 / IM 通道。因此：

- 想理解**循环 / 工具 / 上下文 / harness**，看 [Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 与 [ClaudeCode/Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)。
- 想理解 **引擎 spawn/NDJSON 桥接 / 预览 / 远程**这类外壳增量，才是本家族其余分册的内容。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [sessionRunner.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/bridge/sessionRunner.ts)
- [bridgeMain.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/bridge/bridgeMain.ts)
- [serverRuntime.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/electron/services/serverRuntime.ts)
