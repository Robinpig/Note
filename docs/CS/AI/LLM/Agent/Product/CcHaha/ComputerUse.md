## Introduction

**Computer Use** 让 agent 在授权后**截屏、点击、输入并控制桌面应用**——把操作对象从「文件与 shell」扩展到「屏幕上的任意 GUI 应用」。这是 cc-haha 与纯编程 Agent 的分水岭能力之一。

实现架构分四层（设计文档 `docs/internals/computer-use.md:14-33`）：模型 / MCP → 工具与参数校验（`tools.ts`）→ 会话授权与安全调度（`toolCalls.ts` / `mcpServer.ts`）→ cc-haha 集成（`src/utils/computerUse/`）→ **Python Bridge** → **平台 Helper**。

## Python Bridge（Windows-only）

桌面侧 `computerUse.ts` 是 API 封装；`src/utils/computerUse/pythonBridge.ts` 负责**建 venv、装依赖、以 `command + JSON payload` 调用 helper**，返回统一 `{ok,result,error}` 信封（`pythonBridge.ts:110,175-179`）。**但 Python 路径仅 Windows**：`isWindows` 分支才 bootstrap venv + 写 `win_helper.py` / `win_cursor_badge.py`（`pythonBridge.ts:27,133`）；代码注释明言「macOS routes exclusively to the signed daemon, no Python macOS path」。

- **macOS**：走原生 `cu-helper` Swift 守护进程（见下），**无 Python macOS 路径**。
- **Windows**：Python bridge + `win_helper.py`。
- **Linux**：`executor.ts:334` 只允许 macOS + Windows，**不支持**。

> [!WARNING]
> 早期版本把 `runtime/mac_helper.py` 列为 macOS 实现——**已据源码纠正**：macOS 端是编译后的 Swift 守护进程，不是 Python。

## Native cu-helper (Swift)

`native/cu-helper/Sources/cu-helper/Permissions.swift` 是**纯权限探测**模块，从不移动光标或投递事件（`Permissions.swift:24`）：

- `accessibilityTrusted`（`AXIsProcessTrusted`，`Permissions.swift:42`）。
- `screenRecordingGrantedAuthoritative`（`CGPreflightScreenCaptureAccess`，`Permissions.swift:83`）。

两者均**失败即关闭（fail closed）**。桌面侧 `computerUse.ts:87` 的 `cuHelper.available` 决定渲染「无 Python 的原生 UI」还是 Python 安装引导流。

## Authorization Model

授权是**多层、非单一弹窗**（`computer-use.md:86-137`）：

- 全局开关 `CLAUDE_COMPUTER_USE_ENABLED`（`isDisabled()` 即 kill switch，见下方 Security gates 段）。
- macOS 需 Accessibility + Screen Recording 两项 TCC 授权（`ensureOsPermissions`，fail closed）。
- **全局一次性同意即覆盖所有 app**：启用并确认 consent 后，**没有** app 类别 / bundle id / display name / host 身份能再拒绝访问（`toolCalls.ts:24-28`）。`deniedApps.ts` 里遗留的 `categoryToTier` / `getDeniedCategory` / `isPolicyDenied` / `getDefaultTierForApp` 全部返回 `'full'` 或 `false`——此前笔记写的「`read` / `click` / `full` 三级前台白名单」**已是死代码**，实际所有 app 一律 `full`（`deniedApps.ts:1-44`）。
- **哨兵 app 仅警告、不拦截**：`sentinelApps.ts` 维护 `SENTINEL_BUNDLE_IDS`（shell 类 Terminal/iTerm2/VSCode/Warp/WezTerm/Alacritty/kitty/IntelliJ/PyCharm；filesystem 类 Finder；system_settings 类 System Preferences），审批 UI 对它们显示**警告徽章**，但**不会 block**——power user 仍可让模型控制终端（`sentinelApps.ts:1-43`）。
- 会话互斥锁（`cuLock`，防止两个 Claude 会话同时控屏，见下方 Security gates 段）。
- 独立的 clipboard / system-key grant 标志；像素陈旧检查（`pixelValidation`，默认关）。
- Windows 无 TCC，但**同样走全局一次性同意覆盖所有 app**，无 per-app 白名单。

授权范围与 5 档权限模式叠加——即使开了 Computer Use，危险操作仍走 GUI 审批（见 [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)）。

### End-to-end call path（从模型工具调用到原生事件）

一次 `click(x,y)` 或 `screenshot` 穿越的边界函数（证据 file:line）：

1. **MCP 工具分发**：`toolCalls.ts:handleToolCall`（954）跑 8 道闸门后 `parseRequest`（557）构造 `run(engine, target)` 闭包。
2. **语义引擎**：`executor.ts:createCodexEngine`（151）的 `click`（175）/ `getAppState` 经 `appTargetPayload`（121）调 `engine.click(...)`。
3. **平台桥**：`helperBridge.ts:callHelper`（110）在 `darwin` 上走 `viaDaemon`（156），覆盖命令触发 overlay。
4. **守护进程客户端**：`cuHelperDaemon.ts:callDaemon`（710）→ `dispatchDaemonCommand`（647）把 JSON 帧写入 socket（693）。
5. **原生接收**：`Daemon.swift:handleNewConnection`（344）先认证 peer（349）再 `route`（515）转发。
6. **命令路由**：`CommandRouter.swift:handle`（126）→ `handleClick`（1162）/ `handleScreenshot`（416）→ `AXAction.click` / `Capture.screenshot` → `CGEventPostToPid` / ScreenCaptureKit 真正投递。

### Handshake & peer attestation（macOS）

- **启动**：`open -n <app> --args daemon --socket <sock>`（`cuHelperDaemon.ts:490-496`）。`-n` 强制新实例，`open` 交给 LaunchServices 后**立即退出**，daemon 被 reparent 到 launchd——**不是 XPC、也不是 launchd plist daemon**。`ensureInstalledHelper()` 先把 helper 从 `app.asar.unpacked` 搬到**独立稳定路径**，否则 macOS Screen Recording 的 TCC 会错误归因到宿主 app、授权无效（`cuHelperDaemon.ts:466-473`）。
- **Socket**：AF_UNIX `SOCK_STREAM`，路径 `~/.claude/.runtime/cu-helper.daemon.<pid>.<gen>.sock`，`chmod 0o600`（`cuHelperDaemon.ts:127, Daemon.swift:232,275`）。
- **双向 attestation**：Node→daemon 端 `attestDaemonSocketPeer`（`cuHelperDaemon.ts:525`）把二进制路径写进 fd3，daemon 跑 `attest_daemon_peer` CLI 比对 pid / `teamIdentifier` / 叶子证书（`ClientAttestation.swift:62`）；daemon→Node 端 `authorizeDaemonConnection`（`ClientAttestation.swift:435`）读内核 peer 身份、`SecCodeCheckValidity` 严格校验、沿父进程链追溯到签名桌面宿主 `com.claude-code-haha.desktop`（链深 ≤12）。**防止伪造的 helper 接管输入事件**。
- **线协议**：版本化 NDJSON，协议号 `CCHahaComputerUseIPC-2`（`DaemonProtocol.swift:10`），单帧上限 8MB；每条请求带绝对 `deadline` + `sessionId`/`turnId`，过期请求在服务端直接拒绝（`DaemonProtocol.swift:25-52`）。
- **Turn gate**：单次认证连接上**强制同一时刻只有一个 turn**——`ping`/`check_permissions`/`list_installed_apps`/`shutdown` 为 connection-scoped 不占 turn，其余语义请求必须保持同一 `sessionId+turnId` 直到 `turn_end` 释放（`DaemonProtocol.swift:12-99`）。

### Security gates（8 道闸门）

`toolCalls.ts:handleToolCall` 在真正执行前串行校验（`toolCalls.ts:954` 链：`964` kill switch → `985` 纯静态 parse → `1007` TCC `ensureOsPermissions` → `1020` 全局 CU lock → `1039` engine 存在 → `1055` `resolveTarget` → `1059` 变异操作的进程生命周期）。注意 `src/utils/computerUse/gates.ts` 是**特性开关配置层**（growthbook `tengu_malort_pedway`，控制 `pixelValidation`/`clipboardGuard`/`coordinateMode` 等子闸门），并非上面这条安全链本身。权限模型仍是 fail-closed：`granted = accessibility && screenRecording`，缺 Screen Recording 即失败（`permissions.ts:normalizeOsPermissions`）。

### 子闸门实现

主链之外，`subGates.ts` 定义 6 个可独立开关的子闸门（`CuSubGates`），取值由 feature-flag 层（`gates.ts`）下发。注意 **`pixelValidation` 默认就是关的**——即使 `ALL_SUB_GATES_ON` 里它也是 `false`（`subGates.ts`）；另外五项（`clipboardPasteMultiline` / `mouseAnimation` / `hideBeforeAction` / `autoTargetDisplay` / `clipboardGuard`）默认开。

**按键黑名单（keyBlocklist.ts）**——`systemKeyCombos` grant 未开时会被拦下的具体组合：
- macOS：`meta+q`（Quit）、`shift+meta+q`（Logout）、`alt+meta+escape`（Force Quit）、`meta+tab`（App Switcher）、`meta+space`（Spotlight）、`ctrl+meta+q`（Lock Screen）。
- Windows：`ctrl+alt+delete`（Secure Attention Sequence）、`alt+f4`、`alt+tab`、`meta+l`、`meta+d`。
- 匹配算法比直觉严格：所有修饰符别名（`meta` / `super` / `command` / `cmd` / `windows` / `win` → `meta`，`alt` / `option` / `opt` → `alt` 等）先归一化；匹配按**子集**而非相等——`shift+cmd+tab` 仍会切 app，故必须被 `meta+tab` 抓到，精确匹配会漏；且对**每个非修饰键逐个检查**——`cmd+q+a` 在按下 Q 的瞬间已触发 Cmd+Q（`isSystemKeyCombo`，`keyBlocklist.ts`）。

**像素陈旧检查（pixelCompare.ts，对应 `pixelValidation`）**：点击前把「模型最后看到的截图」与「此刻新鲜截图」在目标点做 **9×9 patch 精确字节比较**，不一致则中止点击并要求模型重新截图。它**不是弹窗检测器**，且**刻意 fail-open**——冷启动无 `lastScreenshot`、截图失败、crop 解码失败或任何内部异常都判 `skipped` 放行点击，「验证失败绝不能阻塞动作」（`validateClickTarget`）；crop 用宿主注入的 Electron `nativeImage`（免 sharp 这个 LGPL native addon），Retina 缩放用百分比坐标规避。

### Capabilities

输入动作（实现于 `toolCalls.ts` / `CommandRouter.swift`）：

- **观察**：`screenshot`、`zoom`、`get_app_state`。
- **指针**：`move_mouse`、`click`（坐标或 `gN:id` 句柄、`button`/`click_count` 1–3）、`drag`、`scroll`（≤10 页）、`mouse_down/up`（daemon-only）。
- **键盘**：`type`/`type_text`、`paste`、`key`、`hold_key`、`press_key`（xdotool 风格）。
- **受控动作**：`systemKeyCombos` 需独立 session `grantFlags`（`toolCalls.ts:810`）；screen-lock 闸门、foreground-lease 隔离、offscreen 窗口策略（`TargetVisibilityPolicy`）避免操作到看不见的窗口。

## Tool Surface

vendor 层 `tools.ts` 暴露 14 个工具，每个带 MCP `annotations`（`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`）供 host 做策略归类。按能力分四类：

**观察（readOnlyHint: true）**
- `list_apps`：列运行/最近应用（格式 `"<App Name> — <bundle.id>"`），**发现不授权**。
- `get_app_state`：读 AX 树（每个交互元素带 `element_index` 不透明句柄）+ 关键窗口截图；先调它、动作后再调。支持 `disableDiff`（返回完整树而非 diff）。

**指针 / 语义动作（readOnlyHint: false）**
- `click`：`element_index`（AX 直接定位，无需像素找）或显式 `(x,y)`；`click_count` 1–3、`mouse_button`。
- `perform_secondary_action`：对元素执行 `get_app_state` 中列出的二级动作（Expand / Collapse / Raise / Scroll Up…）。
- `set_value`：按 `element_index` 直接替换可设元素内容（文本框 / 滑块）。
- `select_text`：在文本元素内选段或置光标（`selection: text|cursor_before|cursor_after`）。
- `scroll`：按 `element_index` 或点 + 基方向（`up/down/left/right`），`pages` 可小数。
- `drag`：从 `(x,y)` 到 `(x,y)`，`button`。

**键盘**
- `press_key`：按键序列（xdotool 风格），单调用 ≤128 和弦；**系统键组合需 session 级 `systemKeyCombos` grant**（见 [Implementation Details](#implementation-details)）。
- `type_text`：键入文本（空串为合法 no-op）。
- `paste`：`text|md|html` 三种格式粘贴。

**受控 / 批量**
- `sequence`（macOS only）：对**一个** app 跑 1–256 步已知 UI 动作的有界批量 API，最后返回真实 AX 状态 + 截图。每步只能是 `MUTATING_TOOLS` 之一、不能 per-step 改 `app`、键盘和弦预算 ≤2048（`toolCalls.ts:574-620`）。
- `js` / `js_reset`（持久 JS REPL）：`js` 在隔离的 Computer Use JS session 跑原生 app 自动化（`app.click/drag/pressKey`…），**标 `destructiveHint: true`**；`js_reset` 清空 session（`tools.ts:101-120`）。走 `replRuntime`/`replWorker`，不在下述 `MUTATING_TOOLS` 集合内。

**变异 vs 只读的精确边界**：源码用 `MUTATING_TOOLS` 集合判定（`toolCalls.ts:538-548`）——`click, perform_secondary_action, set_value, select_text, scroll, drag, press_key, type_text, paste` 共 9 个为变异；`list_apps` / `get_app_state` 只读；`sequence` 单独标 `mutating`（1–256 步）。

## Implementation Details

**坐标系（窗口锁定）**：截图**锁定目标窗口**，所有坐标都是「最新 `get_app_state` 截图的像素空间」，**不是全局屏幕空间**（`tools.ts:29-30,69-79`）。Chromium / Electron 类 app 只暴露窗口框架与菜单栏，`get_app_state` 会明说——此时 `element_index` 够不到内容，必须用截图里的 `(x,y)`（`tools.ts:174-179`）。

**Target 解析与 pid 回收防护**：`appTargetPayload` 优先级 `pid → bundleId → app → frontmost`（空 target = 前台，`executor.ts:121-133`）。每个 target 带 `expectedProcessIdentity`，daemon 行动前重验——pid 在「解析」与「行动」之间被回收复用会被**拒绝**而非误控（`executor.ts:122-124`、`toolCalls.ts:17-22`）。

**systemKeyCombos 授权位来自 SESSION 而非模型参数**：`press_key` 若命中跨应用边界或能终止 app 的键组合（`isSystemKeyCombo`），**必须** `grantFlags?.systemKeyCombos === true`——该 bit 由 session 设置，**模型无法靠传参自授权** cmd+q 之类（`toolCalls.ts:807-815`）。

**Standalone 变异不隐式快照**：每个变异工具返回固定 `MUTATION_RECEIPT`，模型想看结果自己再调 `get_app_state`；避免每次动作后双重 AX 遍历 + 窗口捕获（`toolCalls.ts:30-34`）。

**macOS vs Windows 引擎差异**：
- macOS：`createCodexEngine()` 走原生 cu-helper 守护进程，AX 树 + 按 `element_index` 点击，`engine` 存在（`executor.ts:151,350`）。
- Windows：`engine` 为 `undefined`——Python helper 没有 `get_app_state` / click-by-index 表面，十类 Codex 工具干净返回 `feature_unavailable`（gate 5，注释 `executor.ts:346-349`）；但 CLI 像素层（click / moveMouse / drag 经 pyautogui）仍可用。
- Linux：不支持（`createCliExecutor` 直接抛错，`executor.ts:334-338`）。

**type-via-clipboard（macOS）**：`type(text, {viaClipboard})` 走剪贴板暂存——先存旧剪贴板 → 写新文本 → `paste_clipboard` → 延时后恢复旧内容；Windows 走 `key: ctrl+v`（`executor.ts:300-328`）。

## Deterministic REPL VM

Computer Use 不只有上一段「控制层」（截图 / 点击 / 键入，由 cu-helper daemon + mcp 工具实现）；它还暴露一个**独立的 JS 内核**，让用户或模型在隔离环境里写脚本操作 UI。这套执行环境由三层组成，与 Workflow 的确定性 VM（`runtime.ts` / `compile.ts`，见 [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md) 引擎段）是**两套互不相干**的机制。

### 三层架构（compiler → worker → runtime）
- **编译层 `replCompiler.ts`**：`compileReplCell(code, prior)` 用 `acorn` 解析并做 AST 变换，把所有**自由标识符**（未在局部 / 上层词法作用域声明的变量名）重写为注入的持久作用域 `scope.values["Date"]` 形式——`Date` / `Math` / `fetch` 等全部经此重定向，确定性由宿主 realm 提供的 `scope` 保证；禁止 `import` / `export`（硬错误 "Module imports and exports are not available in Computer Use JavaScript"）；`randomUUID()` 生成唯一前缀 `__cu_cell_<uuid>_` 防命名冲突；`typeof` 改 `scope.typeOf("x")` 避免原生 `ReferenceError`；`const` 重赋值只给 warning 不抛错。
- **内核层 `replWorker.ts`**：`vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } })` 创建**禁动态代码生成**（eval / Wasm）的空白上下文；`new Script(...).runInContext(context)` 运行 IIFE 重写 `setTimeout` / `setInterval` / `clearTimeout` / `clearInterval` / `__cuInvoke` / `__cuEmit` 并用 `Proxy` 代理全局。内核本身作为**一次性子进程**由父进程经 stdio JSON-RPC 驱动（`runComputerUseReplWorker`）。
- **运行层 `replRuntime.ts`**：`ComputerUseRepl` 类，用 `Bun.build()` 把 `replWorker.ts` 打成自包含独立 ESM，再 `spawn('/bin/sh', ['-c', 'exec <command>'], { detached: true, stdio: 'pipe' })` 启动 kernel——**不是 `worker_threads`，是 OS 进程隔离**（`replRuntime.ts:ComputerUseRepl`）。

### 隔离与沙箱（replRuntime.ts）
- **macOS Sandbox**：`wrapCommandWithSandboxMacOS` 只读 `/System` / `usr/lib` / `usr/share` / `bin/bash` / `usr/bin/env` / `dev` 等 + `readable` 列表，可写仅 `options.directory` 与 `/dev/null`，**网络禁用**（`needsNetworkRestriction: true`）。
- **env 隔离**：`HOME` / `TMPDIR` / `TMP` / `TEMP` → 沙箱目录，`PATH = '/usr/bin:/bin'`，`BUN_OPTIONS = '--no-env-file'`，`CLAUDE_CONFIG_DIR` → `directory/.claude`。
- **资源限制**：`maxRssBytes = 768 MB`，`REPL_MAX_ACTIONS` / `REPL_MAX_CODE_BYTES` / `REPL_MAX_OUTPUT_BYTES` 限制行为边界；用户代码超时 `timeoutMs ∈ [1, 60000]`，超时杀 kernel，心跳 2s 无 `pong` 判死并清进程组。

### 确定性（replWorker.ts）
- **跨 cell 状态持久化**：执行结束 `bindings = JSON.parse(realm.commit(submittedSucceeded))`，序列化回 `ReplBinding[]` 供下次 `compileReplCell` 复用，实现连续 REPL 状态。
- **纯 JSON 桥接**：只有 JSON 字符串跨 host bridge——无 host Promise / Error / timer handle 进 realm（内核注释）。
- **cell 生命周期纪律**：`AsyncLocalStorage<CellState>` 追踪活跃 cell；cell 首个 Promise settle 后 `accepting = false`，**强制所有 Computer Use 操作必须被 `await`**；`unobservedError()` 检测未 await 的失败操作。
- **定时器**：`MAX_ACTIVE_TIMERS = 1024`，延迟规范到 `0 .. 2,147,483,647`ms，cell 结束 `finally` 清全部 timers。

### 与 Workflow VM 的区别（避免混淆）
- **Workflow VM**：脚本编译为 `vm.Script`，`Date` / `Math.random` / `import` 被**显式抛错**禁用，目的是编排 subagent 的可重放确定性。
- **Computer Use VM**：acorn AST 改写 + vm 沙箱 + macOS sandbox 进程隔离，自由标识符重定向到 realm；禁的是 `import` / `export` 与动态代码生成（eval / Wasm），`Date` / `Math` 等是否确定取决于 realm 提供的取值——为**脚本化 UI 操作**而生。

## Use Cases

适合「改完网页还要在浏览器里点一遍」「操作没有 CLI 的桌面软件」这类纯代码 Agent 覆盖不到的场景。生产环境慎用：未签名 + 版权风险（见 [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md) 的 WARNING）。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [computer-use.md 设计文档](https://github.com/NanmiCoder/cc-haha/blob/main/docs/internals/computer-use.md)
- [Permissions.swift](https://github.com/NanmiCoder/cc-haha/blob/main/native/cu-helper/Sources/cu-helper/Permissions.swift)
- [cuHelperDaemon.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/cuHelperDaemon.ts)
- [helperBridge.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/helperBridge.ts)
- [toolCalls.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/toolCalls.ts)
- [pythonBridge.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/pythonBridge.ts)
- [DaemonProtocol.swift](https://github.com/NanmiCoder/cc-haha/blob/main/native/cu-helper/Sources/cu-helper/DaemonProtocol.swift)
- [ClientAttestation.swift](https://github.com/NanmiCoder/cc-haha/blob/main/native/cu-helper/Sources/cu-helper/ClientAttestation.swift)
- [tools.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/tools.ts)
- [executor.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/executor.ts)
- [deniedApps.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/deniedApps.ts)
- [sentinelApps.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/sentinelApps.ts)
- [replCompiler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/replCompiler.ts)
- [replRuntime.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/replRuntime.ts)
- [replWorker.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/replWorker.ts)
- [replProtocol.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/replProtocol.ts)
- [subGates.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/subGates.ts)
- [keyBlocklist.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/keyBlocklist.ts)
- [pixelCompare.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/vendor/computer-use-mcp/pixelCompare.ts)
