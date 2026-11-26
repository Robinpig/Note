## Introduction

`pi-tui` 是 Pi 的终端 UI 库：把组件树布局成固定宽度的文本行，与上一帧逐行比较后只重写变化的行，并负责输入解析、编辑器、markdown 渲染和按键绑定。它不依赖 React、ink 或任何虚拟 DOM 框架；所谓「差分渲染」是**行级字符串比较 + 光标寻址**，不是组件级 reconciler。本页按 v1.5.2（commit `b4afdddf`）源码核验。

三个先摆正的事实：① 组件 `render(width)` 的结果按**宽度**缓存，同一宽度不重复渲染；② 差分的粒度是整行，找到第一个 / 最后一个变化行后只重写这个区间；③ 一旦变化落在可视区之外（或终端宽度变了、行超宽），立即退回全量重绘，而不是滚动补偿。

## Rendering Pipeline

`TuiBase` 继承 `Container`，`renderNow()` / `requestRender()` 触发渲染，内部 `doRender()` 由 main-screen / alt-screen 两个子类实现。渲染节流有硬下限：`MIN_RENDER_INTERVAL_MS = 16`，`renderRequested` 与 `immediateRenderScheduled` 两个标志分别处理「稍后渲染」和「马上渲染」；`fullRedrawCount` 单独统计全量重绘次数。

一帧的生成顺序（`TuiMainScreen.doRender()`）：

1. `this.render(width)` 把组件树渲染为行数组，去掉 OSC 133 zone 标记（终端会把 `133;A` 当成新 shell prompt，从而结束程序状态 OSC 7501）；
2. `resolveFakeCursors()` 把「假光标」标记解析成真实 SGR；
3. 有 overlay 时先 `compositeOverlays(newLines, width, height)` 合成到行上——**合成发生在比较之前**，否则弹层的变化会被漏掉；
4. `extractCursorPosition()` 取出光标位置，`applyLineResets()` 处理行状态复位；
5. 与 `previousLines` 比较，决定全量还是差分；
6. 输出经 `BoundedTerminalWriter` 按块写出（上限 `MAX_RENDER_WRITE_CHARS`），整帧包在 `\x1b[?2026h` / `\x1b[?2026l` 同步输出里，避免闪烁。

```ts
		let newLines = this.resolveFakeCursors(this.render(width).map((line) => line.replace(OSC133_ZONE_PREFIX, "")));

		// Composite overlays into the rendered lines (before differential compare)
		if (this.hasOverlayEntries) {
			newLines = this.compositeOverlays(newLines, width, height);
		}

		// Extract cursor position before applying line resets (marker must be found first)
		const cursorPos = this.extractCursorPosition(newLines, height);

		newLines = this.applyLineResets(newLines);
```

## Differential Rendering

差分从找出 `firstChanged` / `lastChanged` 开始：对 `max(newLines.length, previousLines.length)` 逐行做字符串不等比较；新增行时把区间扩到末尾；Kitty 图片行还要通过 `expandChangedRangeForKittyImages()` 扩展范围（图片占多行，删一张要删掉它预留的全部行）。完全没变化时不写任何行，只调整硬件光标位置。

```ts
		const maxLines = Math.max(newLines.length, this.previousLines.length);
		for (let i = 0; i < maxLines; i++) {
			const oldLine = i < this.previousLines.length ? this.previousLines[i] : "";
			const newLine = i < newLines.length ? newLines[i] : "";

			if (oldLine !== newLine) {
				if (firstChanged === -1) firstChanged = i;
				lastChanged = i;
			}
		}
```

**全量重绘有五个触发条件**：首次渲染；终端宽度变化（换行位置变了，无法局部修正）；终端高度变化（Termux 的软键盘除外——那里全量重绘会让历史每次弹键盘都重放一遍）；`clearOnShrink` 开启且内容缩到已渲染最大高度以下且无 overlay；以及 `firstChanged < previousViewportTop`（变化发生在滚出屏幕的历史里）。

差分路径先算「屏幕行 = 缓冲区行 − viewportTop」，用 `\x1b[nB` / `\x1b[nA` 把光标移到第一个变化行，再逐行 `\x1b[2K` 清行后写入新内容；最后调用 `positionHardwareCursor()` 落到逻辑光标处。关键约束写在注释里：**差分只能触碰实际可见的内容**。行宽超过 `terminal.columns` 会被视为自定义组件忘了截断，写 crash 日志到 `pi-tui-crash.log`、清理终端状态后抛错——这不是「自动换行兜底」。

## Layout

布局的产物是 `LayoutBox` 树：每个节点带 `rect`（x/y/width/height）、`clip`（与父 clip 的交集）、`children`、`layer`，以及可选的 `lines` / `lineOffset` / `scrollView`。`layoutComponent()` 递归分配矩形，`updateClips()` 自顶向下求交，`translateBox()` 平移子树。组件高度常常由它渲染出的行数决定，因此布局与渲染是交织的：

```ts
function renderCached(context: LayoutContext, component: Component, width: number): string[] {
	const safeWidth = Math.max(1, Math.floor(width));
	let widths = context.renderCache.get(component);
	if (!widths) {
		widths = new Map<number, string[]>();
		context.renderCache.set(component, widths);
	}
	let lines = widths.get(safeWidth);
	if (!lines) {
		lines = component.render(safeWidth);
		widths.set(safeWidth, lines);
	}
	return lines;
}

function measureHeight(context: LayoutContext, component: Component, width: number): number {
	return renderCached(context, component, width).length;
}
```

`renderCache` 是 `Map<Component, Map<number, string[]>>`——按组件、按宽度双层缓存，宽度不变就不重新渲染。栈类布局用 `allocateStackSizes()` / `visibleStackEntries()`（`components/stack.ts`）分配子项尺寸；`getLayoutNode()` 允许组件挂自定义布局策略（`layout-node.ts`）。行合成用 `compositeTuiLine()` 按 layer 叠加，颜色处理走 `oklab.ts` / `terminal-colors.ts`，宽度测量用 `utils.ts` 的 `visibleWidth()`（忽略 ANSI 与控制字符的可见宽度）和 `sliceByColumn()` / `getGraphemeCellRange()`（按字素簇切列，避免把宽字符或 emoji 切一半）。

## Input Processing

`StdinBuffer` 解决的是「一次数据事件可能只包含半个转义序列」：鼠标 SGR 序列 `\x1b[<35;20;5m` 可能分三次到达，直接解析会把 `\x1b` 当成 Escape 键。它按 CSI（终字节 0x40–0x7E）、OSC（ST 或 BEL 结束）、DCS / APC（ST 结束）、SS3、meta-key 分别判定完整性，只有完整序列才 emit `data`：

```ts
function isCompleteSequence(data: string): "complete" | "incomplete" | "not-escape" {
	if (!data.startsWith(ESC)) return "not-escape";
	if (data.length === 1) return "incomplete";
	const afterEsc = data.slice(1);
	if (afterEsc.startsWith("[")) {
		// Check for old-style mouse sequence: ESC[M + 3 bytes
		if (afterEsc.startsWith("[M")) return data.length >= 6 ? "complete" : "incomplete";
		return isCompleteCsiSequence(data);
	}
	if (afterEsc.startsWith("]")) return isCompleteOscSequence(data);
	if (afterEsc.startsWith("P")) return isCompleteDcsSequence(data);
	if (afterEsc.startsWith("_")) return isCompleteApcSequence(data);
	if (afterEsc.startsWith("O")) return afterEsc.length >= 2 ? "complete" : "incomplete";
	if (afterEsc.length === 1) return "complete";
	return "complete";
}
```

两个超时值：`timeout = 50ms`（不完整键鼠序列）、`escapeTimeout = 10ms`（孤立 ESC 何时当 Escape 键，SSH 高延迟可调大）。但**已识别的终端回复头不走超时**——颜色查询 / XTVersion / Kitty 图形回复可能迟到，若按超时 flush，尾巴会变成普通文本、OSC 的 BEL 会变成 Ctrl+G（外部编辑器快捷键）。`\x1b[200~` / `\x1b[201~` 之间的内容进入 `pasteMode`，整体作为一次 `paste` 事件发出，不会被逐字解释成快捷键。WezTerm 开启 Kitty keyboard 后 Escape 按下是裸 `\x1b`、抬起是完整 CSI-u，缓冲区对连续的 `\x1b\x1b[` 特殊处理，只发第一个 ESC。

按键解析在 `keys.ts` / `keybindings.ts`：`Key` 是带 `name` / `shift` / `alt` / `ctrl` / `meta` 等字段的结构，Kitty CSI-u 编码可携带修饰键和按键事件类型。但**单独按下修饰键**在多数终端没有序列可解析，只能问操作系统：`native-modifiers.ts` 调用平台 helper 的实时查询（Windows / macOS / Linux 各有 native 实现）：

```ts
export function isNativeModifierPressed(key: ModifierKey): boolean {
	const helper = getNativePlatformHelper();
	if (!helper?.isModifierPressed) return false;
	try {
		return helper.isModifierPressed(key) === true;
	} catch {
		return false;
	}
}
```

## Editor and Components

`components/editor.ts` 是 Pi 的输入编辑器：多行文本、光标、自动补全、CJK 安全的撤销栈（`undo-stack.ts`）与 kill-ring（`kill-ring.ts`，Emacs 风格复制 / 粘贴）。编辑历史写入 `<agent-dir>/keybindings.json` 可改绑的命名动作体系（如 `tui.editor.cursorUp`），**没有硬编码的按键判断**——Pi 自己的开发规则也禁止新增 `matchesKey(keyData, "ctrl+x")` 这类硬编码。

其余组件各司其职：`text` / `truncated-text` 渲染文本，`v-stack` / `h-stack` / `box` / `spacer` 做布局，`scroll-view` 滚动，`select-list` / `settings-list` / `input` 做选择，`markdown` 渲染富文本，`cancellable-loader` / `loader` 做进度，`image` / `terminal-image` 处理 Kitty 图像协议，`alt-screen-flash` / `mouse-region` 处理特殊区域。`fuzzy.ts` 提供搜索排序，`latex.ts` 公式渲染，`autocomplete.ts` 补全状态机。

## Main Screen vs Alt Screen

| | `TuiMainScreen` | `TuiAltScreen` |
| :--- | :--- | :--- |
| `mode` | `"regular"` | `"fullscreen"` |
| 终端区域 | 主屏 + scrollback | 备用屏，退出时恢复 |
| 默认 | `--tui-mode regular` | 默认全屏 |
| 特殊处理 | 图片预留行、viewportTop、Termux 高度变化 | alt screen 序列、退出恢复 |

`TuiMainScreenRenderState` 保存 `previousLines` / `previousWidth` / `previousHeight` / `cursorRow` / `hardwareCursorRow` / `maxLinesRendered` / `previousViewportTop`，`captureRenderState()` / `restoreRenderState()` 用于状态取回；恢复时图片行会被清空（`isImageLine` → `""`）并重置图片 ID 集合，避免引用已经失效的 Kitty 图像。退出时 `getExitRestorePrefix()` 负责重新显示光标并关闭颜色通知。

## Corrections

| 常见误述 | 源码事实 |
| :--- | :--- |
| 用虚拟 DOM diff 做组件级更新 | 行级字符串比较，找 `firstChanged` / `lastChanged` 区间，逐个 `\x1b[2K` 重写 |
| 变化只在可视区内时才更新屏幕 | 变化落在 viewport 之上就 `fullRender(true)`，差分**只碰可见区** |
| 组件每次渲染都重新计算 | `renderCache` 按组件 + 宽度双层缓存，宽度不变直接复用 |
| 终端宽度变了靠差分修正 | 宽度变化必然全量重绘，因为换行位置全部改变 |
| stdin 收到 escape 就立刻当 Escape 键 | `StdinBuffer` 等完整性判定；孤立 ESC 等 10ms，其他不完整序列等 50ms；已知终端回复头**不超时 flush** |
| 修饰键状态从键盘序列解析 | 单独按修饰键通常没有序列，走平台 native helper 实时查询 |
| 行超出终端宽度会自动换行 | 视为组件 bug：写 crash 日志、停 TUI、抛错 |

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Interaction：日常交互与快捷键](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)
- [Extensions：终端 UI 扩展点](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [CodeMode：脚本调工具](/docs/CS/AI/LLM/Agent/Product/Pi/CodeMode.md)
- [OpenCode TUI（对照）](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md)

## References

- [pi-tui README（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/README.md)
- [TUI 基类与接口（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/src/tui.ts)
- [主屏差分渲染（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/src/tui-main-screen.ts)
- [布局与合成（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/src/layout.ts)
- [输入缓冲（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/src/stdin-buffer.ts)
- [原生修饰键查询（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/tui/src/native-modifiers.ts)
