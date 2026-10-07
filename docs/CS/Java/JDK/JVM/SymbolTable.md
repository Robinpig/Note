## Introduction





## Version Baseline

> [!NOTE]
> **版本口径**：符号表与字符串驻留集（StringTable）在 **JDK 7** 经历过一次大重构（`SymbolTable` 与 `StringTable` 拆分），JDK 8 引入 `ConcurrentHashTable` 并发化，JDK 10+ 逐步替换为 `ConcurrentHashMap` 支撑的弱引用实现。并发查找的可用性随版本变化明显。详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

```c++

class SymbolTable : public AllStatic {
  friend class VMStructs;
  friend class Symbol;
  friend class ClassFileParser;
  friend class SymbolTableConfig;
  friend class SymbolTableCreateEntry;

 private:
  static volatile bool _has_work;

  // Set if one bucket is out of balance due to hash algorithm deficiency
  static volatile bool _needs_rehashing;

};

typedef ConcurrentHashTable<SymbolTableConfig, mtSymbol> SymbolTableHash;
static SymbolTableHash* _local_table = nullptr;

volatile bool SymbolTable::_has_work = 0;
volatile bool SymbolTable::_needs_rehashing = false;
```









```c++
void SymbolTable::create_table ()  {
  size_t start_size_log_2 = ceil_log2(SymbolTableSize);
  _current_size = ((size_t)1) << start_size_log_2;
  log_trace(symboltable)("Start size: " SIZE_FORMAT " (" SIZE_FORMAT ")",
                         _current_size, start_size_log_2);
  _local_table = new SymbolTableHash(start_size_log_2, END_SIZE, REHASH_LEN, true);

  // Initialize the arena for global symbols, size passed in depends on CDS.
  if (symbol_alloc_arena_size == 0) {
    _arena = new (mtSymbol) Arena(mtSymbol);
  } else {
    _arena = new (mtSymbol) Arena(mtSymbol, symbol_alloc_arena_size);
  }
}
```











## Links
