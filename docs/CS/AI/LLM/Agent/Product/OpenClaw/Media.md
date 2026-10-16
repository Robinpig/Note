## Introduction

这一页是 OpenClaw 的**多模态 I/O**：图像 / 视频 / 音乐生成、入站附件理解、语音输出与实时转写、会议机器人、以及网页抓取搜索。它是 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)「四类 tool 来源」里**内置 tools 的实体部分**——那页讲工具如何被调用，这一页讲工具都有哪些、边界在哪。全部遵循「精简 core」原则：vendor 与协议 adapter 都在插件侧，core 只留契约与护栏。

先纠正两处常见猜测：生成与理解**不是干净二分**（生成侧的下载 helper 反而 import 自理解侧的 shared 模块）；agent 侧工具名是 `image_generate` / `video_generate` / `music_generate`（`*_generation` 是 task / catalog kind，不是工具名）。

## Three-Layer Structure

| 层 | 位置 | 职责 |
| :--- | :--- | :--- |
| 共享底座 | `src/media/` | modality-agnostic：probe / transcode / inline-image / attachment + **ffmpeg 沙箱** + media store；被生成与理解两侧**同时**复用 |
| 生成侧 | `media-generation/`（共享）+ `image-generation/` `video-generation/` `music-generation/` | 生成 provider registry + 有序候选 fallback / 几何归一；各模态 runtime 与 capability 契约；vendor 在 `extensions/*` |
| 理解侧 / 语音 / 网页 | `media-understanding/` `tts/` `realtime-transcription/` `web-fetch/` `web-search/` `link-understanding/` | 入站附件理解、语音输出、实时 STT、网页抓取 / 搜索 / 链接富化 |

## Generation Side

一个反直觉事实：**生成不走 LLM 的 `streamText` provider 调用，而是独立的 capability-provider 契约**——`provider.generateImage/Video/Music()` 直接执行，与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的 chat stream loop 是两条路。

- **共享注册**：一个 factory `createMediaProviderRegistry` 建三模态 provider registry；`withImage/Video/MusicGenerationProviders` 包在 acquisition-scoped 生命周期里。fallback 引擎 `runMediaGenerationCandidates` 按序尝试候选（prepare → skip/invoke → 收集 `FallbackAttempt[]` → 抛）；候选来自 `agents.defaults.mediaModels.<modality>` + override + 跨 provider auto fallback。model-ref 直连 `@openclaw/model-catalog-core`。
- **模态契约一致**（`Provider = {id, aliases, defaultModel, models, capabilities, generateX()}`）；video 有三道 pre-I/O guard（mode / reference capability、providerOptions schema、duration cap）。
- **compat provider = core factory 供 extensions 用**：OpenAI 式 `/images/generations` + `/images/edits`、DashScope 式 submit→poll→bounded-download，都从 plugin-sdk 导出；**vendor（OpenAI / Google / fal / 阿里百炼等）是 `extensions/*` 插件**，经 `registerImageGenerationProvider` 一类 API 注册。
- **工具暴露**：`image_generate` / `video_generate` / `music_generate` 注册时经 `resolveOptionalMediaToolFactoryPlan`——**没有配置对应能力模型时 creator 返回 null，工具根本不注册**。任务状态是进程内 Map（不进 SQLite），**输出落文件 media store**（`<configDir>/media` 下按工具分子目录），SQLite 只记引用。

## Understanding Side

理解侧自动按 provider / model 理解入站 turn 的附件（image→caption、audio→transcript、document→text/images），入口 `applyMediaUnderstanding` 按 `CAPABILITY_ORDER=["image","audio","video"]` 经 `pMap` 并发。

门控大脑是 `runCapability`，其中最反直觉的一条：**native-vision skip**——活跃 chat 模型本身支持视觉时**跳过 image 理解**，图直接进模型上下文。**理解是回退而非默认**：只在模型不具备该能力时才发生。audio 有早转写（mention check 先转写再判定），document 抽取是 **plugin-owned**（core 仅 dispatch）。

两种理解模式并存：上述自动入站理解，与模型主动拉的读取工具 `view_image` / `pdf`（复用同一 provider 注册表）。

## Media Foundation

`src/media/` 是共享底座，两处护栏值得记：

- **ffmpeg 沙箱**：硬上限 buffer 10MB、ffprobe 10s、ffmpeg 45s、audio 20min——媒体处理永远在预算内跑。
- **claim-check URI**：读侧 hydrate 出不透明的 `media://inbound/<id>`（Gateway offload 写出），**媒体不直接内联进存储**；`MEDIA_MAX_BYTES = 5MB`。

边界上，渠道扩展**不得直接 import `src/media`**，只走 plugin-sdk 的 `core.channel.media.*`——与 [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) 的「插件不碰核心机制层」同构。Anthropic inline image block 的归一（10MB 解码上限）由 provider transport host 消费。

## Voice: TTS and Realtime Transcription

语音是 Channels 之外的另一 I/O 模态，输出 / 输入两侧是**对偶的两个 owner**：

- **`src/tts/` 是 reply→audio 的输出 owner**，被 talk / meeting-bot 与渠道 reply 共享。三个入口：`synthesizeSpeech`（公开）、`synthesizeTalkSpeech`（host-only，`assertSecretOwnerAvailable("capability","talk:speech")`）、`textToSpeechTelephony`（telephony target）。auto-mode gate 是 `off|tagged|inbound` 三档；输出落 media store（`tool-speech-synthesis` 子目录）。`[[tts …]]` directive DSL 是**过渡态**，canonical 是结构化 `voiceText/voiceProvider/voiceId`。
- **`realtime-transcription/` 是入站 streaming STT 的 owner**（providers 是 extensions，非本地实现）：会话契约 `{connect, sendAudio, close, isConnected}`，WebSocket 实现带 RetrySupervisor 重连 + 有界 queued audio + generation guard。talk 经 Gateway-owned relay 消费它（g711_ulaw 8kHz），meeting-bot 的实时引擎也走这条。

TTS-supplement 的显示投影挂在 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) 的 chat display projection 上（`mergeTtsSupplementMessages` 把音频块回贴到目标文本消息）。

## Meetings and Talk

**meeting-bot**（`src/meeting-bot/`）让 agent 作为「与会者」进入在线会议，听、说、记：

- **三种模式** `agent | bidi | transcribe`（默认 `agent`）。`transcribe` 只转录不发言；`agent`/`bidi` 为 talkback，且「能不能开口」被做成**显式健康断言**（`isMeetingRealtimeRouteReady`：inCall && !micMuted && 音频输入输出已路由 && 无 manualAction），而非尽力而为。
- **浏览器驱动层**：CDP 驱动真实浏览器入会（`chrome-transport` / `browser-controller`），音频捕获、会话控制 + 动作锁（防并发操作同一浏览器）。
- **语音网关**：`createMeetingVoiceCallGateway` / `joinMeetingViaVoiceCallGateway` / `speakMeetingViaVoiceCallGateway` / `endMeetingVoiceCallGatewayCall` 四件套。
- **转录桥**：`transcripts-bridge.runtime.ts` 每 5s 轮询把字幕桥进 [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) 的 `TranscriptsStore`；store 的捕获生命周期在该页。
- **复用主线**：经 `register(api)` 注册转录源 provider、用多个 `api.registerGatewayMethod` 挂 Gateway RPC——直接复用 [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md) 的 register 契约，不另立运行时。

**talk**（`src/talk/`）是唤醒词 / 语音转录 / 语音确认的实时交互层：激活名最多 2 词（`REALTIME_VOICE_ACTIVATION_NAME_MAX_WORDS`）；语音转录有有界待处理队列（防无界堆积）；语音 turn 保留**有界近期上下文**（`DEFAULT_REALTIME_VOICE_TURN_CONTEXT_LIMIT = 32`）——与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的 token 预算同思路，但独立且小得多（语音 turn 短、实时性优先）。

## Web I/O

网页侧有两条内置 tool 与一个非工具富化环节，边界先分清：**`src/web-*` 是 provider 选择 / 执行层，不是工具本体**——工具是 `web_fetch` / `web_search`。

- **`web_fetch`**：**默认引擎在 tool 内**（core 直取 + Readability），`src/web-fetch/` 只负责 provider fallback 选择。执行流：cache → SSRF-guarded fetch → 内容整形（cf-markdown 直通 / HTML 经 `extractReadableContent` → provider fallback → 基本 HTML / JSON pretty）→ **untrusted 包裹** + 有界截断 + 私域内容 temp spill。两个「唯一」：readability 的唯一 registrant 是 `extensions/web-readability`，唯一 fetch provider 是 `extensions/firecrawl`。
- **`web_search`**：候选序 explicit → metadata → configured/auto，且**额外 consult provider auth profile**——用 codex / xai 时无需单独配 web key。provider（brave / perplexity / duckduckgo / exa / tavily 等）都是 extension 插件，经 manifest 的 `webSearchProviders` capability 注册。一个易冲突点：host `web_search` 与 provider-hosted `web_search` 服务工具不能撞车，靠 `allowedHostedToolTypes` 过滤。
- **`link-understanding` 不是 tool**，是入站消息的**链接富化**：先去 markdown-link span、用 `isBlockedHostnameOrIp` 预筛、默认 cap 3 条，然后严格 SSRF fetch + CLI processors，结果写进入站上下文；时机是媒体理解之后、agent dispatch 之前。

**SSRF 只有一个 owner**：`src/infra/net/ssrf.ts`（`SsrFBlockedError` / `isBlockedHostnameOrIp` / `createPinnedDispatcher`）加 guard `fetch-guard.ts`（三档 strict / trusted_env_proxy / trusted_explicit_proxy），web tool 与 link-understanding 共用。一处事实修正：文档里写的 `src/browser/src/infra/net/ssrf.ts` **不存在**——browser 插件只留一个 re-export shim，core owner 就是 `src/infra/net/ssrf.ts`。guard 还会在 debug 开关打开时 lazy-import [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) 的 proxy-capture 做抓取。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) / [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md)
- [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)
