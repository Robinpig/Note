## Introduction

桌面宠物是 cc-haha 相对其他 agent 工作台的趣味差异化点：一只窗体宠物常驻桌面，**跟随 agent 活动切换动作与表情**、并弹出气泡点评当前任务。它不是严肃生产力模块，但是「工作台有人情味」的鲜明标识（Claude Code / OpenCode 均无此能力）。

底层有两块代码，命名易混：

- `desktop/electron/services/pets.ts`（本切片抓到的这份）——**自定义宠物目录的加载器 / 校验器**（`createCustomPetFromAtlas` / `loadCustomPets` / 安装与原子暂存），**不是**会话 / 代理编排器。
- `desktop/electron/services/petWindow.ts` 的 `PetWindowController` —— 真正拥有宠物窗口生命周期（创建 / 显示 / 隐藏 / 销毁 / 拖拽 / 位置持久化）。
- `desktop/src/features/pets/*`（React 渲染层）—— `PetApp.tsx`（状态 / 轮询 / 偏好）/ `PetRenderer.tsx`（精灵渲染）/ `petAnimation.ts`（帧动画）/ `petSessionModel.ts`（会话状态→宠物状态映射）/ `builtinPets.ts`（内置清单）。

> 实例化 `PetWindowController` 并注册 `getDesktopHost().pets.*` IPC 的主进程桥接代码未在本切片内（仅渲染层引用），以下结论基于上述 7 个文件。

## Built-in Pets

`BUILTIN_PETS` 共 **4 只**（`builtinPets.ts:11-56`），每只绑定一个活动主题（编码在 id 与 description，无独立 `theme` 字段）与一枚 accent 色、`spriteVersionNumber: 2` 的 `spritesheet.webp`：

| id | 名字 | 主题 | accent |
| :-- | :-- | :-- | :-- |
| `dada-code` | 搭搭 Dada | code（协作搭建） | `#4fd1b6` |
| `huhu-plan` | 弧弧 Huhu | plan（路线 / 计划） | `#6ea8ff` |
| `bubu-fix` | 补补 Bubu | fix（修补裂缝） | `#ff9a76` |
| `huihui-build` | 回回 Huihui | build（构建齿轮） | `#9b8cff` |

**关键澄清**：主题只体现在 id / 描述，**没有运行时的「agent 活动 → 宠物」1:1 映射**。用户选一只宠物**全局显示**，agent 活动改变的是该宠物的*动画*而非显示哪只宠物——`selectedPet = allPets.find(pet.id === preferences.selectedPetId)`（`PetApp.tsx:340`），`petSessionModel.ts` 决定的是 dominant *activity*，不是哪只宠物。

## Rendering and Animation

**DOM / CSS 实现，非 canvas**：`PetRenderer.tsx` 用 `<div>` 配 `background-image: url(spritesheet)`，按帧偏移 `background-position`（`PetRenderer.tsx:129-144`）；单图自定义宠物改用 `background-size: contain`（`PetRenderer.tsx:289-297`）。

- **Atlas V2 布局**：`PET_ATLAS_V2` 为 **8 列 × 11 行**，单元 192×208，整图 1536×2288（`petAnimation.ts:3-11`）。
- **可变 fps**：每帧 `frameDurationsMs`，由 `usePetPlayback` 的 `setTimeout` 循环驱动（`PetRenderer.tsx:225-239`）。
- **各状态帧数**（`petAnimation.ts:32-42`）：idle 6 / running-right 8 / running-left 8 / running 7 / waving 4 / jumping 5 / failed 8 / waiting 6 / review 6。
- **idle vs active**：idle = 2 个环境 idle 循环（×6 时长乘子 `PET_IDLE_DURATION_MULTIPLIER`）穿插 `waving` / `jumping` 手势；非 idle = 3 个 active 突发循环后回落慢 idle（`petAnimation.ts:129-154`）。
- **视线**：16 个注视方向（22.5° 步进）映射到 atlas 第 9–10 行（`getPetLookFrame` / `quantizePetLookDirection`，`petAnimation.ts:280-322`）；idle 时视线跟随光标（`PetApp.tsx:524-534`）。
- **瞬时反应**：`PET_TRANSIENT_ANIMATIONS`——完成→jumping、错误→failed、交互→waving、左右拖拽→running-left/right（`petAnimation.ts:341-348`）。

## Window Management

`petWindowOptions`（`petWindow.ts:386-424`）：`transparent: true`（414）、`alwaysOnTop: true`（393）、`frame: false`（396）、`type: 'panel'`（macOS，415）、尺寸 **384×400** 含 24px 边距（21-23）；非 darwin 用 `skipTaskbar`、darwin 用 `enableLargerThanScreen`（411-413）。

- **点击穿透**：macOS `setIgnoreMouseEvents(true, { forward: true })`（428）；其他平台用 `setShape` 仅遮罩内容区（431,643-649）。渲染层在 mascot 悬停 / 离开时切换 passthrough（`PetApp.tsx:479,523,538`）。
- **位置**：默认右下角（`getPetWindowBounds`，`petWindow.ts:373-380`），从 `pet-window.json` 恢复（`readPetWindowPosition`，`petWindow.ts:159`）；可拖拽，拖拽用光标采样器（`PET_WINDOW_DRAG_INTERVAL_MS = 16`，`petWindow.ts:734`）并按显示器工作区夹紧（`getWorkAreaForPoint`）；面板上下 / 左右摆放由主进程 `resolvePetPanelPlacement` 决定（256-310）。
- **显示 / 隐藏**：`PetWindowController.show()/hide()`（555,570）；渲染层经 `getDesktopHost().pets.hide()` 触发（`PetApp.tsx:327`）。

## Session Integration

宠物通过**轮询**而非事件订阅感知 agent 活动：每 **2s** `sessionsApi.getChatStatus` 拉取每个 observed session（`PetApp.tsx:261`，`STATUS_REFRESH_INTERVAL_MS = 2000`），chat store 每 5s 轮询（179）。

- `resolvePetSessionStatus`（`petSessionModel.ts:23-39`）把 `chat.chatState`（permission_pending→`waiting`；非 idle→`running`）、后台任务、observed status、错误信息映射为 status；`buildPetSessionActivities` 按 `STATUS_PRIORITY`（waiting>failed>review>running>idle，`petSessionModel.ts:15-21`）排序。
- `primaryActivity = permissionActivities[0] ?? activities[0]`（`PetApp.tsx:334`），`baseAnimation = petStatusAnimation(primaryActivity.status)`（`PetApp.tsx:335`）；动画映射见 `PET_CHAT_STATE_ANIMATIONS`（`petAnimation.ts:332-339`）：thinking / compacting / tool_executing / streaming→`running`，permission_pending→`waiting`。
- **气泡**：`PetActivityPanel` 渲染 activity 的 `preview` 字符串（`currentPetPreview` / `latestAssistantPreview`，`petSessionModel.ts:51-71`）。
- **全局关联**：宠物聚合**所有 session**（observedSessions），非单会话绑定。

## Custom Pets

支持两种格式（`pets.ts`）：

- **Atlas v2**：`spritesheetPath` + `spriteVersionNumber: 2`，图必须精确 **1536×2288**（`pets.ts:744-754`，`CUSTOM_PET_SPRITESHEET_WIDTH/HEIGHT` 6-7）。
- **单图**：`manifestVersion: 1`、`renderer.kind: 'single-image'`、`imagePath`、`motionProfile: 'soft-spring-v1'`（`pets.ts:833-855`），仅静态 PNG/WebP（拒绝内嵌动画，955-960）。

配置根：`$CLAUDE_CONFIG_DIR/cc-haha/pets`（`resolveCustomPetsRoot`，`pets.ts:249-259`）。严格校验：拒绝符号链接、签名检查、尺寸 / 解码预算（图片 8MB 上限，21-23）；安装器 `createCustomPetFromAtlas` / `createCustomPetFromImage` / `createCustomPetFromAtlasBytes`（引导「九行 action sheet → v2 网格」流程，1116-1120），列表经 `loadCustomPets`（1346）。

## Main-Process Role (Clarification)

- `pets.ts`（本切片这份）= 自定义宠物**目录**：发现 / 校验 / 安装 / 原子暂存，非会话编排器。
- `petWindow.ts` = `PetWindowController` 拥有宠物 BrowserWindow 生命周期（创建 / 显示 / 隐藏 / 销毁 / 拖拽 / 交互区 shape / 面板摆放 / 位置持久化 `writePetWindowPosition`→`pet-window.json`，183-209），是权威绑定 owner（`owns()`，590）。
- `PetApp.tsx`（渲染层）= React 状态 / 会话轮询 / **偏好持久化**（`desktopUiPreferencesApi.get/updatePetPreferences`，132,147）/ 交互区上报 / 拖拽手势 / 显示隐藏请求。
- 偏好项：`enabled` + `selectedPetId` + `showTaskPanel` + `size` + `motionEnabled`（`DesktopPetPreferences`，`PetApp.tsx:122-140`）；窗口矩形在 `pet-window.json`；自定义宠物在 `cc-haha/pets`。

## Design Doc Cross-Check

`docs/desktop/pets.md`（用户向设计文档）与上面基于实现文件的结论**高度吻合**，并补足了几处实现文件未明示的事实。逐条对照（引用以 `pets.md:行` 指设计文档、`*.ts:行` 指实现）：

**一致（实现 ↔ 文档）**
- 4 只内置宠物身份完全对得上：搭搭 Dada / 弧弧 Huhu / 补补 Bubu / 回回 Huihui（`pets.md:25-32` ↔ `builtinPets.ts:11-56`）。
- 渲染为 DOM/CSS（`background-position` 偏移）非 canvas；窗口透明 + 置顶 + 无框 + 点击穿透；右键系统菜单关宠物、不关任务；H5 页面看不到宠物；自定义宠物在 `$CLAUDE_CONFIG_DIR/cc-haha/pets`、单包 ≤ 8MB——均与上面一致。
- 单图自定义宠物「不会跑、不会挥手、不会跟着鼠标转头」（`pets.md:70`）↔ 实现侧 `single-image` 仅静态 PNG/WebP、拒绝内嵌动画（`pets.ts:955-960`）。
- 任务面板三分组（工作中 / 等待你处理 / 需要关注，`pets.md:45-47`）↔ `STATUS_PRIORITY` 的 running / waiting / failed（`petSessionModel.ts:15-21`）。
- 宠物「不能替你批准权限、不能在悬浮窗直接提问」（`pets.md:12`）↔ 上面权限桥结论（H5 / 宠物均不暴露授权）。

**文档补足（实现文件未明示）**
- **默认关闭**：宠物默认 off，需 设置 → 宠物 手动开启（`pets.md:16`），对应 `DesktopPetPreferences.enabled` 默认 false。
- **外观参数**：宠物大小 **96–192 像素**（`pets.md:53`）；「播放动画」关掉后宠物静止但仍在；「默认收起」只露宠物、按需展开任务面板（↔ `size` / `motionEnabled` / `showTaskPanel` 偏好）。
- **无 UI 删除按钮**：删自定义宠物需手动进 `cc-haha/pets` 删子目录再刷新（`pets.md:114`），无内置删除入口。
- **白底拒绝**：导出白底 PNG 在桌面变方块，应用直接拒导入（`pets.md:106-108`）——实现侧透明通道校验（除符号链接 / 签名 / 尺寸预算外）。

**尺寸口径澄清（避免混淆）**
- 设计文档的「**8 列 × 9 行**」是**用户给 AI 画的自定义动作表模板**（`pets.md:76-92`）：最后两行（视线上 / 下圈）可省略、缺省复用待机帧，所以自定义宠物**不一定要**带 16 视线帧。
- 上面代码侧 `PET_ATLAS_V2 = 8 列 × 11 行、1536×2288` 是**内置宠物的成品图集**：多出的第 9–10 行即 `getPetLookFrame` 映射的 **16 个视线方向帧**（每方向 22.5°）。文档也明说「已经是 `1536 × 2288` 的成品图集会原样保留」（`pets.md:102`）——分别描述「自定义模板」与「内置成品」两种形态，并不矛盾。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)

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
