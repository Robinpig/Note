## Introduction

AgentScope 自带一套完整 RAG 实现（`rag/`）——纯算法层，可被完全独立使用；托管的那套在服务层（`app/rag/knowledge_base_manager/`）。本分册从主干笔记拆出，v2.0.11 逐文件重核后四层结构与结论几乎逐一吻合，是七个旧分册里唯一**无需结构性改写**的一册；唯一变化是 `rag/_parser/` 下多了 `_utils.py`。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)，通用范式见 [RAG](/docs/CS/AI/RAG.md)。

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

`rag/` 完全可以脱离 FastAPI 独立跑。下面是把上面的 parser/chunker/embedding/store 串起来的最小切片（精简自仓库 `examples/rag/index_and_search.py`，全部 API 取 v2.0.11）：

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

下面把上面的叙事逐条落到真实源码片段（基线 tag `v2.0.11`）。路径均相对 `src/agentscope/`，不依赖仓库被克隆到哪台机器的哪个目录；片段均从该 tag 的源码原样摘取。

### Section and Chunk

`Section` 与 `Chunk` 都是 `pydantic.BaseModel`，仅作各阶段瞬态内存载体、自身不持久化——模块 docstring 写明「Neither structure is persisted on its own」，持久化发生在 `VectorRecord` / `KnowledgeDocumentRecord` 层；同一段 docstring 也把「Section 是硬边界、Chunk 是最终入库单元」写死。`rag/_document.py` 的模块 docstring 原文：

```python
"""Data structures used in the RAG indexing pipeline.

The indexing pipeline has two stages, each producing its own
structured output:

1. :class:`Section` — produced by a :class:`ParserBase` from a raw
   file.  Each ``Section`` represents one "natural boundary" of the
   source (a PDF page, a PPTX slide, an embedded image, a Markdown
   heading section, etc.).  A ``Chunker`` never combines content
   across two ``Section`` instances, so ``Section`` is also a hard
   boundary that prevents leakage of format-specific structure into
   downstream chunks.

2. :class:`Chunk` — produced by a :class:`ChunkerBase` from one or
   more ``Section`` instances.  Each ``Chunk`` is the final unit
   that gets embedded and inserted into the vector store.

Neither structure is persisted on its own — they are transient
in-memory carriers between pipeline stages.  Persistence happens at
the :class:`~agentscope.rag.VectorRecord` and
``KnowledgeDocumentRecord`` layers.
"""
```

两个类的字段声明（节选自 `rag/_document.py` 各自的类体内，表格结论见下）。`Section` 的三个字段：

```python
    content: TextBlock | DataBlock
    """The section content.  Text sections use :class:`TextBlock`;
    multimodal sections (images, video, etc.) use :class:`DataBlock`."""

    source: str
    """The source filename (e.g. ``"report.pdf"``).  Carried through
    to every downstream :class:`Chunk` and into the vector store
    metadata for citation / display."""

    metadata: dict[str, Any] = Field(default_factory=dict)
```

`Chunk` 多出的 `chunk_index` / `total_chunks` 及其用途，注释原话即为「expand context around a hit」：

```python
    chunk_index: int
    """The 0-based index of this chunk **within the document**.
    Sequential across all sections of the same source file.  Used to
    locate neighbouring chunks for "context expansion" at query time.
    """

    total_chunks: int
    """The total number of chunks produced from the same source file.
    Together with :attr:`chunk_index` lets callers know whether a hit
    is near the start / end of the document, and bounds the
    expansion range."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Format-specific metadata inherited from the parent
    :class:`Section`.  See :attr:`Section.metadata`."""
```

| 类 | 字段 | 说明 |
| :--- | :--- | :--- |
| `Section` | `content: TextBlock \| DataBlock` | 文本走 `TextBlock`；图片/视频等多模态走 `DataBlock` |
| | `source: str` | 源文件名，`state.context` 之后仍透传到 Chunk 与向量库 metadata 供引用 |
| | `metadata: dict` | parser 写入的格式元数据（PDF `{"page": 3}` 等），逐字透传 |
| `Chunk` | `content` / `source` | 与 Section 同语义 |
| | `chunk_index: int` | **文档内 0 基连续编号**，跨 Section 顺排，服务于检索期 ±1 扩窗 |
| | `total_chunks: int` | 同文件切出的 chunk 总数，判定命中是否近首尾、约束扩窗范围 |
| | `metadata: dict` | 继承父 Section |

`Chunk` 比 `Section` 多出的两个字段是 `chunk_index` 与 `total_chunks`，源码注释写明其唯一用途是「expand context around a hit at query time」。`Section` 是硬边界——`ChunkerBase` 保证任何 `Chunk` 只来自**单一** Section（见 `### Chunking`），使页码、幻灯片号等结构元数据不会泄漏到错误 chunk。

### Parsers

`ParserBase`（`rag/_parser/_base.py`）只声明一个抽象方法，原样签名是多行形式：

```python
    @abstractmethod
    async def parse(
        self,
        file: bytes | str,
        filename: str,
    ) -> list[Section]:
```

`file` 是三态联合类型：`bytes` 为原始负载；`str` 对二进制 parser（PDF/PPT/image）是**文件路径**，对 `TextParser` 则运行时消歧（磁盘存在就按 `encoding` 解码，否则当已解码文本）。这一三态语义写在 `parse` 的 docstring 里：

```python
        The ``file`` argument is a union covering the three call sites
        a parser sees in practice:

        - ``bytes`` — the raw payload, as handed in by HTTP uploads
          and blob-store reads.
        - ``str`` for binary parsers (PDF, PPT, image, …) — a
          **filesystem path** to the file to read.  The parser opens
          the path itself; callers do not need to read the bytes first.
        - ``str`` for :class:`TextParser` — disambiguated at runtime:
          if the string names an existing file on disk it is treated
          as a path and the file is decoded with the configured
          encoding; otherwise it is treated as pre-decoded text.
```

`TextParser` 的运行时消歧落在 `rag/_parser/_text.py` 的这段分支（`os.path.isfile` 命中就按 encoding 解码，否则直接当已解码文本）：

```python
        if isinstance(file, str):
            if os.path.isfile(file):
                with open(file, "rb") as fp:
                    raw = fp.read()
                try:
                    text = raw.decode(self.encoding)
                except UnicodeDecodeError as e:
                    raise ValueError(
                        f"Failed to decode {filename!r} as "
                        f"{self.encoding!r}: {e}",
                    ) from e
            else:
                text = file
```

每个子类还声明 `supported_media_types`（IANA 媒体类型，供服务层按类型路由）与 `supported_extensions()`（供前端 `<input accept>` 与文件名守卫，但不参与媒体类型路由）。两者在 `rag/_parser/_base.py` 的声明：

```python
    supported_media_types: list[str]
    """Standard IANA media types (RFC 6838) this parser handles,
    e.g. ``["application/pdf"]`` or
    ``["text/plain", "text/markdown"]``.  Used by the
    KnowledgeBaseManager to select a parser for an uploaded file."""

    @classmethod
    def supported_extensions(cls) -> list[str]:
```

六个具体 parser 由 `rag/_parser/__init__.py` 的 `__all__` 一次导出：

```python
__all__ = [
    "ParserBase",
    "PDFParser",
    "PPTParser",
    "ImageParser",
    "TextParser",
    "WordParser",
    "ExcelParser",
]
```

| Parser | 文件 | Section 粒度 |
| :--- | :--- | :--- |
| `TextParser` | `_text.py` | 整个文件**一个** Section，不推断内部边界；承接 8 种 IANA 类型 `text/plain, text/markdown, text/csv, text/html, text/x-rst, application/json, application/xml, application/x-yaml` |
| `PDFParser` | `_pdf.py` | **每页一个** Section，元数据 `{"page": idx}`（idx 从 1 起）；空页也产出 Section 以保持页码对应 |
| `WordParser` | `_word.py` | 待确认（源码未逐行核对粒度） |
| `ExcelParser` | `_excel.py` | 待确认（源码未逐行核对粒度） |
| `PPTParser` | `_ppt.py` | 待确认（源码未逐行核对粒度） |
| `ImageParser` | `_image.py` | 待确认（源码未逐行核对粒度） |

`TextParser` 承接的 8 种 IANA 类型，就是 `rag/_parser/_text.py` 里这个类属性：

```python
    supported_media_types: list[str] = [
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "text/x-rst",
        "application/json",
        "application/xml",
        "application/x-yaml",
    ]
```

`PDFParser`「每页一个 Section、`page` 从 1 起」由 `rag/_parser/_pdf.py` 的 `enumerate(..., start=1)` 直接给出：

```python
            sections: list[Section] = []
            for page_idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                sections.append(
                    Section(
                        content=TextBlock(text=text),
                        source=filename,
                        metadata={"page": page_idx},
                    ),
                )
```

`ParserBase` 的模块 docstring 强调 parser **只切自然边界、不做切块**——长文本整段留在 Section 里，切块留给 Chunker：

```python
Parsers **do not chunk text**.  Long text is left intact inside the
Section; splitting happens later in a
:class:`~agentscope.rag.ChunkerBase`.  Parsers also do not need to
worry about output size — only about preserving the structural
boundaries that downstream consumers must not cross.
```

### Chunking

`ChunkerBase`（`rag/_chunker/_base.py`）格式无关，唯一抽象方法 `chunk(sections) -> list[Chunk]`，原样签名：

```python
    @abstractmethod
    async def chunk(self, sections: list[Section]) -> list[Chunk]:
```

它用文档字符串固化六条不变式：① 绝不跨 Section 合并；② `DataBlock` 原样透传为单 chunk、永不被切片；③ 空文本 / 纯空白的 Section 不产生 Chunk；④ `chunk_index` 从 `0` 连续到 `total_chunks-1`；⑤ 每个 Chunk 的 `total_chunks` 一致；⑥ `source`/`metadata` 从父 Section 拷贝。`rag/_chunker/_base.py` 的类 docstring 把保证逐条列全：

```python
    Subclasses must guarantee:

    - **No cross-Section merging**: every output :class:`Chunk` is
      derived from exactly one input :class:`Section`.
    - **DataBlock pass-through**: a Section whose content is a
      :class:`~agentscope.message.DataBlock` becomes a single Chunk
      with the same content; multimodal data is never sliced.
    - **No empty-text chunks**: a Section whose text content is
      empty or whitespace-only produces no Chunk, so blank pages
      never reach the embedding step.
    - **Continuous indexing**: ``chunk_index`` runs from ``0`` to
      ``total_chunks - 1`` across the entire output list, even
      when the input contains many Sections.
    - **Consistent total_chunks**: every output Chunk carries the
      same ``total_chunks`` value (the length of the output list).
    - **Metadata inheritance**: each output Chunk's ``source`` and
      ``metadata`` are copied from its parent Section.
```

实现层**只有一种**策略 `ApproxTokenChunker`（`rag/_chunker/_approx_token_chunker.py`，`chunker_type = "approx_token"`）。参数默认值与 `overlap >= chunk_size` 的报错都在 `Parameters` 内：

```python
    chunker_type = "approx_token"

    class Parameters(ChunkerBase.Parameters):
        """The tunable parameters of the approximate-token chunker."""

        chunk_size: int = Field(
            default=512,
            ge=1,
            title="Chunk Size",
            description="Maximum number of approximate tokens per chunk.",
        )
        overlap: int = Field(
            default=50,
            ge=0,
            title="Overlap",
            description=(
                "Number of approximate tokens shared between "
                "consecutive chunks."
            ),
        )

        @model_validator(mode="after")
        def _overlap_less_than_chunk_size(
            self,
        ) -> "ApproxTokenChunker.Parameters":
            if self.overlap >= self.chunk_size:
                raise ValueError(
                    "overlap must be less than chunk_size, got "
                    f"overlap={self.overlap}, chunk_size={self.chunk_size}.",
                )
            return self
```

- 参数 `chunk_size: int = 512`、`overlap: int = 50`，`overlap >= chunk_size` 由 `model_validator` 直接报错。
- token 数近似为 `len(text.encode("utf-8")) // 4`，刻意不引入 tokenizer 依赖，真实实现：

```python
    @staticmethod
    def _approx_count_tokens(text: str) -> int:
        """The approx count of tokens.

        Args:
            text (`str`):
                The text to be counted.

        Returns:
            `int`:
                The approx count of tokens.
        """
        return len(text.encode("utf-8")) // 4
```

- 实际切片在 `_split_text`：先算每个字符的 UTF-8 累计字节偏移 `byte_offsets`，把 `chunk_size`/`overlap` 折算成 `chunk_size*4`/`overlap*4` 字节预算，用 `bisect_right` 找字节边界，`end = max(end, start + 1)` 保证每次都有进展（即便某字符 UTF-8 编码本身就超预算）；重叠靠回退 `overlap_bytes` 字节实现。真实片段：

```python
        # Cumulative UTF-8 byte length after each character, so that
        # the byte length of text[i:j] == byte_offsets[j] - byte_offsets[i]
        byte_offsets = [0, *accumulate(len(c.encode("utf-8")) for c in text)]

        chunk_bytes = self.chunk_size * 4
        overlap_bytes = self.overlap * 4

        pieces: list[str] = []
        start = 0
        while start < len(text):
            # The largest end such that the slice fits the byte budget
            end = (
                bisect_right(
                    byte_offsets,
                    byte_offsets[start] + chunk_bytes,
                )
                - 1
            )
            # Always make progress, even for characters whose UTF-8
            # encoding exceeds the budget on their own
            end = max(end, start + 1)
            pieces.append(text[start:end])

            if end >= len(text):
                break

            # Step back by the overlap budget, ensuring forward progress
            next_start = (
                bisect_right(
                    byte_offsets,
                    byte_offsets[end] - overlap_bytes,
                )
                - 1
            )
            start = max(next_start, start + 1)

        return pieces
```

- 最终在 `chunk()` 末尾统一重编号 `chunk_index` / `total_chunks`——「连续编号」是 chunker 收尾的保证，而非 parser 的产出：

```python
        for index, chunk in enumerate(chunks):
            chunk.chunk_index = index
            chunk.total_chunks = len(chunks)

        return chunks
```

### Vector Stores

向量库抽象 `VectorStoreBase`（`rag/_vdb/_vector_store.py`）是单例共享连接（进程级，由 app lifespan 经 async context manager 管理）。抽象方法（`@abstractmethod`）：`create_collection` / `delete_collection` / `has_collection` / `insert` / `delete` / `search` / `list_documents`，例如 `search` 的声明：

```python
    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
```

注意 `list_chunks` **不是**抽象方法——它作为非抽象默认实现抛 `NotImplementedError`，应用层据此映射 HTTP 501、隐藏分块浏览 UI。`rag/_vdb/_vector_store.py` 的 docstring 与结尾：

```python
        Deliberately **not** an ``@abstractmethod``: it was added after
        third-party subclasses of :class:`VectorStoreBase` already
        existed, and making it abstract would break them on upgrade.
        Backends that do not override it raise
        :class:`NotImplementedError`, which the application layer maps
        to HTTP 501 so clients can hide the chunk-browsing UI.
```

```python
        raise NotImplementedError(
            f"{type(self).__name__} does not implement list_chunks().",
        )
```

三种载荷包装模型（均 `pydantic.BaseModel`）刻意**不**给 `Chunk` 增字段以保持其语义稳定：

- `VectorRecord` = `vector: list[float]` + `document_id: str` + `chunk: Chunk`
- `VectorSearchResult` = `score: float` + `document_id` + `chunk`
- `DocumentSummary` = `document_id` + `source` + `chunk_count` + `metadata`

`rag/_vdb/_vector_store.py` 里 `VectorRecord` 的类定义，docstring 直接写明「不给 `Chunk` 加 embedding 字段」：

```python
class VectorRecord(BaseModel):
    """A single record to insert into a vector store collection.

    Pairs a :class:`Chunk` (the business payload — content, source,
    structural metadata) with its dense embedding vector.  ``Chunk``
    is intentionally not extended with an ``embedding`` field so its
    semantics stay stable across the indexing pipeline; instead the
    vector lives in this wrapper whose only purpose is "I am about
    to be inserted into a vector database."
    """

    vector: list[float]
    """The dense embedding vector for :attr:`chunk`."""

    document_id: str
    """The ID of the source document this record belongs to.
    Assigned by the knowledge base layer when the document is
    registered.  Backends must persist it at insertion time so that
    :meth:`VectorStoreBase.delete` can remove all records of one
    document as a unit."""

    chunk: Chunk
    """The business payload — content, source, structural metadata."""
```

`score` 语义统一为**越大越相关**：距离型后端（如 ES / Milvus 的距离）必须取负数后再返回。`VectorSearchResult.score` 的 docstring 原话：

```python
    score: float
    """Relevance score, always higher-is-better.  Backends whose
    metric is a distance (lower-is-better) negate it before returning,
    so the value is comparable within one store but not across stores
    using different metrics."""
```

四个内置后端由 `rag/_vdb/__init__.py` 统一导出：

```python
from ._qdrant import QdrantStore
from ._mongodb import MongoDBStore
from ._milvus_lite import MilvusLiteStore
from ._elasticsearch import ElasticsearchStore
```

| 类 | 文件 |
| :--- | :--- |
| `QdrantStore` | `_qdrant.py` |
| `MongoDBStore` | `_mongodb.py` |
| `MilvusLiteStore` | `_milvus_lite.py` |
| `ElasticsearchStore` | `_elasticsearch.py` |

抽象类 docstring 以「Chroma / Milvus / Qdrant / FAISS」举例，但 v2.0.11 实际随包发布的仍只有上述四个后端。

### Embedding

embedding 模型基类 `EmbeddingModelBase`（`embedding/_embedding_base.py`）与 chat model 同构：`dimensions: int`（**必填一级字段**——向量维度是契约而非可调旋钮）、`context_size` / `batch_size` / `max_retries` / `retry_delay`、`supports_multimodal: bool = False`。类属性声明原样：

```python
    dimensions: int
    """The output embedding vector dimensions.

    Set directly from the :paramref:`__init__.dimensions` argument —
    a required, first-class field rather than something derived from
    :attr:`parameters`.
    """

    context_size: int
    """Maximum input length (in tokens) per single input item."""

    batch_size: int
    """Maximum number of input items per API call."""

    max_retries: int
    """The maximum number of retries for the underlying API."""

    retry_delay: float
    """Seconds to sleep between retry attempts."""

    supports_multimodal: bool = False
    """Whether this model instance accepts :class:`DataBlock` inputs in
    addition to text.  Text-only models keep the default ``False``;
    multimodal subclasses must set it to ``True`` (per instance when
    routing depends on the model name)."""
```

公开 `__call__` 按 `batch_size` 切批后 `asyncio.gather` **并发**调用、每批带重试；子类只需实现单批的 `_call_api`。`TextBlock` 输入在 `__call__` 入口即拆成 `.text`，故 `_call_api` 只见 `str` / `DataBlock`。开头这段真实源码把「拆 `.text`」「切批」「并发 gather」写在一起：

```python
        normalized: list[Any] = [
            item.text if isinstance(item, TextBlock) else item
            for item in inputs
        ]

        # Split into batches.
        batches = [
            normalized[i : i + self.batch_size]
            for i in range(0, len(normalized), self.batch_size)
        ]

        if len(batches) > 1:
            logger.info(
                "Embedding %d inputs in %d batches (batch_size=%d) "
                "for model %s.",
                len(normalized),
                len(batches),
                self.batch_size,
                self.model,
            )

        # Dispatch all batches concurrently, each with retry.
        results: list[EmbeddingResponse] = await asyncio.gather(
            *(self._call_with_retry(batch, **kwargs) for batch in batches),
        )
```

子类唯一要实现的抽象方法签名：

```python
    @abstractmethod
    async def _call_api(
        self,
        inputs: list[Any],
        **kwargs: Any,
    ) -> EmbeddingResponse:
```

### KnowledgeBase Operations

`KnowledgeBase`（`rag/_knowledge.py`）是单个知识库的运行时句柄，构造**零 I/O**，embedding 模型与 vector store 在构造时注入配对。它对外只暴露四个文档操作（模块 docstring 写明的 `search` / `insert_document` / `delete_document` / `list_documents`），外加 `list_chunks`。构造签名：

```python
    def __init__(
        self,
        name: str,
        description: str,
        embedding_model: EmbeddingModelBase,
        vector_store: VectorStoreBase,
        collection: str,
        metadata_filter: dict | None = None,
    ) -> None:
```

「零 I/O + 惰性建库」的记忆化标志就挂在实例上：

```python
        self._metadata_filter = metadata_filter
        # Memoise the "collection exists" check after the first
        # successful ensure_collection so subsequent operations avoid
        # the extra round-trip.
        self._collection_ready = False
        self._collection_lock = asyncio.Lock()
```

- **惰性建库**：`ensure_collection` 幂等且**带记忆化**（`_collection_ready` 标志），首次操作才按 `embedding_model.dimensions` 建 collection，全新部署开箱即用。真实实现：

```python
        if self._collection_ready:
            return
        async with self._collection_lock:
            # Another caller may have initialized while we waited for I/O.
            if self._collection_ready:
                return
            if not await self._vector_store.has_collection(self._collection):
                await self._vector_store.create_collection(
                    self._collection,
                    dimensions=self._embedding_model.dimensions,
                )
            self._collection_ready = True
```

- **search 数据流**：多 query 一次性 `self._embedding_model(queries)` 批量 embed → `asyncio.gather` 并发对每个 query 调 `vector_store.search` → 按 `(document_id, chunk_index)` 去重保留最高分（注释说明该键在重建索引后仍稳定、而 block UUID 会失效）→ 按 `score` 降序截断 `top_k`。`supports_multimodal` 为假的模型先**静默丢弃** `DataBlock` query。整段真实源码：

```python
        if not self._embedding_model.supports_multimodal:
            queries = [q for q in queries if not isinstance(q, DataBlock)]
            if not queries:
                return []

        await self.ensure_collection()
        response = await self._embedding_model(queries)

        results_per_query = await asyncio.gather(
            *(
                self._vector_store.search(
                    collection=self._collection,
                    query_vector=vector,
                    top_k=top_k,
                    metadata_filter=self._metadata_filter,
                )
                for vector in response.embeddings
            ),
        )

        best: dict[tuple[str, int], VectorSearchResult] = {}
        for results in results_per_query:
            for result in results:
                if (
                    score_threshold is not None
                    and result.score < score_threshold
                ):
                    continue
                # ``(document_id, chunk_index)`` is the stable identity
                # of a chunk: it survives reindex (block UUIDs do not)
                # and uniquely names "this slice of that document"
                # regardless of which query surfaced it.
                key = (result.document_id, result.chunk.chunk_index)
                if key not in best or result.score > best[key].score:
                    best[key] = result

        merged = sorted(
            best.values(),
            key=lambda result: result.score,
            reverse=True,
        )
        return merged[:top_k]
```

- **insert_document 元数据优先级**：合并顺序 `{**document_metadata, **chunk.metadata, **metadata_filter}`——`metadata_filter` 因排最后而**最高优先**，形成安全边界：即便 parser 有 bug 也写不进别的 scope。**向量数校验**：embed 返回的向量数与 chunk 数不符直接 `RuntimeError`。两段在同一函数里连续：

```python
        # Precedence: metadata_filter wins (security boundary), then
        # chunk metadata, then document_metadata.  See docstring.
        chunks = [
            chunk.model_copy(
                update={
                    "metadata": {
                        **(document_metadata or {}),
                        **chunk.metadata,
                        **(self._metadata_filter or {}),
                    },
                },
            )
            for chunk in chunks
        ]

        response = await self._embedding_model(
            [chunk.content for chunk in chunks],
        )

        if len(response.embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding model returned {len(response.embeddings)} "
                f"vectors for {len(chunks)} chunks.",
            )
```

### RAGMiddleware Wiring

`RAGMiddleware`（`middleware/_rag.py`）包一组 `KnowledgeBase` 句柄（各自可带不同 embedding 模型），但**不拥有**这些资源、只编排检索；文档入库（解析/切块/embed/插入）不属于它。类 docstring 原文：

```python
    """Middleware that integrates knowledge-base search into the agent.

    Constructed from a list of :class:`~agentscope.rag.KnowledgeBase`
    handles — each carrying its own embedding model, vector store, and
    metadata filter.  The middleware does not own these resources; it
    only orchestrates search against them.

    .. code-block:: python

        # Automatic injection (static mode)
        middleware = RAGMiddleware(
            knowledge_bases=[kb1, kb2],
            search_config=SearchConfig(mode="static"),
        )

        # Agent-driven search (agentic mode, the default)
        middleware = RAGMiddleware(knowledge_bases=[kb1, kb2])

        agent = Agent(..., middlewares=[middleware], ...)
    """
```

`mode: Literal["static", "agentic"]`，**默认 `"agentic"`**；可配 `top_k`（默认 5）、`score_threshold`、`rerank_candidate_k`、`emit_hint_event`（默认 True）、`persist_hint`（默认 False）。`mode` 与 `top_k` 的真实定义：

```python
        mode: Literal["static", "agentic"] = Field(
            default="agentic",
            title="Mode",
            description=(
                "Retrieval is either agentic, letting the Agent decide when "
                "to retrieve, or static, triggering on every user input."
            ),
        )

        top_k: int = Field(
            default=5,
            ge=1,
            le=50,
            title="Top K",
            description=(
                "Maximum number of chunks returned per search, across all "
                "configured knowledge bases."
            ),
        )
```

`rerank_candidate_k` 的上限 `_MAX_CANDIDATE_K = 50` 是模块级常量：

```python
_MAX_CANDIDATE_K = 50
# Upper bound on the candidates handed to the reranker, both as the
# ``rerank_candidate_k`` field bound and as the cap on its default.
```

`hint_template` 与 `rerank_prompt` 用 `SkipJsonSchema` 对 UI 隐藏，真实声明：

```python
        hint_template: SkipJsonSchema[str] = Field(
            default=_DEFAULT_HINT_TEMPLATE,
            title="Hint template",
            description=(
                "Template wrapping the formatted search results in static "
                "mode, with a `{context}` placeholder."
            ),
        )

        # ``hint_template`` is intentionally hidden from the JSON Schema
        # exposed to the dock UI: the wrapper text is part of the
        # middleware's prompt contract and exposing it through the dock
        # invites session-by-session prompt drift.  It is still accepted
        # for programmatic use.

        rerank_prompt: SkipJsonSchema[str] = Field(
            default=_DEFAULT_RERANK_PROMPT,
            title="Rerank prompt",
            description=(
                "Instruction part of the rerank prompt, with a "
                "`{query}` and an optional `{top_k}` placeholder. The "
                "candidates are appended to it by the middleware."
            ),
        )
```

- **agentic 模式**：`list_tools()` 仅在 `mode == "agentic"` 时返回单个 `search_knowledge` 工具（`_SearchKnowledgeTool`，`name="search_knowledge"`、`is_read_only=True`），由 LLM 自行决定何时、查哪些库（`knowledge_bases` 参数按已装库名收窄 enum）。工具类属性：

```python
    name: str = "search_knowledge"
    """The tool name presented to the agent."""

    is_read_only: bool = True
    is_concurrency_safe: bool = True
    is_external_tool: bool = False
    is_state_injected: bool = False
    is_mcp: bool = False
```

`list_tools` 的真实分支：

```python
        if self._parameters.mode == "agentic":
            return [
                _SearchKnowledgeTool(
                    self._knowledge_bases,
                    top_k=self._parameters.top_k,
                    score_threshold=self._parameters.score_threshold,
                    rerank_model=self._rerank_model,
                    rerank_candidate_k=self._parameters.rerank_candidate_k,
                    rerank_prompt=self._parameters.rerank_prompt,
                ),
            ]
        return []
```

- **static 模式**：跨 hook 协作——`on_reply` 先把 reply 输入 deepcopy 后缓存进 `self._cached_inputs`（因为到 `on_reasoning` 时输入可能已被 `state.context` 消费掉），`on_reasoning` 仅在 `agent.state.cur_iter == 0` 做一次性检索，结果包成 `HintBlock` 经 `agent.state.append_context` 注入，可选地发 `HintBlockEvent` 给前端；若不 `persist_hint`，该 block 在本次 reasoning 后立即按 id 移除，避免每轮工具调用都重 embed。`on_reply` 的缓存与清理：

```python
            self._cached_inputs = blocks

        try:
            async for evt in next_handler(**input_kwargs):
                yield evt
        finally:
            self._cached_inputs = None
```

`on_reasoning` 的 `cur_iter == 0` 守卫与 HintBlock 注入：

```python
            if (
                self._parameters.mode == "static"
                and agent.state.cur_iter == 0
                and self._cached_inputs
            ):
```

```python
                    hint = HintBlock(
                        hint=_wrap_hint(
                            self._parameters.hint_template,
                            blocks,
                        ),
                        source=_HINT_SOURCE,
                    )
                    agent.state.append_context(agent.name, [hint])
                    if self._parameters.emit_hint_event:
                        yield HintBlockEvent(
                            reply_id=agent.state.reply_id,
                            block_id=hint.id,
                            source=hint.source,
                            hint=hint.hint,
                        )
```

- **rerank 是 best-effort**：接了 `rerank_model` 时检索放宽到 `rerank_candidate_k` 个候选、由 chat model 挑最终 `top_k`；rerank 失败就回退向量序。跨不同 embedding 模型的分数不可严格比较，合并仅按原始 `score` 排序。真实回退分支：

```python
    try:
        return await _rerank_results(
            rerank_model=rerank_model,
            queries=queries_list,
            candidates=results,
            top_k=top_k,
            prompt=rerank_prompt,
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "Knowledge-base rerank failed (%s); falling back to vector "
            "order.",
            e,
        )
        return results[:top_k]
```



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [RAG](/docs/CS/AI/RAG.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [VoiceStack](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md) / [Classifier](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — rag/](https://github.com/agentscope-ai/agentscope/tree/v2.0.11/src/agentscope/rag)
- `src/agentscope/rag/_document.py` / `_parser/` / `_chunker/` / `_knowledge.py`
- `src/agentscope/middleware/_rag.py`
