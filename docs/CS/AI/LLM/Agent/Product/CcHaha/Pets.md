## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

桌面宠物是 cc-haha 相对其他 agent 工作台的趣味差异化点：一只窗体宠物常驻桌面，**跟随 agent 活动切换动作与表情**、并弹出气泡点评当前任务。它不是严肃生产力模块，但是「工作台有人情味」的鲜明标识（Claude Code / OpenCode 均无此能力）。

底层代码命名易混，分三层：

- `desktop/electron/services/pets.ts` —— **自定义宠物目录的加载器 / 校验器**（`createCustomPetFromAtlas` / `loadCustomPets` / 安装与原子暂存），**不是**会话 / 代理编排器。
- `desktop/electron/services/petWindow.ts` 的 `PetWindowController` —— 真正拥有宠物窗口生命周期（创建 / 显示 / 隐藏 / 销毁 / 拖拽 / 位置持久化）。
- `desktop/src/features/pets/*`（React 渲染层）—— `PetApp.tsx`（状态 / 轮询 / 偏好）/ `PetRenderer.tsx`（精灵渲染）/ `petAnimation.ts`（帧动画）/ `petSessionModel.ts`（会话状态→宠物状态映射）/ `builtinPets.ts`（内置清单）。

在 v0.7.7 完整源码里，主进程桥接层可以直接查到：`desktop/electron/main.ts` 用 `getPetWindowController()` 实例化控制器并注册 IPC，`desktop/electron/pet-preload.ts` 把 `pets.*` 暴露给渲染层，通道名集中在 `desktop/electron/ipc/channels.ts`。

`desktop/electron/ipc/channels.ts`：
```ts
  petsList: 'desktop:pets:list',
  petsCreateFromImage: 'desktop:pets:create-from-image',
  petsCreateFromAtlas: 'desktop:pets:create-from-atlas',
  petsPickSourceSheet: 'desktop:pets:pick-source-sheet',
  petsCreateFromAtlasBytes: 'desktop:pets:create-from-atlas-bytes',
  petsOpenFolder: 'desktop:pets:open-folder',
  petsShow: 'desktop:pets:show',
  petsHide: 'desktop:pets:hide',
  petsShowContextMenu: 'desktop:pets:show-context-menu',
  petsDragWindow: 'desktop:pets:drag-window',
  petsSetIgnoreMouseEvents: 'desktop:pets:set-ignore-mouse-events',
  petsSetInteractiveRegions: 'desktop:pets:set-interactive-regions',
  petsFocusMainWindow: 'desktop:pets:focus-main-window',
  petsFocusSession: 'desktop:pets:focus-session',
```

## Built-in Pets

`BUILTIN_PETS` 共 **4 只**，每只绑定一个活动主题（编码在 `id` 与 `description`，无独立 `theme` 字段）与一枚 `accent` 色、`spriteVersionNumber: 2` 的 `spritesheet.webp`。

`desktop/src/features/pets/builtinPets.ts`：
```ts
export const BUILTIN_PETS = [
  {
    source: 'builtin',
    id: 'dada-code',
    displayName: '搭搭 Dada',
    description: '沉稳的协作机器人，陪你把想法一块块搭起来。',
    descriptionKey: 'settings.pets.builtin.dada',
    imageUrl: dadaImage,
    spriteVersionNumber: 2,
    spritesheetUrl: dadaSpritesheet,
    accent: '#4fd1b6',
  },
```

`desktop/src/features/pets/builtinPets.ts`：
```ts
  {
    source: 'builtin',
    id: 'huihui-build',
    displayName: '回回 Huihui',
    description: '抱着构建齿轮的小机器人，新回复一到就精神满满。',
    descriptionKey: 'settings.pets.builtin.huihui',
    imageUrl: huihuiImage,
    spriteVersionNumber: 2,
    spritesheetUrl: huihuiSpritesheet,
    accent: '#9b8cff',
  },
] as const satisfies readonly BuiltinPet[]

export function findBuiltinPet(id: string): BuiltinPet {
  return BUILTIN_PETS.find((pet) => pet.id === id) ?? BUILTIN_PETS[0]
}
```

| id | 名字 | 主题 | accent |
| :-- | :-- | :-- | :-- |
| `dada-code` | 搭搭 Dada | code（协作搭建） | `#4fd1b6` |
| `huhu-plan` | 弧弧 Huhu | plan（路线 / 计划） | `#6ea8ff` |
| `bubu-fix` | 补补 Bubu | fix（修补裂缝） | `#ff9a76` |
| `huihui-build` | 回回 Huihui | build（构建齿轮） | `#9b8cff` |

**关键澄清**：主题只体现在 `id` / 描述，**没有运行时的「agent 活动 → 宠物」1:1 映射**。用户选一只宠物**全局显示**，agent 活动改变的是该宠物的*动画*而非显示哪只宠物 —— `selectedPet` 只按 `selectedPetId` 查找，`petSessionModel.ts` 决定的是 dominant *activity*，不是哪只宠物。

`desktop/src/features/pets/PetApp.tsx`：
```tsx
  const primaryActivity = permissionActivities[0] ?? activities[0]
  const baseAnimation = primaryActivity ? petStatusAnimation(primaryActivity.status) : 'idle'
  const animationState = dragDirection
    ? `running-${dragDirection}` as const
    : transientState ?? baseAnimation
  const allPets: readonly PetDescriptor[] = [...BUILTIN_PETS, ...customPets]
  const selectedPet = allPets.find((pet) => pet.id === preferences?.selectedPetId)
    ?? findBuiltinPet(preferences?.selectedPetId ?? '')
```

## Rendering and Animation

**DOM / CSS 实现，非 canvas**：`PetRenderer.tsx` 用 `<div>` 配 `background-image`，按帧偏移 `background-position`；单图自定义宠物改用 `background-size: 'contain'`。

`desktop/src/features/pets/PetRenderer.tsx`：
```tsx
  const style: CSSProperties = usesAtlas ? {
    width: size,
    height,
    ...getAtlasBackgroundStyle({ ...currentVisual, size, height, pixelated }),
  } : {
    width: size,
    height,
    backgroundImage: `url(${JSON.stringify(atlasUrl)})`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'center',
    backgroundSize: 'contain',
    imageRendering: 'auto',
  }
```

`desktop/src/features/pets/PetRenderer.tsx`：
```tsx
function getAtlasBackgroundPosition(
  frame: PetAtlasFrame,
  offsetX: number,
  offsetY: number,
  size: number,
  height: number,
) {
  return `${-frame.columnIndex * size + offsetX}px ${-frame.rowIndex * height + offsetY}px`
}
```

- **Atlas V2 布局**：`PET_ATLAS_V2` 为 **8 列 × 11 行**，单元 192×208，整图 1536×2288。

`desktop/src/features/pets/petAnimation.ts`：
```ts
export const PET_ATLAS_V2 = {
  spriteVersionNumber: 2,
  columns: 8,
  rows: 11,
  cellWidth: 192,
  cellHeight: 208,
  width: 1536,
  height: 2288,
} as const
```

- **可变 fps**：每帧一个 `frameDurationsMs`，由 `usePetPlayback` 的 `setTimeout` 循环驱动；v0.7.7 按已流逝时间算出当前 tick 与「距下一帧的剩余时长」再定时。

`desktop/src/features/pets/PetRenderer.tsx`：
```tsx
    const updateFrame = () => {
      if (cancelled) return
      const tick = getPetAnimationPlaybackTickAtElapsedMs(
        requestedState,
        Math.max(0, performance.now() - startedAt),
      )
      applyVisual({
        frame: tick.frame,
        motionState: tick.motionState,
        phase: tick.phase,
      })
      timer = setTimeout(updateFrame, Math.max(1, Math.ceil(tick.remainingDurationMs)))
    }
```

- **各状态帧数**：`PET_ANIMATION_DEFINITIONS` 每个 `frameDurationsMs` 数组长度即帧数 —— idle 6 / running-right 8 / running-left 8 / running 6 / waving 4 / jumping 5 / failed 8 / waiting 6 / review 6。

`desktop/src/features/pets/petAnimation.ts`：
```ts
export const PET_ANIMATION_DEFINITIONS = {
  idle: { rowIndex: 0, frameDurationsMs: [280, 110, 110, 140, 140, 320] },
  'running-right': { rowIndex: 1, frameDurationsMs: [120, 120, 120, 120, 120, 120, 120, 220] },
  'running-left': { rowIndex: 2, frameDurationsMs: [120, 120, 120, 120, 120, 120, 120, 220] },
  waving: { rowIndex: 3, frameDurationsMs: [140, 140, 140, 280] },
  jumping: { rowIndex: 4, frameDurationsMs: [140, 140, 140, 140, 280] },
  failed: { rowIndex: 5, frameDurationsMs: [140, 140, 140, 140, 140, 140, 140, 240] },
  waiting: { rowIndex: 6, frameDurationsMs: [150, 150, 150, 150, 150, 260] },
  running: { rowIndex: 7, frameDurationsMs: [120, 120, 120, 120, 120, 220] },
  review: { rowIndex: 8, frameDurationsMs: [150, 150, 150, 150, 150, 280] },
} as const satisfies Record<PetAnimationState, PetAnimationDefinition>
```

- **idle vs active**：idle = 2 个环境 idle 循环（×`PET_IDLE_DURATION_MULTIPLIER` 时长乘子）穿插 `waving` / `jumping` 手势；非 idle = `PET_ACTIVE_BURST_LOOPS` 个 active 突发循环后回落慢 idle。

`desktop/src/features/pets/petAnimation.ts`：
```ts
export const PET_ACTIVE_BURST_LOOPS = 3
export const PET_IDLE_DURATION_MULTIPLIER = 6
export const PET_AMBIENT_IDLE_LOOPS = 2
export const PET_AMBIENT_GESTURE_LOOPS = 2
```

`desktop/src/features/pets/petAnimation.ts`：
```ts
  const playback = state === 'idle'
    ? [
      ...Array.from({ length: PET_AMBIENT_IDLE_LOOPS }, slowIdle).flat(),
      ...getRepeatedPetAnimationFrames('waving', PET_AMBIENT_GESTURE_LOOPS, 'action'),
      ...Array.from({ length: PET_AMBIENT_IDLE_LOOPS }, slowIdle).flat(),
      ...getRepeatedPetAnimationFrames('jumping', PET_AMBIENT_GESTURE_LOOPS, 'action'),
    ]
    : [
      ...getRepeatedPetAnimationFrames(state, PET_ACTIVE_BURST_LOOPS, 'action'),
      ...slowIdle(),
    ]
```

- **视线**：16 个注视方向（22.5° 步进）映射到 atlas 的 `rowIndex` 9 / 10（`getPetLookFrame` / `quantizePetLookDirection`）；idle 时视线跟随光标。

`desktop/src/features/pets/petAnimation.ts`：
```ts
export const PET_LOOK_DIRECTIONS = [
  0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5,
  180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5,
] as const
```

`desktop/src/features/pets/petAnimation.ts`：
```ts
export function getPetLookFrame(directionDegrees: PetLookDirection | null): PetLookFrame {
  if (directionDegrees === null) {
    return {
      directionDegrees,
      ...PET_NEUTRAL_LOOK_FRAME,
    }
  }

  const directionIndex = PET_LOOK_DIRECTIONS.indexOf(directionDegrees)
  if (directionIndex < 0) {
    throw new RangeError('directionDegrees must be a supported 22.5-degree step')
  }

  const rowIndex = directionIndex < PET_ATLAS_V2.columns ? 9 : 10
  const columnIndex = directionIndex % PET_ATLAS_V2.columns

  return {
    directionDegrees,
    ...getPetAtlasFrame(rowIndex, columnIndex),
  }
}
```

- **瞬时反应**：`PET_TRANSIENT_ANIMATIONS` —— 完成→jumping、错误→failed、交互→waving、review→review、左右拖拽→running-left/right；`PET_CHAT_STATE_ANIMATIONS` 则把 ChatState 映射到动画。

`desktop/src/features/pets/petAnimation.ts`：
```ts
export const PET_CHAT_STATE_ANIMATIONS = {
  idle: 'idle',
  thinking: 'running',
  compacting: 'running',
  tool_executing: 'running',
  streaming: 'running',
  permission_pending: 'waiting',
} as const satisfies Record<ChatState, PetAnimationState>

export const PET_TRANSIENT_ANIMATIONS = {
  completion: 'jumping',
  error: 'failed',
  interaction: 'waving',
  review: 'review',
  'drag-left': 'running-left',
  'drag-right': 'running-right',
} as const satisfies Record<string, PetAnimationState>
```

## Window Management

窗口尺寸与拖拽节奏由 `petWindow.ts` 顶部常量给出（384×400，边距 24，拖拽采样 16ms，`pet-window.json` 状态文件）。

`desktop/electron/services/petWindow.ts`：
```ts
export const PET_WINDOW_WIDTH = 384
export const PET_WINDOW_HEIGHT = 400
export const PET_WINDOW_MARGIN = 24
export const PET_WINDOW_PARTITION = 'cc-haha-pet'
export const PET_WINDOW_STATE_FILE = 'pet-window.json'

const MAX_ABSOLUTE_SCREEN_COORDINATE = 1_000_000
const PET_WINDOW_DRAG_INTERVAL_MS = 16
```

`petWindowOptions` 设置 `transparent: true`、`alwaysOnTop: true`、`frame: false`，darwin 用 `type: 'panel'` 与 `enableLargerThanScreen`，其他平台用 `skipTaskbar`。

`desktop/electron/services/petWindow.ts`：
```ts
  return {
    ...bounds,
    alwaysOnTop: true,
    autoHideMenuBar: true,
    backgroundColor: '#00000000',
    frame: false,
    fullscreenable: false,
    hasShadow: false,
    maximizable: false,
    minimizable: false,
    resizable: false,
    show: false,
    // macOS runs a visible window's frame through
    // -[NSWindow constrainFrameRect:toScreen:], which rewrites any y above the
    // work area back down to its top edge. The mascot sits at the bottom of a
    // mostly transparent window, so clamping against it deliberately asks for a
    // negative y to push that padding off-screen — and AppKit silently refused,
    // stranding the mascot a padding-height below the menu bar. This is the one
    // switch that skips that method; clampPetWindowPosition stays the
    // authoritative bound on every platform and every edge.
    ...(platform === 'darwin'
      ? { enableLargerThanScreen: true }
      : { skipTaskbar: true }),
    transparent: true,
    type: platform === 'darwin' ? 'panel' : undefined,
```

- **点击穿透**：macOS `setIgnoreMouseEvents(true, { forward: true })`；其他平台用 `setShape` 仅遮罩内容区。渲染层在 mascot 悬停 / 离开时切换 passthrough。

`desktop/electron/services/petWindow.ts`：
```ts
function configurePetWindow(window: PetWindow, platform: NodeJS.Platform): void {
  if (platform === 'darwin') {
    window.setIgnoreMouseEvents(true, { forward: true })
  } else {
    window.setIgnoreMouseEvents(false)
    window.setShape([{ x: 0, y: 0, width: PET_WINDOW_WIDTH, height: PET_WINDOW_HEIGHT }])
  }
```

`desktop/src/features/pets/PetApp.tsx`：
```tsx
        onMouseEnter={() => void getDesktopHost().pets.setIgnoreMouseEvents(false)}
        onMouseMove={(event) => {
          if (dragGestureRef.current) return
          if (animationState !== 'idle') return
          const rect = mascotRef.current?.getBoundingClientRect()
          if (!rect) return
          setLookDirection(quantizePetLookDirection(
            event.clientX - (rect.left + rect.width / 2),
            event.clientY - (rect.top + rect.height / 2),
            12,
          ))
        }}
        onMouseLeave={() => {
          if (dragGestureRef.current) return
          setLookDirection(undefined)
          void getDesktopHost().pets.setIgnoreMouseEvents(true)
        }}
```

- **位置**：默认右下角（`getPetWindowBounds`），从 `pet-window.json` 恢复（`readPetWindowPosition`）；可拖拽，拖拽用光标采样器并按显示器工作区夹紧（`getWorkAreaForPoint`）；面板上下 / 左右摆放由主进程 `resolvePetPanelPlacement` 决定。

`desktop/electron/services/petWindow.ts`：
```ts
export function getPetWindowBounds(
  workArea: Rectangle,
  restoredPosition?: PetWindowState | null,
): Rectangle {
  if (restoredPosition) {
    return {
      ...clampPetWindowPosition(restoredPosition, workArea, restoredPosition.region),
      width: PET_WINDOW_WIDTH,
      height: PET_WINDOW_HEIGHT,
    }
  }
  return {
    x: Math.max(
      workArea.x,
      workArea.x + workArea.width - PET_WINDOW_WIDTH - PET_WINDOW_MARGIN,
    ),
    y: Math.max(
      workArea.y,
      workArea.y + workArea.height - PET_WINDOW_HEIGHT - PET_WINDOW_MARGIN,
    ),
    width: PET_WINDOW_WIDTH,
    height: PET_WINDOW_HEIGHT,
  }
}
```

- **显示 / 隐藏**：`PetWindowController.show()` / `hide()`；渲染层经 `getDesktopHost().pets.hide()` 触发。

`desktop/electron/services/petWindow.ts`：
```ts
  hide(): void {
    const window = this.window
    this.finishDrag(window ?? undefined)
    if (!window || window.isDestroyed()) {
      this.window = null
      return
    }
    window.destroy()
    this.window = null
    this.resetPanelState()
    this.pendingRestoredPosition = null
  }
```

## Session Integration

宠物通过**轮询**而非事件订阅感知 agent 活动：`STATUS_REFRESH_INTERVAL_MS = 2_000` 拉 `getChatStatus`，chat store 每 5s 轮询（`SESSION_REFRESH_INTERVAL_MS`）。

`desktop/src/features/pets/PetApp.tsx`：
```ts
const TASK_SESSION_LIMIT = 9
const SESSION_REFRESH_INTERVAL_MS = 5_000
const STATUS_REFRESH_INTERVAL_MS = 2_000
const CUSTOM_PET_REFRESH_INTERVAL_MS = 30_000
const PET_DRAG_THRESHOLD_PX = 4
```

`desktop/src/features/pets/PetApp.tsx`：
```tsx
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const results = await Promise.all(observedSessions.map(async (session) => {
          try {
            const result = await sessionsApi.getChatStatus(session.id, controller.signal)
            return [session.id, result.activityState] as const
          } catch {
            return [session.id, null] as const
          }
        }))
        if (cancelled) return
        setObservedStatuses((current) => Object.fromEntries(results.map(([sessionId, status]) => [
          sessionId,
          status ?? current[sessionId] ?? 'idle',
        ])))
      } finally {
        inFlight = false
      }
    }
    void refresh()
    const timer = setInterval(() => void refresh(), STATUS_REFRESH_INTERVAL_MS)
```

- `resolvePetSessionStatus` 把 `chat.chatState`（`permission_pending`→`waiting`；非 idle→`running`）、后台任务、observed status、错误信息映射为 status；`buildPetSessionActivities` 按 `STATUS_PRIORITY`（waiting>failed>review>running>idle）排序。v0.7.7 里完成态的 `review` 被显式折叠为 `idle`。

`desktop/src/features/pets/petSessionModel.ts`：
```ts
export type PetSessionStatus = 'waiting' | 'failed' | 'review' | 'running' | 'idle'
```
```ts
const STATUS_PRIORITY: Record<PetSessionStatus, number> = {
  waiting: 0,
  failed: 1,
  review: 2,
  running: 3,
  idle: 4,
}
```

`desktop/src/features/pets/petSessionModel.ts`：
```ts
export function resolvePetSessionStatus(
  chat: PerSessionState | undefined,
  review = false,
  observed: PetSessionStatus = 'idle',
): PetSessionStatus {
  if (chat?.chatState === 'permission_pending') return 'waiting'
  if (chat && chat.chatState !== 'idle') return 'running'
  if (hasRunningBackgroundTasks(chat?.backgroundAgentTasks)) return 'running'
  if (observed === 'waiting' || observed === 'running') return observed
  if (chat?.messages.at(-1)?.type === 'error') return 'failed'
  if (observed === 'failed') return 'failed'
  if (chat?.historyStatus === 'error') return 'failed'
  // Older servers reported every successful turn as review while its tab was
  // still open. Completion is idle unless a real actionable state is present.
  if (review || observed === 'review') return 'idle'
  return 'idle'
}
```

- 主线 `baseAnimation` 由 `petStatusAnimation(primaryActivity.status)` 得出（见上文 `PetApp.tsx` 代码块），它是 `petSessionModel.ts` 里状态→同名动画的 switch；`PET_CHAT_STATE_ANIMATIONS` 属于 `resolvePetAnimationState` 的 ChatState 映射，是另一套表。

`desktop/src/features/pets/petSessionModel.ts`：
```ts
export function petStatusAnimation(status: PetSessionStatus): PetAnimationState {
  switch (status) {
    case 'waiting': return 'waiting'
    case 'failed': return 'failed'
    case 'review': return 'review'
    case 'running': return 'running'
    case 'idle': return 'idle'
  }
}
```

- **气泡**：`PetActivityPanel` 渲染 activity 的 `preview` 字符串（`currentPetPreview` / `latestAssistantPreview`）。

`desktop/src/features/pets/petSessionModel.ts`：
```ts
export function latestAssistantPreview(messages: readonly UIMessage[] | undefined, maxLength = 120): string {
  const message = [...(messages ?? [])]
    .reverse()
    .find((candidate) => candidate.type === 'assistant_text')
  if (!message || message.type !== 'assistant_text') return ''
  const normalized = message.content.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength
    ? `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
    : normalized
}

export function currentPetPreview(chat: PerSessionState | undefined, maxLength = 120): string {
  const live = chat?.streamingText?.trim() || chat?.statusVerb?.trim() || ''
  if (live) {
    const normalized = live.replace(/\s+/g, ' ')
    return normalized.length > maxLength
      ? `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
      : normalized
  }
  return latestAssistantPreview(chat?.messages, maxLength)
}
```

- **全局关联**：宠物聚合**所有 session**（`observedSessions`），非单会话绑定。

## Custom Pets

支持两种格式，由 `desktop/electron/services/pets.ts` 校验。尺寸、manifest 版本、motion profile 与各类字节 / 像素预算都定义在该文件顶部常量里。

`desktop/electron/services/pets.ts`：
```ts
export const CUSTOM_PET_SPRITESHEET_WIDTH = 1536
export const CUSTOM_PET_SPRITESHEET_HEIGHT = 2288
export const CUSTOM_PET_SPRITESHEET_PIXELS =
  CUSTOM_PET_SPRITESHEET_WIDTH * CUSTOM_PET_SPRITESHEET_HEIGHT
export const CUSTOM_PET_SINGLE_IMAGE_MIN_DIMENSION = 32
export const CUSTOM_PET_SINGLE_IMAGE_MAX_DIMENSION = 4096
export const CUSTOM_PET_SINGLE_IMAGE_MAX_PIXELS =
  CUSTOM_PET_SINGLE_IMAGE_MAX_DIMENSION * CUSTOM_PET_SINGLE_IMAGE_MAX_DIMENSION
export const CUSTOM_PET_SINGLE_IMAGE_MANIFEST_VERSION = 1
export const CUSTOM_PET_SINGLE_IMAGE_RENDERER_VERSION = 1
export const CUSTOM_PET_SINGLE_IMAGE_MOTION_PROFILE = 'soft-spring-v1' as const
export const CUSTOM_PET_FOLDER_MAX_LENGTH = 73
export const DEFAULT_CUSTOM_PET_MAX_ENTRIES = 128
export const DEFAULT_CUSTOM_PET_MAX_DECODED_PIXELS = CUSTOM_PET_SPRITESHEET_PIXELS * 16
export const DEFAULT_CUSTOM_PET_MAX_MANIFEST_BYTES = 64 * 1024
export const DEFAULT_CUSTOM_PET_MAX_IMAGE_BYTES = 8 * 1024 * 1024
export const DEFAULT_CUSTOM_PET_MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024
export const DEFAULT_CUSTOM_PET_MAX_TOTAL_DATA_URL_BYTES = 12 * 1024 * 1024
```

- **Atlas v2**：`spritesheetPath` + `spriteVersionNumber: 2`，图必须精确 **1536×2288**。

`desktop/electron/services/pets.ts`：
```ts
function assertAtlasImageSize(size: ImageSize): void {
  if (
    size.width !== CUSTOM_PET_SPRITESHEET_WIDTH ||
    size.height !== CUSTOM_PET_SPRITESHEET_HEIGHT
  ) {
    throw new PetPackageError(
      'invalid-image-dimensions',
      `The spritesheet image must be ${CUSTOM_PET_SPRITESHEET_WIDTH}x${CUSTOM_PET_SPRITESHEET_HEIGHT}.`,
    )
  }
}
```

- **单图**：`manifestVersion: 1`、`renderer.kind: 'single-image'`、`imagePath`、`motionProfile: 'soft-spring-v1'`，仅静态 PNG/WebP（拒绝内嵌动画）。

`desktop/electron/services/pets.ts`：
```ts
  if (manifest.manifestVersion !== CUSTOM_PET_SINGLE_IMAGE_MANIFEST_VERSION) {
    throw new PetPackageError(
      'invalid-manifest-version',
      `manifestVersion must be ${CUSTOM_PET_SINGLE_IMAGE_MANIFEST_VERSION}.`,
    )
  }
  if (!isRecord(manifest.renderer)) {
    throw new PetPackageError('invalid-renderer', 'renderer must be an object.')
  }
  const renderer = manifest.renderer
  if (
    renderer.kind !== 'single-image' ||
    renderer.version !== CUSTOM_PET_SINGLE_IMAGE_RENDERER_VERSION
  ) {
    throw new PetPackageError(
      'invalid-renderer',
      `renderer must use single-image version ${CUSTOM_PET_SINGLE_IMAGE_RENDERER_VERSION}.`,
    )
  }
  const motionProfile = renderer.motionProfile ?? CUSTOM_PET_SINGLE_IMAGE_MOTION_PROFILE
  if (motionProfile !== CUSTOM_PET_SINGLE_IMAGE_MOTION_PROFILE) {
    throw new PetPackageError('invalid-renderer', 'The single-image motion profile is unsupported.')
  }
```

`desktop/electron/services/pets.ts`：
```ts
  if (!hasExpectedImageSignature(data, candidate.mimeType)) {
    throw new PetPackageError('invalid-image', 'The pet image header is invalid.')
  }
  if (hasEmbeddedImageAnimation(data, candidate.mimeType)) {
    throw new PetPackageError(
      'invalid-image',
      'The pet image must be a static PNG or WebP.',
    )
  }
```

- **配置根**：`$CLAUDE_CONFIG_DIR/cc-haha/pets`（`resolveCustomPetsRoot`）。严格校验：拒绝符号链接、签名检查、尺寸 / 解码预算（图片 8MB 上限）。

`desktop/electron/services/pets.ts`：
```ts
export function resolveCustomPetsRoot(options: CustomPetsRootOptions = {}): string {
  if (options.root) return path.resolve(options.root)

  const env = options.env ?? process.env
  const homeDir = path.resolve(options.homeDir ?? os.homedir())
  const configuredRoot = env.CLAUDE_CONFIG_DIR?.trim()
  const claudeConfigDir = configuredRoot
    ? path.resolve(resolveHomePath(configuredRoot, homeDir))
    : path.join(homeDir, '.claude')
  return path.join(claudeConfigDir, 'cc-haha', 'pets')
}
```

- **安装器**：`createCustomPetFromAtlas` / `createCustomPetFromImage` / `createCustomPetFromAtlasBytes`（后者引导「九行 action sheet → v2 网格」流程，作者无需手工凑 1536×2288），列表经 `loadCustomPets`。

`desktop/electron/services/pets.ts`：
```ts
/**
 * Installs an atlas the renderer assembled in memory. Used by the guided flow that
 * normalizes a nine-row action sheet into the v2 grid, so authors never have to
 * hit 1536x2288 by hand.
 */
export async function createCustomPetFromAtlasBytes(
  input: CreateCustomPetFromAtlasBytesInput,
  options: CreateCustomPetFromAtlasOptions = {},
): Promise<LoadedCustomAtlasPet> {
```

`desktop/electron/services/pets.ts`：
```ts
export async function loadCustomPets(
  options: LoadCustomPetsOptions = {},
): Promise<CustomPetLoadResult> {
  const root = resolveCustomPetsRoot(options)
  const pets: LoadedCustomPet[] = []
  const errors: CustomPetLoadError[] = []
  const maxEntries = normalizeLimit(options.maxEntries, DEFAULT_CUSTOM_PET_MAX_ENTRIES)
  const maxManifestBytes = normalizeLimit(
    options.maxManifestBytes,
    DEFAULT_CUSTOM_PET_MAX_MANIFEST_BYTES,
  )
  const maxImageBytes = normalizeLimit(options.maxImageBytes, DEFAULT_CUSTOM_PET_MAX_IMAGE_BYTES)
```

## Main-Process Role (Clarification)

- `pets.ts` = 自定义宠物**目录**：发现 / 校验 / 安装 / 原子暂存，非会话编排器。
- `petWindow.ts` = `PetWindowController` 拥有宠物 BrowserWindow 生命周期（创建 / 显示 / 隐藏 / 销毁 / 拖拽 / 交互区 shape / 面板摆放 / 位置持久化 `writePetWindowPosition`→`pet-window.json`），是权威绑定 owner（`owns()`）。

`desktop/electron/services/petWindow.ts`：
```ts
export function writePetWindowPosition(
  state: PetWindowState,
  env: NodeJS.ProcessEnv = process.env,
  homeDir: string = os.homedir(),
): void {
  if (areStorageWritesFrozen() || !isPetWindowPosition(state)) return
  const statePath = petWindowStatePath(env, homeDir)
  const temporaryPath = `${statePath}.${process.pid}.tmp`
  try {
    mkdirSync(path.dirname(statePath), { recursive: true, mode: 0o700 })
    writeFileSync(temporaryPath, `${JSON.stringify({
      x: Math.round(state.x),
      y: Math.round(state.y),
```

`desktop/electron/services/petWindow.ts`：
```ts
  owns(window: PetWindow | null): boolean {
    return window !== null && this.window === window && !window.isDestroyed()
  }

  setIgnoreMouseEvents(window: PetWindow, ignore: boolean): void {
    if (!this.owns(window)) {
      throw new Error('Pet window IPC sender does not own the companion window')
    }
    if ((this.options.platform ?? process.platform) !== 'darwin') return
    window.setIgnoreMouseEvents(ignore, ignore ? { forward: true } : undefined)
  }
```

- `PetApp.tsx`（渲染层）= React 状态 / 会话轮询 / **偏好持久化**（`desktopUiPreferencesApi.getPetPreferences` / `updatePetPreferences`）/ 交互区上报 / 拖拽手势 / 显示隐藏请求。

`desktop/src/features/pets/PetApp.tsx`：
```tsx
  const persistPreferences = useCallback(async (patch: Partial<DesktopPetPreferences>) => {
    const current = preferencesRef.current
    if (!current) return false

    const requestId = ++nextPreferencePatchIdRef.current
    pendingPreferencePatchesRef.current.set(requestId, patch)
    const next = { ...current, ...patch }
    preferencesRef.current = next
    setPreferences(next)
    try {
      await desktopUiPreferencesApi.updatePetPreferences(patch)
```

- 偏好项定义在 `desktop/src/api/desktopUiPreferences.ts`（v0.7.7 为 7 项：`enabled` / `selectedPetId` / `size` / `showTaskPanel` / `collapsed` / `motionEnabled` / `lastSessionId`）；窗口矩形在 `pet-window.json`；自定义宠物在 `cc-haha/pets`。

`desktop/src/api/desktopUiPreferences.ts`：
```ts
export type DesktopPetPreferences = {
  enabled: boolean
  selectedPetId: string
  size: number
  showTaskPanel: boolean
  collapsed: boolean
  motionEnabled: boolean
  lastSessionId: string | null
}
```

## Design Doc Cross-Check

`docs/desktop/pets.md`（用户向设计文档）与上面基于实现文件的结论**高度吻合**，并补足了几处实现文件未明示的事实。逐条对照如下。

**一致（实现 ↔ 文档）**
- 4 只内置宠物身份完全对得上：搭搭 Dada / 弧弧 Huhu / 补补 Bubu / 回回 Huihui（见上文 `builtinPets.ts` 代码块）。

`docs/desktop/pets.md`：
```md
| 角色 | 它是谁 |
|---|---|
| 搭搭 Dada | 沉稳的协作机器人，陪你把想法一块块搭起来 |
| 弧弧 Huhu | 拿着铅笔和计划本的路线机器人，复杂任务也能找到出口 |
| 补补 Bubu | 举着修补扳手的小机器人，最擅长发现并修好裂缝 |
| 回回 Huihui | 抱着构建齿轮的小机器人，新回复一到就精神满满 |
```

- 渲染为 DOM/CSS（`background-position` 偏移）非 canvas；窗口透明 + 置顶 + 无框 + 点击穿透；右键系统菜单关宠物、不关任务；H5 页面看不到宠物；自定义宠物在 `$CLAUDE_CONFIG_DIR/cc-haha/pets`、单包 ≤ 8MB —— 均与上面一致。
- 单图自定义宠物「不会跑、不会挥手、不会跟着鼠标转头」↔ 实现侧 `single-image` 仅静态 PNG/WebP、拒绝内嵌动画（见上文 `pets.ts` 代码块）。

`docs/desktop/pets.md`：
```md
这种宠物**不会跑、不会挥手、不会跟着鼠标转头**。想要完整动作，用下面两种。
```

- 任务面板三分组（工作中 / 等待你处理 / 需要关注）↔ `STATUS_PRIORITY` 的 running / waiting / failed。
- 宠物「不能替你批准权限、不能在悬浮窗直接提问」↔ 上面权限桥结论（H5 / 宠物均不暴露授权）。

`docs/desktop/pets.md`：
```md
它只是个状态提示和跳转入口，不能替你批准权限，也不能在悬浮窗里直接提问。
```

**文档补足（实现文件未明示）**
- **默认关闭**：宠物默认 off，需 设置 → 宠物 手动开启，对应 `DesktopPetPreferences.enabled` 默认 false。
- **外观参数**：宠物大小 **96–192 像素**；「播放动画」关掉后宠物静止但仍在；「默认收起」只露宠物、按需展开任务面板（↔ `size` / `motionEnabled` / `collapsed` 偏好）。

`docs/desktop/pets.md`：
```md
- **宠物大小** — 96 到 192 像素之间。
- **播放动画** — 关掉之后宠物还在，只是不动了。想要安静一点又不想彻底关掉时用它。
- **显示进行中的任务区域** — 见上。
- **默认收起** — 平时只露宠物，需要时再展开任务面板。
```

- **无 UI 删除按钮**：删自定义宠物需手动进 `cc-haha/pets` 删子目录再刷新，无内置删除入口。

`docs/desktop/pets.md`：
```md
界面上目前没有删除按钮。要删的话：先在设置页选回一只内置宠物，点「打开文件夹」，只删掉目标宠物那个子目录，回设置页点「刷新」。不要删整个 `pets` 或 `cc-haha` 目录。
```

- **白底拒绝**：导出白底 PNG 在桌面变方块，应用直接拒导入 —— 实现侧透明通道校验（除符号链接 / 签名 / 尺寸预算外）。

`docs/desktop/pets.md`：
```md
最常见的失败是**白底**。白底导出的图在桌面上会变成一个方块，应用会直接拒绝导入。让 AI 重新导出透明背景的 PNG，或者用抠图工具去掉背景。
```

**尺寸口径澄清（避免混淆）**
- 设计文档的「**8 列 × 9 行**」是**用户给 AI 画的自定义动作表模板**：最后两行（视线上 / 下圈）可省略、缺省复用待机帧，所以自定义宠物**不一定要**带 16 视线帧。

`docs/desktop/pets.md`：
```md
要画的是一张 **8 列 × 9 行**的动作表，每格一个动作帧：
```
```md
「向左跑」不用画，应用会把第 2 行水平镜像自动补出来。最后两行懒得画也行，重复待机的第一帧就好，只是它不会跟着鼠标转头。
```

- 上面代码侧 `PET_ATLAS_V2 = 8 列 × 11 行、1536×2288` 是**内置宠物的成品图集**：多出的第 9–10 行即 `getPetLookFrame` 映射的 **16 个视线方向帧**（每方向 22.5°）。文档也明说「已经是 `1536 × 2288` 的成品图集会原样保留」——分别描述「自定义模板」与「内置成品」两种形态，并不矛盾。

`docs/desktop/pets.md`：
```md
所以**长宽不必是某个精确数值**，AI 常出的 `1024 × 1152` 之类都能用，比例接近 8:9 时效果最好。已经是 `1536 × 2288` 的成品图集会原样保留，不会被重新缩放。
```

## Corrections

| 旧描述 | 源码事实（v0.7.7） |
| :-- | :-- |
| 「各状态帧数」里 `running` 是 7 帧 | `petAnimation.ts` 的 `PET_ANIMATION_DEFINITIONS.running.frameDurationsMs` 是 6 个时长（120×5 + 220），即 **6 帧**；不存在 7 帧的定义。 |
| `PET_TRANSIENT_ANIMATIONS` 只有 completion / error / interaction / drag-left / drag-right | 该表 v0.7.7 新增 `review: 'review'`，共 6 项；`resolvePetAnimationState` 让 transient 优先于 ChatState。 |
| `resolvePetSessionStatus` 把成功回合映射为独立 `review` 状态 | `petSessionModel.ts` 明确 `if (review || observed === 'review') return 'idle'`，注释写明「Completion is idle unless a real actionable state is present」；主线不再产生 review 状态。 |
| 主线 `baseAnimation` 的动画映射见 `PET_CHAT_STATE_ANIMATIONS`（ChatState→动画） | 主线用 `petStatusAnimation(primaryActivity.status)`（`petSessionModel.ts` 的 switch：waiting / failed / review / running / idle → 同名动画）；`PET_CHAT_STATE_ANIMATIONS` 属于 `resolvePetAnimationState` 的 ChatState 映射，是另一套表。 |
| `DesktopPetPreferences` 定义在 `PetApp.tsx`，含 5 项（enabled / selectedPetId / showTaskPanel / size / motionEnabled） | 定义在 `desktop/src/api/desktopUiPreferences.ts`，含 **7 项**，新增 `collapsed` 与 `lastSessionId`。 |
| 「实例化 `PetWindowController` 并注册 `getDesktopHost().pets.*` IPC 的主进程桥接代码未在本切片内，结论仅基于 7 个文件」 | v0.7.7 完整源码中桥接层可见：`desktop/electron/main.ts` 的 `getPetWindowController()`、`desktop/electron/pet-preload.ts` 的 `pets.*`、`desktop/electron/ipc/channels.ts` 的通道常量（均见上文）。 |

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)
- [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md)
- [Persistence](/docs/CS/AI/LLM/Agent/Product/CcHaha/Persistence.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [builtinPets.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/features/pets/builtinPets.ts)
- [PetApp.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/features/pets/PetApp.tsx)
- [PetRenderer.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/features/pets/PetRenderer.tsx)
- [petAnimation.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/features/pets/petAnimation.ts)
- [petSessionModel.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/features/pets/petSessionModel.ts)
- [pets.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/electron/services/pets.ts)
- [petWindow.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/electron/services/petWindow.ts)
- [pets.md 设计文档（用户向）](https://github.com/NanmiCoder/cc-haha/blob/main/docs/desktop/pets.md)
