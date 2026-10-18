## Introduction

cc-haha 在通用工具（Bash / FileEdit / WebFetch 等，与 Claude Code 同源）之外另有若干**自有工具**，其中真正可用的只有图像生成与结构化输出两类；另有两个「看似存在、实则不可用」的工具占位。本篇按真实源码梳理，并明确区分**真实实现** / **手写禁用占位** / **`@generated` stub** 三种形态——后两者在公开版均不执行，避免把它们误当功能。

## Tool Status

| 工具 | 名称 | 状态 | 依据 |
| :-- | :-- | :-- | :-- |
| 图像生成 | `ImageGen` | 真实，provider 驱动启用 | `ImageGenTool.ts` |
| 图像编辑 | `ImageEdit` | 真实，provider 驱动启用 | `ImageGenTool.ts` |
| 结构化输出 | `StructuredOutput` | 真实，仅非交互会话 | `SyntheticOutputTool.ts` |
| — | `tungsten` | **手写禁用占位** | `isEnabled()→false` |
| 截屏 | SnipTool | **`@generated` stub** | DCE 后不执行 |

> 三种不可用形态的判别依据不同：`tungsten` 是**手写**占位（文件真实存在、`isEnabled()` 返回 `false`、权限直接 deny）；stub 则是 `scan-missing-imports` 自动生成的 Proxy 占位文件。二者都不提供功能，但前者会出现在工具列表里被模型看见，后者不会。

## Image Generation

`ImageGen`（生成）与 `ImageEdit`（编辑）共用 `generateImages` 后端（`backend.ts`），**是否可用、schema 长什么样都由当前 provider 决定**——模型不能通过参数指定模型或 provider。

- **动态 schema**：`getImageGenerationRuntimeConfig()` 的 `protocol` 若为 `gemini_native`，改用 `GEMINI_IMAGE_ASPECT_RATIOS`，且 Gemini Flash Lite 图像模型只暴露 `resolution: ['1k']`；其余走 OpenAI 兼容的 `DEFAULT_IMAGE_ASPECT_RATIOS`（`aspectRatios.ts` / `modelCapabilities.ts`）。`buildTool` 会快照 getter，故两个工具额外用 `Object.defineProperty` 把 `inputSchema` 的 getter 挂回成品工具。
- **公共字段**：`prompt`、`count`（1–4，同一 prompt 的变体数）、`aspect_ratio`、`resolution`（`1k` / `2k`）、`size`（OpenAI 兼容）、`quality`、`background`、`output_format`（`png` / `jpeg` / `webp`）。
- **三类 provider**：`providerKind` 为 `openai_oauth` / `grok_oauth` / `openai_images`。图像生成**复用 OpenAI Codex 与 Grok 的 OAuth 令牌**——`backend.ts` 直接依赖 `services/openaiAuth`（`ensureFreshOpenAITokens`）与 `services/grokAuth`（`ensureFreshGrokTokens` / `forceRefreshGrokTokens`），即「登录过账号就能生图」，不需另配 API key。
- **权限**：`checkPermissions` **恒定 allow**，图像生成不弹审批；`isEnabled` 仅取决于 provider 是否配置图像能力；`shouldDefer: true` 延迟加载。
- **输出**：`type: 'image_generation_result'`，含 `images[].path`（本地绝对路径）、`mimeType`、可选 `revisedPrompt`，以及 `durationMs`。

**ImageEdit 的路径约束**：编辑需 `referenced_image_paths`（1–3 张，有序），且**只接受本会话中用户提供的图**——`[Image source: ...]` 附件、`@` 附加的文件，或先前 ImageGen 返回的路径。工具提示明确禁止模型臆造、搜索或替换路径，也禁止自己从磁盘读图塞进来；用户指的是一张没有路径的图时应反问要求附加。`ImageGen` 本身则完全没有源图参数，提示要求不得传占位路径。

两个工具的提示都写明：**provider 调用失败不要自动重试**，应解释错误并等用户决定。

## Structured Output

`StructuredOutput`（`SYNTHETIC_OUTPUT_TOOL_NAME`）把最终答复按调用方给定的 JSON Schema 校验后返回，供 SDK / CLI 消费结构化结果。

- **仅非交互会话创建**：`isSyntheticOutputToolEnabled({ isNonInteractiveSession })` 只在该参数为真时返回真——`main.tsx` 据此决定是否创建该工具。创建后 `isEnabled` 恒真，`isReadOnly` 为真、`isOpenWorld` 为假。
- **Ajv 校验**：`createSyntheticOutputTool(jsonSchema)` 用 `new Ajv({ allErrors: true })` 先 `validateSchema` 再 `compile`；schema 非法时返回 Ajv 的诊断文本（如 `data/properties/bugs should be object`），运行结果不匹配则抛 `TelemetrySafeError`（对外只暴露截断后的字段路径，不泄漏原始内容）。
- **WeakMap identity 缓存**：源码注释给出一个与 Workflow 直接相关的实测——Workflow 脚本每次 `agent({ schema })` 传同一 schema 对象引用，一次 run 可达 30–80 次；若无缓存每次都要 `new Ajv()` + `validateSchema()` + `compile()`（约 1.4 ms 的 JIT 代码生成），加 identity 缓存后把 80 次调用的 Ajv 开销从约 110 ms 降到约 4 ms。

## Unavailable Placeholders

**`tungsten`——手写禁用占位**：工具对象真实存在且 `name: 'tungsten'`，但 `isEnabled()` 恒返回 `false`、`checkPermissions` 直接 deny、`maxResultSizeChars` 为 0、`inputSchema` 是空 passthrough；`description` / `prompt` / `call` 的返回文案统一为 "Unavailable in this local recovery build."。`clearSessionsWithTungstenUsage()` 与 `resetInitializationState()` 均为空函数。因 `isEnabled` 为假，正常不会被注入工具列表。

**SnipTool——`@generated` stub**：`src/tools/SnipTool/SnipTool.ts` 仅 1.2 KB，是 `scan-missing-imports` 生成的 Proxy 占位（`export const __stubMissing = true`），对应 ant-internal 的 `feature()` gated 模块，公开版 DCE 后不执行——**cc-haha 没有独立的截屏工具**，取屏幕图像应走 Computer Use 的 `screenshot` / `get_app_state`。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)
- [ComputerUse](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)

## References

- [ImageGenTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ImageGenTool/ImageGenTool.ts)
- [constants.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ImageGenTool/constants.ts)
- [backend.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ImageGenTool/backend.ts)
- [SyntheticOutputTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/SyntheticOutputTool/SyntheticOutputTool.ts)
- [TungstenTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/TungstenTool/TungstenTool.ts)
- [SnipTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/SnipTool/SnipTool.ts)