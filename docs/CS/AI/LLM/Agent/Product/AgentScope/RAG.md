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

### RAGMiddleware: Two Modes

把 RAG 接进主循环的是 `middleware/_rag.py` 里的 `RAGMiddleware`，两种模式：

- **`agentic`**（默认）——通过 `list_tools()` 暴露单个 `SearchKnowledgeTool`，让 LLM 自己决定何时检索
- **`static`**——跨 hook 协作：`on_reply` 先把输入 block 缓存起来，`on_reasoning` 再取用（因为到那时输入可能已被 `state.context` 消费掉）；只在 `cur_iter == 0` 触发一次，避免每轮工具调用都重新 embed

可选接入 `rerank_model` 做重排，但失败时保留向量序（best-effort）。`hint_template` 和 `rerank_prompt` 用 `SkipJsonSchema` 对 UI 隐藏——它们属于中间件的 prompt 契约，不该每次会话被改。



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [RAG](/docs/CS/AI/RAG.md)

## References

- `src/agentscope/rag/_document.py` / `_parser/` / `_chunker/` / `_knowledge.py`
- `src/agentscope/middleware/_rag.py`
