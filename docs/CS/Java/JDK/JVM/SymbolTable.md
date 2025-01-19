## Introduction





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

