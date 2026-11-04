## Introduction

AgentScope 自带一套完整 RAG 实现（`rag/`）——纯算法层，可被完全独立使用；托管的那套在服务层（`app/rag/knowledge_base_manager/`）。本分册从主干笔记拆出，保留 v2.0.8 源码事实。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)，通用范式见 [RAG](/docs/CS/AI/RAG.md)。

## RAG Subsystem

AgentScope 自带一套完整的 RAG 实现（`rag/`），和本库 [RAG](/docs/CS/AI/RAG.md) 里说的通用范式对得上，但有几个选择值得单独记。

### Data Flow and Section Boundaries

```
raw file → ParserBase.parse() → [Section] → ChunkerBase.chunk() → [Chunk]
        → embed → VectorRecord → VectorStoreBase.insert() → collection
```

`Section`（`rag/_document.py`）与 `Chunk` 都是纯内存瞬态对象，不单独持久化。`Section` 携带 parser 写入的 `metadata`（PDF 的 `{"page": 3}`、PPTX 的 `{"slide": 2}`、Excel 的 `{"sheet": "Q3 Sales"}`），并逐字透传给 chunk。

`Chunk` 比 `Section` 多两个字段：`chunk_index`（**文档内**跨 Section 连续编号）和 `total_chunks`。这两个字段存在的唯一目的是**检索期的上下文扩窗**——拿到命中 chunk 后按 `±1` 找回邻居。

**Section 是硬边界**：确认所有切分策略保证绝不跨 Section 拼接（`_chunker/_base.py`）。这样页码、幻灯片号这类结构元数据不会泄漏到错误的 chunk 上。

### Parsers, Chunker, Vector Stores

六个 parser继承 `ParserBase`（`_parser/_base.py`，唯一抽象方法 `async def parse(file: bytes | str, filename: str) -> list[Section]`）：`TextParser`（吞掉 text/markdown / html 等 8 种媒体类型，**不推断内部边界**，整个文件一个 Section）、`PDFParser`（每页一个 Section）、`WordParser`、`ExcelParser`、`PPTParser`（每页一张幻灯片）、`ImageParser`。

`file` 参数的联合类型是三态的：`bytes` 是原始负载；`str` 对二进制 parser 是**文件路径**，对 `TextParser` 则是运行时消歧（磁盘存在就按 encoding 解码，否则当已解码文本）。

切分策略**只有一种**——`ApproxTokenChunker`（`chunker_type = "approx_token"`），参数 `chunk_size=512` / `overlap=50`，`overlap >= chunk_size` 直接报错。token 数用 `len(text.encode("utf-8")) // 4` 近似，刻意避免引入 tokenizer 依赖。`DataBlock` 内容原样透传为单 chunk，永不被切片。

向量库四个：`QdrantStore` / `MongoDBStore` / `MilvusLiteStore` / `ElasticsearchStore`。`VectorStoreBase` 的 `score` 语义统一为**越大越好**——距离型后端取负数。载荷模型刻意设计成：不给 `Chunk` 加 `embedding` / `score` 字段（保持 `Chunk` 语义稳定），而把这些放进 `VectorRecord`（= vector + document_id + chunk）和 `VectorSearchResult`（多一个 score）。

### KnowledgeBase and Its Boundary

`KnowledgeBase`（`rag/_knowledge.py`）是运行时句柄，embedding 模型在构造时注入、与 vector store 配对：

```python
KnowledgeBase(
    name=..., description=...,
    embedding_model=EmbeddingModelBase,
    vector_store=VectorStoreBase,
    collection=...,
    metadata_filter=None,
)

async def search(self, queries: list[str | TextBlock | DataBlock],
                 top_k: int = 5, score_threshold: float | None = None
                ) -> list[VectorSearchResult]
```

注意方法名是 **`search` 不是 `retrieve`**。多 query 一次性 batch embed 后并发检索，去重键是 `(document_id, chunk_index)` 而非 block UUID——注释说明 UUID 在重建索引后会变。`supports_multimodal` 为假的模型会**静默丢弃** DataBlock query。插入时元数据优先级是 `metadata_filter > chunk 自身 metadata > document_metadata`，这是安全边界，防止 buggy parser 把记录写进别的 scope。

**一个重要的职责边界**：Parser 和 Chunker **不挂在 `KnowledgeBase` 上**。它只吃已经切好的 `list[Chunk]`，真正的解析-入库编排（鉴权、维度策略、blob 存储、索引 worker）在 `app/rag/knowledge_base_manager/`。也就是说 `rag/` 是**纯算法层**，可被完全独立使用；托管的那一套在服务层。

### End-to-End Example (Library Mode, No Service)

`rag/` 完全可以脱离 FastAPI 独立跑。下面是把上面的 parser/chunker/embedding/store 串起来的最小切片（精简自仓库 `examples/rag/index_and_search.py`，全部 API 取 v2.0.8）：

```python
import asyncio
from agentscope.credential import DashScopeCredential
from agentscope.embedding import DashScopeEmbeddingModel
from agentscope.message import TextBlock
from agentscope.rag import (
    ApproxTokenChunker, KnowledgeBase, QdrantStore, TextParser,
)

async def main() -> None:
    # 1. 四个构建块 —— 也是 service 模式 create_app 内部用的同一套
    embedding = DashScopeEmbeddingModel(
        credential=DashScopeCredential(api_key="sk-..."),
        model="text-embedding-v4", dimensions=1024,
    )
    parser = TextParser()
    chunker = ApproxTokenChunker(chunk_size=256, overlap=32)
    store = QdrantStore(location=":memory:")   # 换 url= 即远端 Qdrant

    async with store:                            # 进入即开 client，退出即关
        kb = KnowledgeBase(
            name="demo-kb", description="玩具语料",
            embedding_model=embedding, vector_store=store, collection="demo-kb",
        )
        # 2. 入库：bytes → Section → Chunk → embed + 写 collection
        sections = await parser.parse(b"# AgentScope\n多智能体框架。", "as.md")
        chunks = await chunker.chunk(sections)
        doc_id = await kb.insert_document(chunks, document_metadata={"f": "as.md"})

        # 3. 检索：多 query 批量 embed 后并发查，去重键 (document_id, chunk_index)
        results = await kb.search(queries=["什么是多智能体框架？"], top_k=3)
        for r in results:
            text = r.chunk.content.text if isinstance(r.chunk.content, TextBlock) else "<非文本>"
            print(f"score={r.score:.4f} doc={r.document_id} :: {text[:80]}")

asyncio.run(main())
```

要点对照上文：① `QdrantStore` 是 async context manager，进入才开连接；② `KnowledgeBase` 构造**零 I/O**，collection 在首次 `insert_document` 时惰性创建，全新部署无需手动建库；③ `insert_document(chunks, document_id?, document_metadata?)` 返回 `document_id`，`metadata_filter > chunk 自身 metadata > document_metadata` 的优先级在这里生效——传入的 `document_metadata` 会被强制打在每个 chunk 上；④ `search` 返回的 `VectorSearchResult` 多一个 `score`（`Chunk` 本身不含 score，保持语义稳定），`score` 越大越相关。

### RAGMiddleware: Two Modes

把 RAG 接进主循环的是 `middleware/_rag.py` 里的 `RAGMiddleware`，两种模式：

- **`agentic`**（默认）——通过 `list_tools()` 暴露单个 `SearchKnowledgeTool`，让 LLM 自己决定何时检索
- **`static`**——跨 hook 协作：`on_reply` 先把输入 block 缓存起来，`on_reasoning` 再取用（因为到那时输入可能已被 `state.context` 消费掉）；只在 `cur_iter == 0` 触发一次，避免每轮工具调用都重新 embed

可选接入 `rerank_model` 做重排，但失败时保留向量序（best-effort）。`hint_template` 和 `rerank_prompt` 用 `SkipJsonSchema` 对 UI 隐藏——它们属于中间件的 prompt 契约，不该每次会话被改。



## Source Facts

下面把上面的叙事逐条落到源码精确事实（本地仓库 `/Users/robin/Projects/agentscope`，commit `c7d8e31`，v2.0.8）。路径均相对 `src/agentscope/`。

### Section and Chunk

`Section` 与 `Chunk` 都是 `pydantic.BaseModel`，仅作各阶段瞬态内存载体、自身不持久化——模块 docstring 写明「Neither structure is persisted on its own」（`rag/_document.py:19-22`），持久化发生在 `VectorRecord` / `KnowledgeDocumentRecord` 层。

| 类 | 字段 | 行号 | 说明 |
| :--- | :--- | :--- | :--- |
| `Section` | `content: TextBlock \| DataBlock` | `rag/_document.py:48` | 文本走 `TextBlock`；图片/视频等多模态走 `DataBlock` |
| | `source: str` | `:52` | 源文件名，`state.context` 之后仍透传到 Chunk 与向量库 metadata 供引用 |
| | `metadata: dict` | `:57` | parser 写入的格式元数据（PDF `{"page": 3}` 等），逐字透传 |
| `Chunk` | `content` / `source` | `:80` / `:84` | 与 Section 同语义 |
| | `chunk_index: int` | `:88` | **文档内 0 基连续编号**，跨 Section 顺排，服务于检索期 ±1 扩窗 |
| | `total_chunks: int` | `:94` | 同文件切出的 chunk 总数，判定命中是否近首尾、约束扩窗范围 |
| | `metadata: dict` | `:100` | 继承父 Section |

`Chunk` 比 `Section` 多出的两个字段是 `chunk_index` 与 `total_chunks`（`:88 / :94`），源码注释写明其唯一用途是「expand context around a hit at query time」（`:76-78`）。`Section` 是硬边界——`ChunkerBase` 保证任何 `Chunk` 只来自**单一** Section（见 `### Chunking`），使页码、幻灯片号等结构元数据不会泄漏到错误 chunk（`rag/_document.py:9-13`）。

### Parsers

`ParserBase`（`rag/_parser/_base.py:22`）只声明一个抽象方法：

```python
@abstractmethod
async def parse(self, file: bytes | str, filename: str) -> list[Section]
```

`file` 是三态联合类型（`:81-92`）：`bytes` 为原始负载；`str` 对二进制 parser（PDF/PPT/image）是**文件路径**，对 `TextParser` 则运行时消歧（磁盘存在就按 `encoding` 解码，否则当已解码文本，`rag/_parser/_text.py:97-109`）。每个子类还声明 `supported_media_types`（IANA 媒体类型，供服务层按类型路由，`:37`）与 `supported_extensions()`（`:43`，供前端 `<input accept>` 与文件名守卫，但不参与媒体类型路由）。

六个具体 parser（导出见 `rag/_parser/__init__.py:12-20`）：

| Parser | 文件:行 | Section 粒度 |
| :--- | :--- | :--- |
| `TextParser` | `_text.py:10` | 整个文件**一个** Section，不推断内部边界；承接 8 种 IANA 类型 `text/plain, text/markdown, text/csv, text/html, text/x-rst, application/json, application/xml, application/x-yaml`（`_text.py:23-32`） |
| `PDFParser` | `_pdf.py:16` | **每页一个** Section，元数据 `{"page": idx}`（idx 从 1 起，`_pdf.py:83-91`）；空页也产出 Section 以保持页码对应 |
| `WordParser` | `_word.py` | 待确认（源码未逐行核对粒度） |
| `ExcelParser` | `_excel.py` | 待确认（源码未逐行核对粒度） |
| `PPTParser` | `_ppt.py` | 待确认（源码未逐行核对粒度） |
| `ImageParser` | `_image.py` | 待确认（源码未逐行核对粒度） |

`ParserBase` docstring 强调 parser **只切自然边界、不做切块**（`:10-14`）——长文本整段留在 Section 里，切块留给 Chunker。

### Chunking

`ChunkerBase`（`rag/_chunker/_base.py:26`）格式无关，唯一抽象方法 `chunk(sections) -> list[Chunk]`（`:74`）。它用文档字符串固化五条不变式（`:37-50`）：① 绝不跨 Section 合并；② `DataBlock` 原样透传为单 chunk、永不被切片；③ `chunk_index` 从 `0` 连续到 `total_chunks-1`；④ 每个 Chunk 的 `total_chunks` 一致；⑤ `source`/`metadata` 从父 Section 拷贝。

实现层**只有一种**策略 `ApproxTokenChunker`（`rag/_chunker/_approx_token_chunker.py:20`，`chunker_type = "approx_token"`）：

- 参数 `chunk_size: int = 512`、`overlap: int = 50`，`overlap >= chunk_size` 由 `model_validator` 直接报错（`:42-67`）。
- token 数近似为 `len(text.encode("utf-8")) // 4`（`:238`），刻意不引入 tokenizer 依赖。
- 实际切片在 `_split_text`（`:172`）：先算每个字符的 UTF-8 累计字节偏移 `byte_offsets`，把 `chunk_size`/`overlap` 折算成 `chunk_size*4`/`overlap*4` 字节预算，用 `bisect_right` 找字节边界，`end = max(end, start + 1)` 保证每次都有进展（即便某字符 UTF-8 编码本身就超预算，`:206-208`）；重叠靠回退 `overlap_bytes` 字节实现（`:214-222`）。
- 最终在 `chunk()` 末尾统一重编号 `chunk_index` / `total_chunks`（`:166-168`）——「连续编号」是 chunker 收尾的保证，而非 parser 的产出。

### Vector Stores

向量库抽象 `VectorStoreBase`（`rag/_vdb/_vector_store.py:104`）是单例共享连接（进程级，由 app lifespan 经 async context manager 管理，`:5-18`）。抽象方法（`@abstractmethod`）：`create_collection:145`、`delete_collection:164`、`has_collection:173`、`insert:189`、`delete:205`、`search:230`、`list_documents:268`。注意 `list_chunks:302` **不是**抽象方法——它作为非抽象默认实现抛 `NotImplementedError`（`:357`），应用层据此映射 HTTP 501、隐藏分块浏览 UI（`:321-326`）。

三种载荷包装模型（均 `pydantic.BaseModel`）刻意**不**给 `Chunk` 增字段以保持其语义稳定：

- `VectorRecord`（`:28`）= `vector: list[float]`（`:39`）+ `document_id: str`（`:42`）+ `chunk: Chunk`（`:49`）
- `VectorSearchResult`（`:53`）= `score: float`（`:62`）+ `document_id`（`:68`）+ `chunk`（`:74`）
- `DocumentSummary`（`:78`）= `document_id` + `source` + `chunk_count` + `metadata`

`score` 语义统一为**越大越相关**（`:62-66`）：距离型后端（如 ES / Milvus 的距离）必须取负数后再返回（`:261`）。四个内置后端（`rag/_vdb/__init__.py:10-13`）：

| 类 | 文件:行 |
| :--- | :--- |
| `QdrantStore` | `_qdrant.py:31` |
| `MongoDBStore` | `_mongodb.py:31` |
| `MilvusLiteStore` | `_milvus_lite.py:26` |
| `ElasticsearchStore` | `_elasticsearch.py:20` |

抽象类 docstring 以「Chroma / Milvus / Qdrant / FAISS」举例（`:108`），但 v2.0.8 实际随包发布的只有上述四个后端。

### Embedding

embedding 模型基类 `EmbeddingModelBase`（`embedding/_embedding_base.py:34`）与 chat model 同构：`dimensions: int`（`:78`，**必填一级字段**——向量维度是契约而非可调旋钮，`:57-84`）、`context_size` / `batch_size` / `max_retries` / `retry_delay`、`supports_multimodal: bool = False`（`:98`）。公开 `__call__`（`:197`）按 `batch_size` 切批后 `asyncio.gather` **并发**调用、每批带重试；子类只需实现单批的 `_call_api`（`:363`）。`TextBlock` 输入在 `__call__` 入口即拆成 `.text`（`:234-237`），故 `_call_api` 只见 `str` / `DataBlock`。

### KnowledgeBase Operations

`KnowledgeBase`（`rag/_knowledge.py:44`）是单个知识库的运行时句柄，构造**零 I/O**（`:49`），embedding 模型与 vector store 在构造时注入配对。它对外只暴露四个文档操作（模块 docstring `:7-9`）：`search:190`、`insert_document:279`、`delete_document:358`、`list_documents:371`，外加 `list_chunks:387`。

- **惰性建库**：`ensure_collection:160` 幂等且**带记忆化**（`_collection_ready` 标志，`:130`、`:177-184`），首次操作才按 `embedding_model.dimensions` 建 collection，全新部署开箱即用。
- **search 数据流**：多 query 一次性 `self._embedding_model(queries)` 批量 embed（`:238`）→ `asyncio.gather` 并发对每个 query 调 `vector_store.search`（`:240-250`）→ 按 `(document_id, chunk_index)` 去重保留最高分（`:252-266`，注释说明该键在重建索引后仍稳定、而 block UUID 会失效）→ 按 `score` 降序截断 `top_k`（`:268-273`）。`supports_multimodal` 为假的模型先**静默丢弃** `DataBlock` query（`:232-235`）。
- **insert_document 元数据优先级**：合并顺序 `{**document_metadata, **chunk.metadata, **metadata_filter}`（`:330-335`）——`metadata_filter` 因排最后而**最高优先**，形成安全边界：即便 parser 有 bug 也写不进别的 scope（`:25-31`、`:107-119`）。
- **向量数校验**：embed 返回的向量数与 chunk 数不符直接 `RuntimeError`（`:341-345`）。

### RAGMiddleware Wiring

`RAGMiddleware`（`middleware/_rag.py:626`）包一组 `KnowledgeBase` 句柄（各自可带不同 embedding 模型），但**不拥有**这些资源、只编排检索（`:4-8`、`629-632`）；文档入库（解析/切块/embed/插入）不属于它（`:27-30`）。

`mode: Literal["static", "agentic"]`，**默认 `"agentic"`**（`:662-669`）。可配 `top_k`（默认 5，`:671`）、`score_threshold`（`:682`）、`rerank_candidate_k`（上限 `_MAX_CANDIDATE_K = 50`，`:80`）、`emit_hint_event`（默认 True，`:704`）、`persist_hint`（默认 False，`:713`）；`hint_template` 与 `rerank_prompt` 用 `SkipJsonSchema` 对 UI 隐藏（`:723` / `:738`）。

- **agentic 模式**：`list_tools()` 仅在 `mode == "agentic"` 时返回单个 `search_knowledge` 工具（`_SearchKnowledgeTool`，`name="search_knowledge"`、`is_read_only=True`，`:139-143`、`:842-853`），由 LLM 自行决定何时、查哪些库（`knowledge_bases` 参数按已装库名收窄 enum，`:236-255`）。
- **static 模式**：跨 hook 协作——`on_reply`（`:859`）先把 reply 输入 deepcopy 后缓存进 `self._cached_inputs`（因为到 `on_reasoning` 时输入可能已被 `state.context` 消费掉，`:867-871`），`on_reasoning`（`:929`）仅在 `agent.state.cur_iter == 0`（`967`）做一次性检索，结果包成 `HintBlock` 经 `agent.state.append_context` 注入（`:993`），可选地发 `HintBlockEvent` 给前端（`:994-1000`）；若不 `persist_hint`，该 block 在本次 reasoning 后立即按 id 移除（`:1006-1015`），避免每轮工具调用都重 embed。
- **rerank 是 best-effort**：接了 `rerank_model` 时检索放宽到 `rerank_candidate_k` 个候选、由 chat model 挑最终 `top_k`（`:405-445`）；rerank 失败就回退向量序（`:431-445`）。跨不同 embedding 模型的分数不可严格比较，合并仅按原始 `score` 排序（`:371-376`）。



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [RAG](/docs/CS/AI/RAG.md)

## References

- `src/agentscope/rag/_document.py` / `_parser/` / `_chunker/` / `_knowledge.py`
- `src/agentscope/middleware/_rag.py`
