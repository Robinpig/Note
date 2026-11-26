## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

**Computer Use** 让 agent 在授权后**截屏、点击、输入并控制桌面应用**——把操作对象从「文件与 shell」扩展到「屏幕上的任意 GUI 应用」。这是 cc-haha 与纯编程 Agent 的分水岭能力之一。

实现分几层：模型 / MCP 工具与参数校验（`tools.ts`、`toolCalls.ts`）→ 会话授权与安全调度（`mcpServer.ts`、`gates.ts`）→ 平台运行组件。v0.7.7 对最后一层做了重构：macOS 走签名的 Swift 守护进程 cu-helper；**Windows 与 Linux 改用随安装包提供的原生 `agent-desktop` 运行组件**，不再需要安装 Python 或创建虚拟环境，Linux 也正式受支持。设计文档见 `docs/internals/computer-use.md`。

## Platform Runtime: Native agent-desktop on Windows / Linux

v0.7.7 把 Windows / Linux 的 Computer Use 后端换成随安装包分发的原生二进制。`src/utils/computerUse/agentDesktopBinary.ts` 按平台拼出可执行文件名与随包路径：

```ts
export function resolveAgentDesktopBinary(options: AgentDesktopBinaryOptions = {}): string | null {
  const platform = options.platform ?? process.platform
  const arch = options.arch ?? process.arch
  const file = platform === 'win32' ? 'agent-desktop.exe' : 'agent-desktop'
  const appRoot = options.appRoot ?? process.env.CLAUDE_APP_ROOT
  const resources = options.resourcesPath ?? (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath
  const exists = options.exists ?? ((candidate: string) => {
    try {
      const info = statSync(candidate)
      if (!info.isFile()) return false
      accessSync(candidate, platform === 'win32' ? constants.F_OK : constants.X_OK)
      return true
    } catch {
      return false
    }
  })
  if (options.binaryPath) return exists(options.binaryPath) ? path.resolve(options.binaryPath) : null
```

平台路由在 `src/vendor/computer-use-mcp/mcpServer.ts` 决定：`linux` 或 `agentDesktop` capability 为真时直接走原生工具集，只有「win32 且非原生」才回退到 legacy 分发器（`windowsLegacyToolCalls.ts` / `windowsLegacyTools.ts`）。

```ts
export function buildPlatformComputerUseTools(
  caps: {
    screenshotFiltering: "native" | "none";
    platform: "darwin" | "win32" | "linux";
    agentDesktop?: boolean;
    teachMode?: boolean;
  },
  coordinateMode: CoordinateMode,
  installedAppNames?: string[],
): Tool[] {
  if (caps.agentDesktop || caps.platform === 'linux') return buildAgentDesktopTools()
  return caps.platform === "win32"
    ? buildLegacyComputerUseTools(caps, coordinateMode, installedAppNames)
    : buildComputerUseTools(caps, coordinateMode, installedAppNames)
      .filter(tool => tool.name === 'js' || tool.name === 'js_reset');
}
```

`src/utils/computerUse/gates.ts` 的注释与暴露判断把三平台并列，明确 Linux 与 Windows 都依赖原生组件可启动：

```ts
/**
 * Computer Use uses the macOS helper or the Windows/Linux native CLI.
 * The macOS MCP must not be exposed until the exact helper that status/API
 * calls use is launchable; otherwise the model sees tools that can only fail.
 */
export function shouldExposeComputerUseMcp(
  platform: NodeJS.Platform,
  macosNativeLaunchable: boolean,
  agentDesktopLaunchable = false,
): boolean {
  return ((platform === 'win32' || platform === 'linux') && agentDesktopLaunchable)
    || (platform === 'darwin' && macosNativeLaunchable)
}
```

**代码存在 ≠ 公开版实际生效**：仓库里 `src/utils/computerUse/pythonBridge.ts`、`setup.ts`、`pipInstall.ts` 与 `windowsLegacyToolCalls.ts` / `windowsLegacyTools.ts` 仍在，注释也仍写着「This bridge is Windows-only」：

```ts
// This bridge is Windows-only. macOS routes every command to the signed native
// `cu-helper` daemon and `helperBridge` refuses to fall back, so the old
// `mac_helper.py` was unreachable and has been deleted along with its
// pyobjc requirements file. Keeping a dead darwin branch here invited the
// reading that Python is still a supported macOS path — it is not.
```

但这套 Python / venv 引导只在上面的 legacy 回退分支才会被用到；公开版 Windows / Linux 主路径是原生 `agent-desktop`，用户无需安装 Python、无需创建虚拟环境。`src/utils/computerUse/executor.ts` 的 legacy CLI executor 也把 Linux 列入支持平台，不再是「只允许 macOS + Windows」：

```ts
export function createCliExecutor(opts: {
  getMouseAnimationEnabled: () => boolean
  getHideBeforeActionEnabled: () => boolean
}): ComputerExecutor {
  if (!isComputerUseSupportedPlatform()) {
    throw new Error(
      `createCliExecutor called on ${process.platform}. Computer control is only supported on macOS, Windows and Linux.`,
    )
  }
```

## Native cu-helper (Swift, macOS)

macOS 仍走原生 cu-helper Swift 守护进程。`native/cu-helper/Sources/cu-helper/Permissions.swift` 是**纯权限探测**模块，从不移动光标或投递事件，且两项 TCC 授权都**失败即关闭（fail closed）**：

```swift
/// Reality check, baked into the implementation:
///   - Accessibility is queried via the canonical `AXIsProcessTrusted()` /
///     `AXIsProcessTrustedWithOptions(...)`. We FAIL CLOSED — any inability to read
///     the trust state is reported as not-trusted, never a misleading `true`, so the
///     desktop UI doesn't claim control works when it doesn't.
///   - Screen Recording is queried only via `CGPreflightScreenCaptureAccess()`.
///     Window-title visibility is not accepted as a substitute: a responsible
///     parent can expose titles even when this helper's own TCC identity cannot
///     capture. Permission reporting must match the capture hot path exactly.
///
/// NOTHING in this file ever moves the real cursor or posts an input event; it is pure
/// permission introspection. The only function that can surface OS UI is
/// `requestScreenRecording()`, which is reserved for explicit onboarding and is never
/// invoked on a hot path.
```

- `accessibilityTrusted` 用 `AXIsProcessTrusted()`；`screenRecordingGrantedAuthoritative` 用 `CGPreflightScreenCaptureAccess()`；`granted = accessibility && screenRecording`，缺 Screen Recording 即失败。
- **macOS 前台行为已变**：v0.7.7 读取 / 操作目标应用不再把它拉到前台，对话回到 cc-haha 全屏后目标也不会被反复激活。`TargetVisibilityPolicy.swift` 明确遮挡不是 raise / activate 的理由：

```swift
/// Explains a repeated window capture without turning ordinary occlusion into
/// an input failure.
///
/// The daemon keeps a desktop-independent SCStream subscribed to the target
/// window throughout a Computer Use turn. That gives Chromium/CEF a continuous
/// WindowServer consumer while another app fully covers it, while all input is
/// still addressed to the target process/window. Occlusion is therefore never
/// a reason to raise, activate, or reject a mutation.
enum TargetVisibilityPolicy {
    static func captureTargetStillMatches(
        snapshotWindowID: CGWindowID?,
        currentWindowID: CGWindowID?
    ) -> Bool {
        snapshotWindowID == currentWindowID
    }
```

> [!WARNING]
> 早期版本把 `runtime/mac_helper.py` 列为 macOS 实现——已据源码纠正：macOS 端是编译后的 Swift 守护进程，不是 Python。

## Authorization Model

授权是**多层、非单一弹窗**：

- 全局开关 `CLAUDE_COMPUTER_USE_ENABLED`（`isDisabled()` 即 kill switch，见 Security gates 段）。
- macOS 需 Accessibility + Screen Recording 两项 TCC 授权（`ensureOsPermissions`，fail closed）。
- **全局一次性同意即覆盖所有 app**：启用并确认 consent 后，没有 app 类别 / bundle id / display name / host 身份能再拒绝访问。`src/vendor/computer-use-mcp/deniedApps.ts` 里遗留的 tier 查询全部返回 `'full'` 或 `null` / `false`——旧笔记写的「`read` / `click` / `full` 三级前台白名单」已是死代码：

```ts
/**
 * Computer Use is authorized once through the global enable dialog. All
 * apps have full access regardless of category, bundle ID, display name, or host/helper identity.
 *
 * Keep the legacy lookup exports for the Windows dispatcher and stored-grant
 * compatibility code. They no longer impose per-app policy or access tiers.
 * This module stays import-free because the desktop also consumes it.
 */
export type DeniedCategory = 'browser' | 'terminal' | 'trading'

export function categoryToTier(
  _category: DeniedCategory | null,
): 'read' | 'click' | 'full' {
  return 'full'
}
```

- **哨兵 app 仅警告、不拦截**：`src/vendor/computer-use-mcp/sentinelApps.ts` 维护 `SENTINEL_BUNDLE_IDS`（shell 类 Terminal/iTerm2/VSCode/Warp/WezTerm/Alacritty/kitty/IntelliJ/PyCharm；filesystem 类 Finder；system_settings 类 System Preferences），审批 UI 对它们显示**警告徽章**，但不会 block：

```ts
/**
 * Bundle IDs that are escalations-in-disguise. The approval UI shows a warning
 * badge for these; they are NOT blocked. Power users may legitimately want the
 * model controlling a terminal.
 *
 * Imported by the renderer via the `./sentinelApps` subpath (package.json
 * `exports`), which keeps Next.js from reaching index.ts → mcpServer.ts →
 * @modelcontextprotocol/sdk (devDep, would fail module resolution). Keep
 * this file import-free so the subpath stays clean.
 */
```

- 会话互斥锁 `cuLock`（防两个会话同时控屏）；独立 clipboard / system-key grant 标志；像素陈旧检查（`pixelValidation`，默认关）。
- Windows 无 TCC，但同样走全局一次性同意覆盖所有 app，无 per-app 白名单。

授权范围与 5 档权限模式叠加——即使开了 Computer Use，危险操作仍走 GUI 审批（见 [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)）。

### End-to-end call path（从模型工具调用到原生事件）

一次 `click(x,y)` 或 `screenshot` 穿越的边界函数（函数名而非行号）：

1. **MCP 工具分发**：`toolCalls.ts` 的 `handleToolCall` 跑 8 道闸门后由 `parseRequest` 构造 `run(engine, target)` 闭包。
2. **语义引擎**：`executor.ts` 的 `createCodexEngine` 的 `click` / `getAppState` 经 `appTargetPayload` 调 `engine.click(...)`。
3. **平台桥**：`helperBridge.ts` 的 `callHelper` 在 darwin 上走 `viaDaemon`，覆盖命令触发 overlay。
4. **守护进程客户端**：`cuHelperDaemon.ts` 的 `callDaemon` → `dispatchDaemonCommand` 把 JSON 帧写入 socket。
5. **原生接收**：`Daemon.swift` 的 `handleNewConnection` 先认证 peer 再 `route` 转发。
6. **命令路由**：`CommandRouter.swift` 的 `handle` → `handleClick` / `handleScreenshot` → `AXAction.click` / `Capture.screenshot` → `CGEventPostToPid` / ScreenCaptureKit 真正投递。

Windows / Linux 的新路径则由 `src/vendor/computer-use-mcp/agentDesktopDispatch.ts` 把 `desktop` 工具直接交给原生组件：

```ts
export function bindAgentDesktopSession(adapter: ComputerUseHostAdapter, ctx: ComputerUseSessionContext) {
  let tail: Promise<unknown> = Promise.resolve()
  return (name: string, args: unknown, signal?: AbortSignal): Promise<CuCallToolResult> => {
    const pending = tail.then(async () => {
      if (adapter.isDisabled() || ctx.isAborted?.() || signal?.aborted) return error('Computer Use is disabled or cancelled. No command was dispatched.')
      if (name !== 'desktop' || !adapter.agentDesktop) return error('Unknown native desktop tool.')
      let input
      try { input = parseAgentDesktopInput(args) } catch (cause) {
        return error(cause instanceof Error ? cause.message : 'Invalid desktop arguments')
      }
```

### Handshake & peer attestation（macOS）

- **启动**：`open -n <app> --args daemon --socket <sock>`。`-n` 强制新实例，`open` 交给 LaunchServices 后立即退出，daemon 被 reparent 到 launchd——不是 XPC、也不是 launchd plist daemon。`ensureInstalledHelper()` 先把 helper 从 `app.asar.unpacked` 搬到独立稳定路径，否则 Screen Recording 的 TCC 会错误归因到宿主 app、授权无效。
- **Socket**：AF_UNIX `SOCK_STREAM`，路径 `~/.claude/.runtime/cu-helper.daemon.<pid>.<gen>.sock`，`chmod 0o600`。
- **双向 attestation**：Node→daemon 端 `attestDaemonSocketPeer` 把二进制路径写进 fd3，daemon 跑 `attest_daemon_peer` CLI 比对 pid / `teamIdentifier` / 叶子证书；daemon→Node 端 `authorizeDaemonConnection` 读内核 peer 身份、`SecCodeCheckValidity` 严格校验、沿父进程链追溯到签名桌面宿主 `com.claude-code-haha.desktop`（链深 ≤12）。防止伪造的 helper 接管输入事件。
- **线协议**：版本化 NDJSON，协议号 `CCHahaComputerUseIPC-2`，单帧上限 8MB；每条请求带绝对 `deadline` + `sessionId` / `turnId`，过期请求服务端直接拒绝。`native/cu-helper/Sources/cu-helper/DaemonProtocol.swift`：

```swift
/// Versioned request contract for the authenticated daemon socket.
///
/// Code signature attestation proves who is connected; this handshake proves
/// that both sides agree on request shape and lifecycle semantics. Every request
/// also carries an absolute deadline plus session/turn identity so a command
/// queued behind a slow capture cannot execute after its caller has moved on.
enum ComputerUseDaemonProtocol {
    static let version = "CCHahaComputerUseIPC-2"
    static let maxFrameBytes = 8 * 1024 * 1024
    private static let connectionScopedCommands: Set<String> = [
        "ping", "check_permissions", "list_installed_apps", "shutdown",
    ]

    static func isTurnScoped(command: String) -> Bool {
        !connectionScopedCommands.contains(command)
    }
```

- **Turn gate**：单次认证连接上强制同一时刻只有一个 turn——`ping` / `check_permissions` / `list_installed_apps` / `shutdown` 为 connection-scoped 不占 turn，其余语义请求必须保持同一 `sessionId+turnId` 直到 `turn_end` 释放。

### Security gates（8 道闸门）

`src/vendor/computer-use-mcp/toolCalls.ts` 的 `handleToolCall` 在真正执行前串行校验 8 道闸门：

```ts
 * ## Enforcement order (every call)
 *
 *   1. Kill switch (`adapter.isDisabled()`).
 *   2. Static request parsing — argument shapes, bounds, alias conflicts, and
 *      the `systemKeyCombos` grant. Pure: no TCC probe, no lock, no daemon
 *      round-trip. A malformed request must not cost a permission prompt.
 *   3. TCC gate (`adapter.ensureOsPermissions()`).
 *   4. Global CU lock (`overrides.checkCuLock`).
 *   5. Engine presence.
 *   6. `resolveTarget` → one running process + its lifetime identity.
 *   7. Proven process lifetime — mutating tools only.
 *   8. Engine dispatch.
```

`src/utils/computerUse/gates.ts` 是**特性开关配置层**（growthbook `tengu_malort_pedway`，控制 `pixelValidation` / `clipboardGuard` / `coordinateMode` 等子闸门），并非上面这条安全链本身：

```ts
function readConfig(): ChicagoConfig {
  return {
    ...DEFAULTS,
    ...getDynamicConfig_CACHED_MAY_BE_STALE<Partial<ChicagoConfig>>(
      'tengu_malort_pedway',
      DEFAULTS,
    ),
  }
}
```

权限模型仍是 fail-closed：`granted = accessibility && screenRecording`，缺 Screen Recording 即失败（`src/utils/computerUse/permissions.ts` 的 `normalizeOsPermissions`）。

### 子闸门实现

主链之外，`src/vendor/computer-use-mcp/subGates.ts` 定义 6 个可独立开关的子闸门（`CuSubGates`），取值由 feature-flag 层下发。注意 **`pixelValidation` 默认就是关的**——即使 `ALL_SUB_GATES_ON` 里它也是 `false`；另外五项（`clipboardPasteMultiline` / `mouseAnimation` / `hideBeforeAction` / `autoTargetDisplay` / `clipboardGuard`）默认开：

```ts
export const ALL_SUB_GATES_ON: CuSubGates = {
  pixelValidation: false,
  clipboardPasteMultiline: true,
  mouseAnimation: true,
  hideBeforeAction: true,
  autoTargetDisplay: true,
  clipboardGuard: true,
}
```

**按键黑名单（`src/vendor/computer-use-mcp/keyBlocklist.ts`）**——`systemKeyCombos` grant 未开时会被拦下的具体组合：macOS `meta+q`（Quit）、`shift+meta+q`（Logout）、`alt+meta+escape`（Force Quit）、`meta+tab`（App Switcher）、`meta+space`（Spotlight）、`ctrl+meta+q`（Lock Screen）；Windows `ctrl+alt+delete`（Secure Attention Sequence）、`alt+f4`、`alt+tab`、`meta+l`、`meta+d`。匹配算法比直觉严格：所有修饰符别名（`meta` / `super` / `command` / `cmd` / `windows` / `win` → `meta`，`alt` / `option` / `opt` → `alt` 等）先归一化；匹配按**子集**而非相等——`shift+cmd+tab` 仍会切 app，故必须被 `meta+tab` 抓到，精确匹配会漏；且对**每个非修饰键逐个检查**——`cmd+q+a` 在按下 Q 的瞬间已触发 Cmd+Q（`isSystemKeyCombo`）。文件头注释：

```ts
/**
 * Key combos that cross app boundaries or terminate processes. Gated behind
 * the `systemKeyCombos` grant flag. When that flag is off, the `key` tool
 * rejects these and returns a tool error telling the model to request the
 * flag; all other combos work normally.
 *
 * Matching is canonicalized: every modifier alias the Rust executor accepts
 * collapses to one canonical name. Without this, `command+q` / `meta+q` /
 * `cmd+alt+escape` bypass the gate — see keyBlocklist.test.ts for the three
 * bypass forms and the Rust parity check that catches future alias drift.
 */
```

**像素陈旧检查（`src/vendor/computer-use-mcp/pixelCompare.ts`，对应 `pixelValidation`）**：点击前把「模型最后看到的截图」与「此刻新鲜截图」在目标点做 **9×9 patch 精确字节比较**，不一致则中止点击并要求模型重新截图（`validateClickTarget`）。它**不是弹窗检测器**，且**刻意 fail-open**——冷启动无 `lastScreenshot`、截图失败、crop 解码失败或任何内部异常都判 `skipped` 放行点击，「验证失败绝不能阻塞动作」；crop 用宿主注入的 Electron `nativeImage`（免 sharp 这个 LGPL native addon），Retina 缩放用百分比坐标规避：

```ts
/**
 * Staleness guard ported from the Vercept acquisition.
 *
 * Compares the model's last-seen screenshot against a fresh-right-now
 * screenshot at the click target, so the model never clicks pixels it hasn't
 * seen. If the 9×9 patch around the target differs, the click is aborted and
 * the model is told to re-screenshot. This is NOT a popup detector.
 *
 * Semantics preserved exactly:
 *   - Skip on no `lastScreenshot` (cold start) — click proceeds.
 *   - Skip on any internal error (crop throws, screenshot fails, etc.) —
 *     click proceeds. Validation failure must never block the action.
 *   - 9×9 exact byte equality on raw pixel bytes. No fuzzing, no tolerance.
 *   - Compare in percentage coords so Retina scale doesn't matter.
 *
 * JPEG decode + crop is INJECTED via `ComputerUseHostAdapter.cropRawPatch`.
 * The original used `sharp` (LGPL, native `.node` addon); we inject Electron's
 * `nativeImage` (Chromium decoders, BSD, nothing to bundle) from the host, so
 * this package never imports it — the crop is a function parameter.
 */
```

### Capabilities

输入动作（实现于 `toolCalls.ts` / `CommandRouter.swift`）：

- **观察**：`screenshot`、`zoom`、`get_app_state`。
- **指针**：`move_mouse`、`click`（坐标或 `gN:id` 句柄、`button` / `click_count` 1–3）、`drag`、`scroll`（≤10 页）、`mouse_down/up`（daemon-only）。
- **键盘**：`type` / `type_text`、`paste`、`key`、`hold_key`、`press_key`（xdotool 风格）。
- **受控动作**：`systemKeyCombos` 需独立 session `grantFlags`；screen-lock 闸门、foreground-lease 隔离、offscreen 窗口策略（`TargetVisibilityPolicy`）避免操作到看不见的窗口。

vendor 层每个工具都带 MCP `annotations`（`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`）供 host 做策略归类：

```ts
    {
      name: 'js_reset',
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      description: 'Reset the persistent Computer Use JavaScript session and discard all App handles and variables. Select an app again before continuing.',
      inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    },
    {
      name: "list_apps",
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      description:
        'List running and recently used applications, with running apps first. ' +
        "Each line is \"<App Name> — <bundle.id>\". Discovery does not grant access. Use this to discover " +
```

## Tool Surface

vendor 层 `tools.ts` 暴露的工具按能力分四类（观察 / 指针·语义动作 / 键盘 / 受控·批量），详见 [Tools](/docs/CS/AI/LLM/Agent/Product/CcHaha/Tools.md)：

**观察（readOnlyHint: true）**
- `list_apps`：列运行 / 最近应用（格式 `"<App Name> — <bundle.id>"`），**发现不授权**。
- `get_app_state`：读 AX 树（每个交互元素带 `element_index` 不透明句柄）+ 关键窗口截图；先调它、动作后再调。支持 `disableDiff`（返回完整树而非 diff）。

**指针 / 语义动作（readOnlyHint: false）**
- `click`：`element_index`（AX 直接定位，无需像素找）或显式 `(x,y)`；`click_count` 1–3、`mouse_button`。
- `perform_secondary_action`：对元素执行 `get_app_state` 中列出的二级动作（Expand / Collapse / Raise / Scroll Up…）。
- `set_value`：按 `element_index` 直接替换可设元素内容（文本框 / 滑块）。
- `select_text`：在文本元素内选段或置光标（`selection: text|cursor_before|cursor_after`）。
- `scroll`：按 `element_index` 或点 + 基方向（`up/down/left/right`），`pages` 可小数。
- `drag`：从 `(x,y)` 到 `(x,y)`，`button`。

**键盘**
- `press_key`：按键序列（xdotool 风格），单调用 ≤128 和弦；**系统键组合需 session 级 `systemKeyCombos` grant**。
- `type_text`：键入文本（空串为合法 no-op）。
- `paste`：`text|md|html` 三种格式粘贴。

**受控 / 批量**
- `sequence`（macOS only）：对**一个** app 跑 1–256 步已知 UI 动作的有界批量 API，最后返回真实 AX 状态 + 截图。每步只能是 `MUTATING_TOOLS` 之一、不能 per-step 改 `app`、键盘和弦预算 ≤2048。
- `js` / `js_reset`（持久 JS REPL）：`js` 在隔离的 Computer Use JS session 跑原生 app 自动化（`app.click/drag/pressKey`…），**标 `destructiveHint: true`**；`js_reset` 清空 session。走 `replRuntime` / `replWorker`，不在下述 `MUTATING_TOOLS` 集合内。

**变异 vs 只读的精确边界**：源码用 `src/vendor/computer-use-mcp/toolCalls.ts` 的 `MUTATING_TOOLS` 集合判定——下列 9 个为变异；`list_apps` / `get_app_state` 只读；`sequence` 单独标 `mutating`（1–256 步）：

```ts
const MUTATING_TOOLS: ReadonlySet<string> = new Set([
  "click",
  "perform_secondary_action",
  "set_value",
  "select_text",
  "scroll",
  "drag",
  "press_key",
  "type_text",
  "paste",
]);

const KNOWN_TOOLS: ReadonlySet<string> = new Set([
  "list_apps",
  "get_app_state",
  ...MUTATING_TOOLS,
  "sequence",
]);
```

## Implementation Details

**坐标系（窗口锁定）**：截图**锁定目标窗口**，所有坐标都是「最新 `get_app_state` 截图的像素空间」，**不是全局屏幕空间**。Chromium / Electron 类 app 只暴露窗口框架与菜单栏，`get_app_state` 会明说——此时 `element_index` 够不到内容，必须用截图里的 `(x,y)`。

**Target 解析与 pid 回收防护**：`appTargetPayload` 优先级 `pid → bundleId → app → frontmost`（空 target = 前台）。每个 target 带 `expectedProcessIdentity`，daemon 行动前重验——pid 在「解析」与「行动」之间被回收复用会被**拒绝**而非误控。

**systemKeyCombos 授权位来自 SESSION 而非模型参数**：`press_key` 若命中跨应用边界或能终止 app 的键组合（`isSystemKeyCombo`），**必须** `grantFlags?.systemKeyCombos === true`——该 bit 由 session 设置，**模型无法靠传参自授权** cmd+q 之类。

**Standalone 变异不隐式快照**：每个变异工具返回固定 `MUTATION_RECEIPT`，模型想看结果自己再调 `get_app_state`；避免每次动作后双重 AX 遍历 + 窗口捕获。

**平台差异（v0.7.7）**：macOS 走 cu-helper daemon，AX 树 + 按 `element_index` 点击，`engine` 存在；Windows / Linux 走原生 `agent-desktop` 工具集。legacy CLI executor（`src/utils/computerUse/executor.ts`）里仍保留「非 darwin 时 `engine` 为 `undefined`、十类 Codex 工具返回 `feature_unavailable`」的分支，但那只对应非原生的旧 Windows 回退路径：

```ts
    // The Codex semantic AX engine is the native macOS path (cu-helper daemon →
    // AXTree/AXAction). On Windows the Python helper has no get_app_state/click-
    // by-index surface, so we leave `engine` undefined there and the ten Codex
    // tools cleanly return `feature_unavailable` (toolCalls.ts gate 5).
    engine: process.platform === 'darwin' ? createCodexEngine() : undefined,
```

**type-via-clipboard（macOS）**：`type(text, {viaClipboard})` 走剪贴板暂存——先存旧剪贴板 → 写新文本 → `paste_clipboard` → 延时后恢复旧内容；Windows 走 `key: ctrl+v`。

## Deterministic REPL VM

Computer Use 不只有上一段「控制层」（截图 / 点击 / 键入，由 cu-helper daemon + mcp 工具实现）；它还暴露一个**独立的 JS 内核**，让用户或模型在隔离环境里写脚本操作 UI。这套执行环境由 compiler → worker → runtime 三层组成，与 Workflow 的确定性 VM（见 [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md) 引擎段）是**两套互不相干**的机制。

### 三层架构（compiler → worker → runtime）
- **编译层 `src/utils/computerUse/replCompiler.ts`**：`compileReplCell(code, prior)` 用 `acorn` 解析并做 AST 变换，把所有**自由标识符**（未在局部 / 上层词法作用域声明的变量名）重写为注入的持久作用域取值——`Date` / `Math` / `fetch` 等全部经此重定向；禁止 `import` / `export`（硬错误 "Module imports and exports are not available in Computer Use JavaScript"）；`randomUUID()` 生成唯一前缀 `__cu_cell_<uuid>_` 防命名冲突；`typeof` 改 `scope.typeOf("x")` 避免原生 `ReferenceError`；`const` 重赋值只给 warning 不抛错：

```ts
export function compileReplCell(code: string, prior: readonly ReplBinding[]) {
  const ast = parse(code, { ecmaVersion: 'latest', sourceType: 'module' }) as unknown as SyntaxNode
  const current = new Map<string, ReplBinding>()
  const identifiers = new Set<string>()
  const hoistedDeclarations: Array<{ node: SyntaxNode; parent?: SyntaxNode }> = []
  const insertions: Array<{ position: number; text: string }> = []

  function inspect(node: SyntaxNode, depth: number, inFunctionScope: boolean, parent?: SyntaxNode) {
    // A free call becomes `(0, scope.values[name])(...)`. Its new leading
    // parenthesis can undo ASI after the preceding expression, initializer,
    // return, or throw. Preserve boundaries from the original parsed program,
    // including nested function bodies, without altering for-loop headers.
    const variableStatement = node.type === 'VariableDeclaration'
```

- **内核层 `src/utils/computerUse/replWorker.ts`**：`vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } })` 创建**禁动态代码生成**（eval / Wasm）的空白上下文；`new Script(...).runInContext(context)` 运行 IIFE 重写 `setTimeout` / `setInterval` / `clearTimeout` / `clearInterval` / `__cuInvoke` / `__cuEmit` 并用 `Proxy` 代理全局。内核本身作为**一次性子进程**由父进程经 stdio JSON-RPC 驱动（`runComputerUseReplWorker`）：

```ts
/**
 * Persistent JavaScript kernel. Production runs this in a disposable process;
 * vm is a language boundary, not the OS sandbox or hard time/memory limit.
 * Only JSON strings cross its host bridge. In particular no host Promise,
 * Error, timer handle/function, module loader, or Node object is passed into the realm.
 */
export function createComputerUseReplWorker(send: (message: ReplOutput) => void) {
  const context = createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false },
  })
  const execution = new AsyncLocalStorage<CellState>()
```

- **运行层 `src/utils/computerUse/replRuntime.ts`**：`ComputerUseRepl` 类，用 `Bun.build()` 把 `replWorker.ts` 打成自包含独立 ESM，再 `spawn('/bin/sh', ['-c', 'exec <command>'], { detached: true, stdio: 'pipe' })` 启动 kernel——**不是 `worker_threads`，是 OS 进程隔离**。

### 隔离与沙箱（`replRuntime.ts`）
- **macOS Sandbox**：`wrapCommandWithSandboxMacOS` 只读 `/System` / `usr/lib` / `usr/share` / `bin/bash` / `usr/bin/env` / `dev` 等 + `readable` 列表，可写仅 `options.directory` 与 `/dev/null`，**网络禁用**（`needsNetworkRestriction: true`）：

```ts
export function createComputerUseReplSandboxCommand(options: { args: string[], readable: string[], directory: string }): string {
  // sandbox-runtime adds its own TMPDIR outside this command. Override it
  // inside the sandbox without changing the parent process's environment.
  const args = ['/usr/bin/env', ...['TMPDIR', 'TMP', 'TEMP'].map(name => `${name}=${options.directory}`), ...options.args]
  return wrapCommandWithSandboxMacOS({
    command: `exec ${args.map(quote).join(' ')}`,
    // /bin/sh is a selector stub on recent macOS and may open
    // /private/var/select/sh. Execute the concrete system shell directly.
    binShell: '/bin/bash',
    needsNetworkRestriction: true,
    readConfig: {
      denyOnly: ['/'],
      allowWithinDeny: [...options.readable, '/System', '/usr/lib', '/usr/share', '/bin/bash', '/usr/bin/env', '/dev', '/private/etc/localtime'],
    },
    writeConfig: { allowOnly: [options.directory, '/dev/null'], denyWithinAllow: [] },
  })
}
```

- **env 隔离**：`HOME` / `TMPDIR` / `TMP` / `TEMP` → 沙箱目录，`PATH = '/usr/bin:/bin'`，`BUN_OPTIONS = '--no-env-file'`，`CLAUDE_CONFIG_DIR` → `directory/.claude`。
- **资源限制**：`maxRssBytes = 768 MB`，`REPL_MAX_ACTIONS` / `REPL_MAX_CODE_BYTES` / `REPL_MAX_OUTPUT_BYTES` 限制行为边界；用户代码超时 `timeoutMs ∈ [1, 60000]`，超时杀 kernel，心跳 2s 无 `pong` 判死并清进程组。

### 确定性（`replWorker.ts`）
- **跨 cell 状态持久化**：执行结束 `bindings = JSON.parse(realm.commit(submittedSucceeded))`，序列化回 `ReplBinding[]` 供下次 `compileReplCell` 复用，实现连续 REPL 状态。
- **纯 JSON 桥接**：只有 JSON 字符串跨 host bridge——无 host Promise / Error / timer handle 进 realm。
- **cell 生命周期纪律**：`AsyncLocalStorage<CellState>` 追踪活跃 cell；cell 首个 Promise settle 后 `accepting = false`，**强制所有 Computer Use 操作必须被 `await`**；`unobservedError()` 检测未 await 的失败操作。
- **定时器**：`MAX_ACTIVE_TIMERS = 1024`，延迟规范到 `0 .. 2,147,483,647`ms，cell 结束 `finally` 清全部 timers。

### 与 Workflow VM 的区别（避免混淆）
- **Workflow VM**：脚本编译为 `vm.Script`，`Date` / `Math.random` / `import` 被**显式抛错**禁用，目的是编排 subagent 的可重放确定性。
- **Computer Use VM**：acorn AST 改写 + vm 沙箱 + macOS sandbox 进程隔离，自由标识符重定向到 realm；禁的是 `import` / `export` 与动态代码生成（eval / Wasm），`Date` / `Math` 等是否确定取决于 realm 提供的取值——为**脚本化 UI 操作**而生。

## Use Cases

适合「改完网页还要在浏览器里点一遍」「操作没有 CLI 的桌面软件」这类纯代码 Agent 覆盖不到的场景。生产环境慎用：未签名 + 版权风险（见 [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md) 的 WARNING）。

## Corrections

| 旧描述 | 源码事实（v0.7.7） |
| :-- | :-- |
| 架构末端是「Python Bridge → 平台 Helper」，Windows 必需 Python + venv + `win_helper.py` | Windows / Linux 改用随安装包的原生 `agent-desktop` 二进制（`agentDesktopBinary.ts` 从 `app.asar.unpacked/src-tauri/binaries` 解析），不再需要 Python / 虚拟环境；`pythonBridge.ts` / `windowsLegacyToolCalls.ts` 代码仍在，但只在「win32 且 `agentDesktop` capability 为假」的 legacy 回退分支生效 |
| Linux 不支持（只允许 macOS + Windows） | Linux 受支持：`mcpServer.ts` 的 `buildPlatformComputerUseTools` 对 `platform === 'linux'` 直接 `buildAgentDesktopTools()`；`gates.ts` 注释「Windows/Linux native CLI」且 `shouldExposeComputerUseMcp` 把 win32 与 linux 并列；`executor.ts` 报错文本也改为「only supported on macOS, Windows and Linux」 |
| macOS 上读取 / 操作目标应用会把它拉到前台，回到 cc-haha 全屏后目标被反复激活 | `TargetVisibilityPolicy.swift` 明言遮挡「never a reason to raise, activate, or reject a mutation」，输入「without activating or raising the target」；`release-notes/v0.7.7.md` 亦记载该行为已去除 |
| Windows 的 `engine` 一律为 `undefined`、十类 Codex 工具返回 `feature_unavailable`、CLI 像素层经 pyautogui 可用 | 该结论只对应 legacy CLI executor 的非 darwin 分支；新版 Windows 走原生 `agent-desktop` 工具集（`buildAgentDesktopTools` / `bindAgentDesktopSession`），不再以 pyautogui 为主路径 |

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/CcHaha/Tools.md)
- [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md)

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
