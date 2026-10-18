## Introduction

cc-haha 的核心卖点之一是 **BYO 模型（Bring Your Own Model）**：不锁定任何厂商。模型清单与供应商由**服务端配置驱动**（不是硬编码在客户端），客户端 `modelsApi` 只负责向本地服务端请求 `/api/models`、当前 provider、目录与 effort 等级（`desktop/src/api/models.ts:9-34`）。这与 [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md) 的「模型无关」路线一致，但 cc-haha 额外内置了多家厂商的登录与预设。

> [!WARNING]
> 模型服务费用由对应供应商计收；本地模型免费但需本机运行推理。

## Connection Modes

| 方式 | 说明 |
| :--- | :--- |
| 账号登录 | 直接登录 Claude / ChatGPT / Grok 账号 |
| 内置预设 | DeepSeek、Kimi、Zhipu GLM（智谱）等一键预设 |
| 本地模型 | 指向 LM Studio 或 Ollama 运行的本地端点，零费用 |
| 自定义端点 | 任意 OpenAI 兼容端点 |

这些预置供应商（Claude / ChatGPT / Grok / DeepSeek / Kimi / Zhipu / 本地 LM Studio / Ollama / OpenAI 兼容）来自服务端 `ProviderService`，在已抓取的客户端切片里只见到 `provider:{id,name}` 形态——具体预置清单以服务端为准。

## Image Generation

聊天内直接生成 / 编辑图像：登录 ChatGPT 或 Grok 即用，或接入任意 OpenAI 兼容 Images API。

## Local Models

本地模型经 LM Studio / Ollama 暴露的端点接入；需本机已启动对应服务并配置端口。这带来**零 API 费用 + 数据不出本机**的双重收益，与 cc-haha 的 local-first 定位一致。

## Effort Levels

模型还暴露 **effort 等级**（`/api/effort` 取可用列表与当前值，`models.ts:27-33`），与 Anthropic 的思考 / 努力预算概念对应。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)

## References

- [cc-haha 文档：Connect a model](https://cchaha.ai/en/start/models)
- [models.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/api/models.ts)
