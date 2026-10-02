## Introduction

RAGFlow 是 InfiniFlow 出品、**Apache-2.0** 许可的开源 RAG 引擎（GitHub 星标约 8 万+）。它的定位与 Dify 那类"通用 LLM 应用平台"不同：**它是一个专注做「深度文档理解」的 RAG 引擎**，把文档解析当成第一性问题而不是预处理的一步。

它的差异化在 DeepDoc 这一层：**视觉模型 + 版面算法去理解页面结构**，而不是把 PDF 当成一坨文本按字数切。因此它的主场是——扫描件、带表格的财报、多栏排版、PPT、版式复杂的合同等"脏文档"。如果你的语料全是干净的 Markdown 或结构良好的 HTML，这层解析优势就用不上，反而白付了那份资源开销（见下文部署要求）。

一句话：**RAG 的效果上限由切分质量决定，RAGFlow 卖的就是切分质量。**

## DeepDoc：它到底多做了什么

朴素切分器的失败模式很典型：表格被按行切开后，"Q3 营收是多少"能把数字检出来，却丢掉了说明这个数字含义的列名；PPT 丢失视觉层级；扫描件干脆是空的。DeepDoc 用三段式处理解决：

| 环节 | 做什么 | 解决什么失败 |
|------|--------|--------------|
| **OCR** | 从扫描件与低质量 PDF 中提取文字 | 扫描件检索不到内容 |
| **TSR**（表格结构识别） | 识别表格边界、表头与单元格关系后再切 | 表格行列错位、数字失去列名上下文 |
| **DLR**（版面识别） | 区分标题、正文、图注、页脚、脚注 | 图注与上文分离、标题层级丢失 |

产出不是裸文本，而是**带版面元数据的结构化内容**——切分器因此知道不要把表头和它的数据行拆开、不要把图注和它描述的段落分开。此外它在生成前还有一道多趟校验，确认召回的 chunk 真的支持即将生成的答案，用于压低"看似合理实则编造"的引用。

## 关键机制

- **13 种内置切分模板**：通用、问答、简历、手册、表格、论文、书籍、法律、演示文稿、图片、整篇、标签，以及 v0.21.0 新增的"Ingestion Pipeline"。模板是按文档版式调过的，选对模板比调参更有效。
- **chunk 在 UI 里可见可编辑**：答错了能一路追溯到导致它的那个 chunk——这是"回答要能对合规/法务解释得清、可追溯到源 chunk"的前提。
- **答案带引用**：每个结论可回溯到源 chunk 与页码。
- ⚠️ **embedding 模型一旦有 chunk 就不可更换**：这是最容易踩的一次性决定，换模型意味着重建知识库，选型阶段就想清楚。

## 2026 年的版本进展

| 版本 | 时间 | 主要变化 |
|------|------|----------|
| v0.21.0 | 2025 | 新增 Ingestion Pipeline 切分模板 |
| v0.25.0 | 2026-04 | Agentic 工作流 + **MCP Server**、Elasticsearch 9.x（原 8.x）、MinIO 镜像改用 `pgsty/minio` |
| v0.25.1 | 2026-04-29 | 大 PDF 懒加载、RESTful API 统一、DeepSeek v4 支持 |
| v0.26.x | 2026 年中 | 当前稳定线（v0.26.4） |

近期还在稳定的方向：Agentic 工作流与 Agent 记忆、**基于 gVisor 沙箱的代码执行器**、以及飞书 / Discord / Telegram / Line 等对话渠道。也就是说它已经从"纯 RAG"往"带执行的 RAG 应用平台"走了一步。

## 部署：门槛明显高于同类

官方 README 给出的最低要求：

| 项 | 要求 |
|----|------|
| CPU | ≥ 4 核 |
| 内存 | ≥ 16 GB |
| 磁盘 | ≥ 50 GB |
| Docker | ≥ 24.0.0，Compose ≥ v2.26.1 |
| Linux | `vm.max_map_count` ≥ 262144（ES 的内存锁定行为决定这 16 GB 底线） |
| 架构 | 官方预构建镜像**仅 x86**，ARM64 需自行构建 |
| gVisor | 只有要用到代码执行器（沙箱）时才需要装 |

```shell
sudo sysctl -w vm.max_map_count=262144
git clone https://github.com/infiniflow/ragflow.git
cd ragflow/docker
docker compose --profile elasticsearch,cpu up -d
# 默认 HTTP 端口 80，本机访问 http://localhost
```

两个实操提醒：

1. **先改默认密码**：`.env` 里 `ELASTIC_PASSWORD`、`MYSQL_PASSWORD`、`MINIO_PASSWORD` 出厂就是弱口令，启动前必须用 `openssl rand -hex 32` 之类的方式换掉。
2. **固定在稳定 tag**：`:nightly` 之类的标签跟着每日构建走而不是稳定发布，请 `git checkout v0.26.x` 后再起；升级前先读 release notes（尤其 0.24 → 0.25 这种带 MinIO 替换的版本，桶数据要手动迁移）。

资源吃紧时可以把文档引擎换成更轻的 `infinity`，代价是大规模场景的成熟度不如 Elasticsearch。另外它默认要用 GPU 才能跑得动 DeepDoc 的视觉任务（CPU 也能跑，只是慢），处理大量扫描件时应规划 GPU。

## 怎么选

| 情况 | 建议 |
|------|------|
| 语料是扫描件、带复杂表格、PPT、多栏排版的"脏文档" | **RAGFlow**，解析层就是它的护城河 |
| 需要给合规/法务/客户出示可追溯引用 | **RAGFlow**（chunk 可见可编辑 + 答案带引用） |
| 语料干净，还要通用编排（多应用类型、插件市场、发布多渠道） | [Dify](/docs/CS/AI/LLM/Dify.md) |
| 只要一个轻量的知识库问答，机器资源有限 | FastGPT / AnythingLLM（4C16G 的门槛不是每台机器都给得起） |
| 只想快速验证一个 RAG 想法 | [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md) 拉条 RAG 流程更快 |

一句话：**RAGFlow 是"为了文档质量可以接受更高部署成本"时的答案；如果回答质量的瓶颈根本不在解析而在产品编排，它就不是那个瓶颈的解药。**

## Links

- [RAG](/docs/CS/AI/RAG.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md)
- [Coze](/docs/CS/AI/LLM/Coze.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)
- [MCP](/docs/CS/AI/LLM/MCP.md)
- [AI](/docs/CS/AI/AI.md)

## References

1. [RAGFlow 官网](https://ragflow.io/)
2. [RAGFlow 开源仓库](https://github.com/infiniflow/ragflow)
3. [RAGFlow 官方文档](https://ragflow.io/docs/dev/)
4. [RAGFlow: Self-Host a Deep-Document RAG Engine（含版本差异与 .env 加固清单）](https://dev.to/jangwook_kim_e31e7291ad98/ragflow-self-host-a-deep-document-rag-engine-3nf7)
5. [RAGFlow Review 2026: DeepDoc RAG Explained](https://swarm.beetlix.com/reviews/ragflow-review-2026)
