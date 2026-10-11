## Introduction

`Symbol` 是 HotSpot 内部**驻留（interned）且不可变的 UTF-8 字节串**。它不是 Java 对象：没有 oop 头、没有 markWord、不在 GC 堆里、GC 也不把它当对象扫描。`oops/symbol.cpp:396` 的 `Symbol::is_valid()` 里就有一条判据专门把它和堆对象区分开：

```cpp
  // Symbols are not allocated in Java heap.
  if (Universe::heap()->is_in(s)) return false;
```

HotSpot 自己的定义在 `oops/symbol.hpp:33-34`：`A Symbol is a canonicalized string. All Symbols reside in global SymbolTable and are reference counted.`

**为什么需要它**。class 文件里几乎每一个"名字"都是一个 `CONSTANT_Utf8_info`：类名 `java/lang/String`、方法名 `main`、字段名、签名 `(Ljava/lang/String;)V`、模块名、包名。一个中等规模的 JVM 进程里，同一批名字会被成千上万个 class 反复引用——`java/lang/Object` 可能出现在几万个常量池中。若每次解析 class 都复制一份字符串，那么名字比较要 `strcmp`（而类查找、方法解析、字段解析、加载器约束检查全在比名字），内存被名字本身吃掉一大块，也没法把"名字 + 类加载器"直接当哈希键。

驻留一次解决两件事：**同一个内容全局只有一个 `Symbol*`**，于是比较退化成指针比较、哈希可以预先算好塞进符号自己身上。`oops/constantPool.cpp:1396-1400` 是直接受益者：

```cpp
bool ConstantPool::klass_name_at_matches(const InstanceKlass* k, int cp_index) {
  // Names are interned, so we can compare Symbol*s directly
  Symbol* cp_name = klass_name_at(cp_index);
  return (cp_name == k->name());
}
```

类加载器自身的字典同样如此，键是 `Symbol*`、比较是指针相等（`classfile/dictionary.cpp:124-127`），哈希值直接取符号自带的 identity hash（`classfile/dictionary.cpp:58-60`）——一次查表既不用重算哈希也不用 `strcmp`。模块表、包表、加载器约束表都把 `SymbolHandle::compute_hash` 当哈希函数传入（`classfile/moduleEntry.hpp:231`、`classfile/packageEntry.hpp:248`、`classfile/loaderConstraints.cpp:150`）。

本篇讲**符号本体 + 符号表结构 + 并发维护与回收**；`String.intern()` 的 Java 侧语义只在最后一节做结构对比。

## Version Baseline

> [!NOTE]
> **本篇最容易被写错的一点**：旧笔记与网上流传的"JDK 10+ 把 `SymbolTable` 换成了 `ConcurrentHashMap` 支撑的弱引用实现"，在 **HotSpot C++ 侧不成立**。在本地 `jdk-27-ga` 全量源码里：
>
> - 符号表容器仍是 `typedef ConcurrentHashTable<SymbolTableConfig, mtSymbol> SymbolTableHash;`（`classfile/symbolTable.cpp:75`），`ConcurrentHashTable` 本身也仍在 `utilities/concurrentHashTable.hpp`。
> - 全树搜 `ConcurrentHashMap` 只命中 `classfile/vmSymbols.hpp` 与 `classfile/vmClassMacros.hpp` 两个文件，命中的是 **Java 类名字符串** `java/util/concurrent/ConcurrentHashMap`（VM 要引用这个 Java 类），不是 C++ 容器。
> - 符号表里**没有任何弱引用**，存活与否由 `Symbol` 自己的 16 位引用计数决定。弱引用只在 **StringTable** 一侧：表值是 `WeakHandle`（`classfile/stringTable.cpp:175`），外加一个 weak OopStorage `create_weak("StringTable Weak", mtSymbol)`（`classfile/stringTable.cpp:300`）。把 StringTable 的实现细节安到 SymbolTable 头上，就是那句话的全部错误来源。
> - 老资料里的 `SymbolTable::unlink()` / `do_purge()` 两个清理入口**本树已彻底不存在**：整棵树 `do_purge` 零命中；泛型 `Hashtable` 的 `unlink` 成员还在（`utilities/hashtable.hpp:295`，服务 ModuleTable 与加载器约束表等旧式表），但 `SymbolTable` 早就不用 `Hashtable`。现在的回收路径是 `clean_dead_entries()` 的 `BulkDeleteTask` 与 `grow()` 的顺带清理。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Symbol Layout

### Fields and Immutability

`Symbol` 声明在 `oops/symbol.hpp`——**不在 `classfile/` 下，`classfile/symbol.hpp` 这个路径不存在**，且继承的是 `MetaspaceObj` 而不是 `Metadata`：

```cpp
class Symbol : public MetaspaceObj {
  // This is an int because it needs atomic operation on the refcount.  Mask hash
  // in high half word. length is the number of UTF8 characters in the symbol
  volatile uint32_t _hash_and_refcount;
  u2 _length;
  u1 _body[2];
```

字段布局与老笔记常见的 `_len` + `_bytes` 两字段版已经不同：JDK 9 之后哈希与引用计数被打包进同一个 32 位字，以便用**一条 CAS 同时完成"判活 + 加引用"**。

| 字段 | 类型 | 含义 | 访问器 |
| :-- | :-- | :-- | :-- |
| `_hash_and_refcount` | `volatile uint32_t` | 高 16 位 hash 片段，低 16 位引用计数 | `refcount()` / `identity_hash()` |
| `_length` | `u2` | UTF-8 字节数，上限 `0xffff` | `utf8_length()` / `length()` |
| `_body[2]` | `u1[]` | 柔性数组式尾部，实际长度由 `byte_size()` 决定 | `bytes()` / `base()` / `char_at(i)` |

打包函数 `pack_hash_and_refcount()` 里有一条 `STATIC_ASSERT(PERM_REFCOUNT == ((1 << 16) - 1))`（`oops/symbol.cpp:45-52`），而 `PERM_REFCOUNT` 定义为 `0xffff`（`oops/symbol.hpp:99-102`）——16 位全 1 既是"永久"标记也是计数上限，两者故意重合。空间计算是"头 8 字节 + 超出 2 的部分"：`byte_size(length) = sizeof(Symbol) + (length > 2 ? length - 2 : 0)`（`oops/symbol.hpp:123-130`）。

`max_symbol_length = 0xffff` 直接来自 class 文件 `utf8_length` 是 u2 这一事实。超长字符串不会撑爆结构，产品构建里**被截断并 warning**，注释直说这是给"用法错误 creeping in"兜底（`classfile/symbolTable.cpp:337-351`）。

**不可变性**：没有任何 public 方法能改 `_body`；构造函数私有且只允许 `SymbolTable` 调用（`oops/symbol.hpp:132-133`）。所有"读成 C 字符串"的接口都返回**复制品**，且复制目标几乎都是 Resource 区，所以调用方必须有 `ResourceMark`：`as_C_string()` / `as_utf8()` / `as_quoted_ascii()` / `as_unicode(int&)` / `as_klass_external_name()`（`oops/symbol.cpp:126-205`）。

⚠️ 方法名是**小写 `as_utf8()`**，写成 `as_UTF8()` 在本树找不到符号。另外 `fast_compare()` 是唯一"内容无关"的比较，它直接比地址，理由写在 `oops/symbol.hpp:313-320`：符号在 C 堆上，相对地址永不变化。

### Identity Hash versus Content Hash

这是符号体系里最反直觉的一点。`Symbol::identity_hash()` 的低 16 位来自构造时塞进去的**随机数**，不是内容哈希（`oops/symbol.cpp:54-56`）：

```cpp
Symbol::Symbol(const u1* name, int length, int refcount) {
  _hash_and_refcount =  pack_hash_and_refcount((short)os::random(), refcount);
```

组装结果一半是随机片段、一半是"地址异或长度异或前两字节"（`oops/symbol.hpp:155-159`）：

```cpp
  unsigned identity_hash() const {
    unsigned addr_bits = (unsigned)((uintptr_t)this >> LogBytesPerWord);
    return ((unsigned)extract_hash(_hash_and_refcount) & 0xffff) |
           ((addr_bits ^ (length() << 8) ^ (( _body[0] << 8) | _body[1])) << 16);
  }
```

所以它**只能当身份用，不能当内容用**：同一串文本被删掉再重建，新符号的 identity hash 与旧的无关；两个 identity hash 相同而内容不同的符号也允许存在。它适合做 `Dictionary` / `ModuleTable` / `PackageTable` 的桶键，因为那些表的键是**某个活的 `Symbol*`**，靠 `equals` 里的指针比较定胜负。

而 `SymbolTable` 自己**用的是内容哈希**——它的任务是"给一段字节找出唯一符号"。`Symbol::compute_hash`（`oops/symbol.hpp:300-302`）虽然挂在符号上，但转发的是 `identity_hash()`，那是给别的表用的。CDS dump 时 identity hash 会被 `update_identity_hash()` 从随机值换成归档熵，以保证归档可复现（`oops/symbol.cpp:75-78`）。

### Reference Counting and TempNewSymbol

`oops/symbol.hpp:36-96` 用整段注释定义引用计数协议，四条规则浓缩成一张表：

| 场景 | 规则 | 证据 |
| :-- | :-- | :-- |
| 存进持久字段 | 必须计数，如常量池项、`fieldDescriptor::_name` | `symbol.hpp:44-49` |
| 从 `lookup()` 拿到 | **在 lookup 里加**，不是赋值时加；调用方负责手动减 | `symbol.hpp:51-63` |
| 只是别人的副本且作用域更短 | 省掉计数，如 `Symbol* kn = klass->name()` | `symbol.hpp:65-85` |
| 临时造新符号 | 一律用 `TempNewSymbol` 包住，构造加、析构减 | `symbol.hpp:87-92` |

符号表桶里那个指针**不计入引用计数**，所以"计数归零"就意味着除了表自身没人用了。三个原子操作共享同一套 CAS 骨架，关键差别在遇到 0 与 `PERM_REFCOUNT` 时的态度（`oops/symbol.cpp:288-311`）：

```cpp
// Increment refcount while checking for zero.  If the Symbol's refcount becomes zero
// a thread could be concurrently removing the Symbol.  This is used during SymbolTable
// lookup to avoid reviving a dead Symbol.
bool Symbol::try_increment_refcount() {
    if (refc == PERM_REFCOUNT) { return true;  // sticky max or created permanent
    } else if (refc == 0)      { return false; // dead, can't revive.
    } else { found = AtomicAccess::cmpxchg(&_hash_and_refcount, old_value, old_value + 1); ... }
```

`decrement_refcount()` 不能简单 `dec`：别的线程可能同时把它升到 `PERM_REFCOUNT`，所以必须 cmpxchg 后重读判断（`oops/symbol.cpp:325-344`）。`make_permanent()` 是"粘住"操作，一旦升到 `0xffff` 再也下不来（`oops/symbol.cpp:346-367`）。

`TempNewSymbol` 与 `SymbolHandle` 是同一个模板的两个实例化，唯一区别是构造时是否"认领"已有计数（`oops/symbolHandle.hpp:101-111`）。`TempNewSymbol` 拿到 `refcount()==1` 的新符号时不会立刻放手，而是塞进 128 槽环形队列延后清理，注释说明原因是"同一串字节往往被连着造出来又扔掉，延后可让它被复用"（`oops/symbolHandle.cpp:30-39`）。配套的 `drain_queue()` 有声明有定义，但**在本树 `src/hotspot` 内没有调用点**（该树不含 test 源码）——这条只作"读源码时别被它误导"的提示，不要据此推断 API 被删除。

## Allocation Paths

### Three Backing Stores

"符号的内存从哪来"的正确答案分三条路径，全部集中在 `SymbolTableConfig::allocate_node_impl()`（`classfile/symbolTable.cpp:176-202`）：

```cpp
    if (value.refcount() != PERM_REFCOUNT) {
      return AllocateHeap(alloc_size, mtSymbol);
    } else {
      // Allocate to global arena
      MutexLocker ml(SymbolArena_lock, Mutex::_no_safepoint_check_flag); // Protect arena
      return SymbolTable::arena()->Amalloc(alloc_size);
    }
```

| 条件 | 分配器 | 锁 | 能否释放 |
| :-- | :-- | :-- | :-- |
| 普通符号，运行期 | `AllocateHeap()` → `os::malloc` | 无 | 是，`FreeHeap()` |
| 永久符号，运行期 | `SymbolTable::_arena` 的 `Amalloc()` | `SymbolArena_lock` | 理论上 `Afree`，常失败 |
| static CDS dump 期间 | `AOTMetaspace::symbol_space_alloc()` | `DumpRegion_lock` | 不释放，注释写明 "No deallocation is needed" |

`AllocateHeap` 就是 malloc 加 NMT 记账（`memory/allocation.cpp:37-46`，`os::malloc(size, mem_tag, stack)`），`mtSymbol` 在 NMT 里的显示名是 `Symbol`（`nmt/memTag.hpp:44`）。所以"符号走本地内存、不占 Metaspace 也不占堆"在本版本依然成立，与 [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md) 一节"Symbols => native memory"的口径一致。`Symbol` 继承 `MetaspaceObj` 只为复用 CDS 的 `MetaspaceClosure` 协议（它的 `metaspace_pointers_do()` 什么都不 push，`oops/symbol.cpp:369-377`）与只读归档资格（`is_read_only_by_default()` 返回 true，`oops/symbol.hpp:150-151`）。

永久符号走 Arena 而非常规堆，代价是 `Afree` 只能归还最近一次分配，否则内存留在 arena 里出不去。`free_node()` 把这种失败显式记成日志 `" - Leaked permanent symbol"`（`classfile/symbolTable.cpp:159-171`）；同函数的断言则把允许进入释放的三种状态钉死：永久、`refcount()==1`（刚造的、插入撞车）、`refcount()==0`（清理）（`classfile/symbolTable.cpp:140-147`）。

### Node Layout and Bootstrap

符号不是独立对象，它**嵌在哈希表节点尾部**。`ConcurrentHashTable::Node` 只有三个字段：`DEBUG_ONLY(size_t _saved_hash)`、`Atomic<Node*> _next`、`VALUE _value`（`utilities/concurrentHashTable.hpp:70-74`），节点总长由动态尺寸公式算出（`utilities/concurrentHashTable.inline.hpp:1061-1067`）：`sizeof(Node) - sizeof(VALUE) + value_size`。能这么玩的前提是 `Node::_value` 正好贴着对象结尾、无尾部填充，由 `is_dynamic_sized_value_compatible()` 断言（`utilities/concurrentHashTable.hpp:104-108`）。所以**一个符号的真实开销 = 链表指针 + 8 字节 Symbol 头 + UTF-8 字节**。

插入时其实构造了两次：`do_add_if_needed()` 先在 Resource 区 placement-new 一个临时 `Symbol` 当作 `insert()` 的 value 参数（`classfile/symbolTable.cpp:512-516`），真正的符号是 `Node::create_node` 里由拷贝构造体复制出来的——拷贝构造自己的注释就是证据：`This copies the symbol when it is added to the ConcurrentHashTable.`（`oops/symbol.cpp:67-72`）。

表和 arena 建在 `universe_init()` 里，顺序 StringTable → AOT metaspace → null CLD → SymbolTable → ResolvedMethodTable（`memory/universe.cpp:923`、`946`、`952`）。`create_table()` 与旧笔记那段大致相同，但两处细节变了：取整函数叫 `log2i_ceil`（`utilities/powerOfTwo.hpp:84-87`），Arena 构造多了 `Arena::Tag` 参数（`classfile/symbolTable.cpp:205-218`）：

```cpp
  size_t start_size_log_2 = log2i_ceil(SymbolTableSize);
  _local_table = new SymbolTableHash(start_size_log_2, END_SIZE, REHASH_LEN, true);
  ...
    _arena = new (mtSymbol) Arena(mtSymbol, Arena::Tag::tag_other, symbol_alloc_arena_size);
```

表建好后，VM 内置符号才在 `universe2_init()` → `Universe::genesis()` → `vmSymbols::initialize()`（调用点 `memory/universe.cpp:445`）里逐个 `new_permanent_symbol()` 灌进来。所有 VM 符号的字符串被编译成一整块以 `\0` 分隔的只读数据，以免 libjvm 里散落一堆字符串常量（`classfile/vmSymbols.cpp:74-90`）。注意外层条件是 `if (!CDSConfig::is_using_archive())`：**用了 CDS 归档时这一步整个跳过**，符号直接从归档里的 compact table 映射。

## SymbolTable Data Structure

### Handles and Constants

`SymbolTable` 是 `AllStatic`，类体里只留两个 volatile bool 和一组私有静态函数（`classfile/symbolTable.hpp:49-59`）：

```cpp
class SymbolTable : public AllStatic {
  friend class Symbol;
  friend class ClassFileParser;
  friend class SymbolTableConfig;
  friend class SymbolTableCreateEntry;

 private:
  static volatile bool _has_work;

  // Set if one bucket is out of balance due to hash algorithm deficiency
  static volatile bool _needs_rehashing;
```

⚠️ **表句柄不是类成员**。`_local_table` 是 `symbolTable.cpp` 的文件级 static（`classfile/symbolTable.cpp:75-76`）：

```cpp
typedef ConcurrentHashTable<SymbolTableConfig, mtSymbol> SymbolTableHash;
static SymbolTableHash* _local_table = nullptr;
```

网上把 `static SymbolTableHash* _local_table` 写成 `SymbolTable` 成员的流行片段是抄漏了作用域，头文件里没有这个字段。同类文件级 static 还有一组状态与统计量：`_symbols_removed`、`_symbols_counted`、`_current_size`、`_items_count`、`_has_items_to_clean`、`_alt_hash`、`_rehashed`、`_alt_hash_seed`，以及线程局部的 `_lookup_shared_first`（`classfile/symbolTable.cpp:78-99`）。

| 常量 | 值 | 位置 | 作用 |
| :-- | :-- | :-- | :-- |
| `PREF_AVG_LIST_LEN` | `8.0` | `symbolTable.cpp:50` | 负载因子超过它就 grow |
| `END_SIZE` | `24` | `symbolTable.cpp:52` | 桶数上限 `2^24` |
| `REHASH_LEN` | `100` | `symbolTable.cpp:54` | 链长超过它就提示需要 rehash |
| `ON_STACK_BUFFER_LENGTH` | `128` | `symbolTable.cpp:56` | UTF16→UTF8 转换的栈缓冲 |
| `symbol_alloc_batch_size` | `8` | `symbolTable.hpp:107` | 常量池批量插入的批大小 |
| `symbol_alloc_arena_size` | `360*K` | `symbolTable.hpp:109` | 永久符号 arena 初始大小 |

`REHASH_LEN` 的命名有历史包袱：它作为第 3 个实参传给 `ConcurrentHashTable`，形参名其实是 `grow_hint`（构造函数声明 `utilities/concurrentHashTable.hpp:427-432`），语义是"链上走过多少节点还没命中，就认为哈希质量有问题"。初始与上限桶数由 `-XX:SymbolTableSize` 决定：默认 `32768`（2^15）、范围 `1024..2^24`、**EXPERIMENTAL**，命令行要配 `-XX:+UnlockExperimentalVMOptions`（`runtime/globals.hpp:112-113`、`1816-1818`）。

### Shared CDS Tables

运行期只有一张动态表，但一次查找最多涉及**三张**共享表。两个只读表是 compact hashtable，直接映射自归档文件、不占可写内存（`classfile/symbolTable.cpp:60-71`）：

```cpp
static OffsetCompactHashtable<
  const char*, Symbol*,
  symbol_equals_compact_hashtable_entry
> _shared_table, _dynamic_shared_table, _shared_table_for_dumping;
```

compact table 的查找是"哈希取模定位桶 + 桶内线性扫"，桶要么是单值要么是 `(hash, value)` 对数组（`classfile/compactHashtable.hpp:273-300`）。dump 时每个符号先 `set_permanent()` 再压缩编码指针写入（`classfile/symbolTable.cpp:684-696`）。归档桶的平均深度由 `-XX:SharedSymbolTableBucketSize` 控制，默认 4、范围 `2..246`（`cds/cds_globals.hpp:62-64`）。整体加速口径见 [Startup_Acceleration](/docs/CS/Java/JDK/JVM/Startup_Acceleration.md)。

## Hashing and Lookup

### Hash Function Selection

`hash_symbol()` 只有三行，却是所有并发问题的源头（`classfile/symbolTable.cpp:109-114`）：

```cpp
// Pick hashing algorithm.
static unsigned int hash_symbol(const char* s, int len, bool useAlt) {
  return useAlt ?
  AltHashing::halfsiphash_32(_alt_hash_seed, (const uint8_t*)s, len) :
  java_lang_String::hash_code((const jbyte*)s, len);
}
```

默认走 `java_lang_String::hash_code` 的 **jbyte 重载**，即对 UTF-8 原始字节做 K&R 的 P(31) 多项式（`classfile/javaClasses.hpp:178-184`，上方注释写着 "THIS ALGORITHM MUST MATCH String.hashCode()"）。纯 ASCII 名字与 `String.hashCode()` 一致。`_alt_hash` 一旦被翻成 true 就换成带随机种子的 `halfsiphash_32`——这是抗哈希碰撞算法复杂度攻击的开关。

⚠️ 共享归档表**永远用原始 Java 哈希**，因为归档内容不可重算，于是 `lookup_shared()` 进来先做一次哈希纠正：注释原文是 "hash_code parameter may use alternate hashing algorithm but the shared table always uses the same original hash code"（`classfile/symbolTable.cpp:102-120`、`297-314`）。

### Entry Points

可调入口都在 `classfile/symbolTable.hpp:118-142`，语义差别集中在"要不要分配""计数怎么算""查哪张表"三点：

| 入口 | 未命中时 | 命中时计数 | 查找路径 |
| :-- | :-- | :-- | :-- |
| `new_symbol(const char*, int)` | 创建普通符号 | 加 1 | `lookup_common`，动态表 + 共享表 |
| `new_symbol(const jchar*, int)` | 先转 UTF-8 再同上 | 加 1 | 同上 |
| `new_symbol(const Symbol*, begin, end)` | 截取子串后新建 | 加 1 | 同上 |
| `new_permanent_symbol(name)` | 建在 arena，计数 `PERM_REFCOUNT` | **命中但非永久时被 `make_permanent()` 转正** | `lookup_only` |
| `probe(name, len)` / `probe_unicode` | **返回 nullptr，绝不分配** | 命中则加 1 | `lookup_only` |
| `lookup_only(name, len, hash&)` | nullptr | 命中则加 1 | `lookup_common` |
| `new_symbols(...)` 批量 | 由 ClassFileParser 调用 | 加 1 | 只加动态表 |

`probe` 的头文件注释本身就是一句警告：`NO ALLOCATION IS GUARANTEED!`（`classfile/symbolTable.hpp:118-122`）。`lookup_common()` 里那个 `_lookup_shared_first` 是纯性能设计：它是 `THREAD_LOCAL`，记录"上次命中在共享表还是动态表"，让同一线程后续按更可能命中的顺序试探两张表；之所以放 TLS，注释解释是因为多线程往一个全局变量里更新命中历史会打爆缓存行（`classfile/symbolTable.cpp:92-94`、`316-335`）。

### Refcount on Lookup

引用计数在**匹配成功的那一刻**加，而不是在 `get` 返回之后——否则从"找到"到"加计数"的窗口里，符号可能被并发清理线程回收。`SymbolTableLookup` 的两个回调凑齐了判活协议（`classfile/symbolTable.cpp:390-411`）：

```cpp
  // Note: When equals() returns "true", the symbol's refcount is incremented. This is
  // needed to ensure that the symbol is kept alive before equals() returns to the caller,
  // so that another thread cannot clean the symbol up concurrently.
  bool equals(Symbol* value) {
    Symbol *sym = value;
    if (sym->equals(_str, _len)) {
      if (sym->try_increment_refcount()) { return true; }
      else { assert(sym->refcount() == 0, "expected dead symbol"); return false; }
    } else { return false; }
  }
  bool is_dead(Symbol* value) { return value->refcount() == 0; }
```

`equals` 里 `try_increment_refcount()` 失败说明撞到死符号，跳过继续走链；`is_dead` 则给表打上"这个桶有垃圾"的标记，最终变成 `clean_hint`。

### Insert Races

`do_add_if_needed()` 是一段标准乐观插入：先 `insert`，成功后再 `get` 拿回表里真正的那个符号（插入可能被复制、也可能命中的是别人的重复项），所以要减掉自己多出的那一份计数；`insert` 失败（被抢先）就直接 `get`，`get` 也失败（那个符号又被清了）就整个重来（`classfile/symbolTable.cpp:518-538`）：

```cpp
  do {
    if (_local_table->insert(current, lookup, *tmp, &rehash_warning, &clean_hint)) {
      if (_local_table->get(current, lookup, stg, &rehash_warning)) {
        sym = stg.get_res_sym();
        // The get adds one to ref count, but we inserted with our ref already included.
        // Therefore decrement with one.
        if (sym->refcount() != PERM_REFCOUNT) { sym->decrement_refcount(); }
        break;
      }
    }
    // In case another thread did a concurrent add, return value already in the table.
    // This could fail if the symbol got deleted concurrently, so loop back until success.
    if (_local_table->get(current, lookup, stg, &rehash_warning)) {
      sym = stg.get_res_sym(); break; }
  } while(true);
```
### Constant Pool Bulk Path

逐个插入在"一个 class 有上百个 UTF8 项"时会重复算哈希，所以 `ClassFileParser` 用两阶段策略：解析常量池时**先只查不建**，未命中的攒够 8 个再批量建（`classfile/classFileParser.cpp:340-362`）：

```cpp
        unsigned int hash;
        Symbol* const result = SymbolTable::lookup_only((const char*)utf8_buffer,
                                                        utf8_length, hash);
        if (result == nullptr) {
          names[names_count] = (const char*)utf8_buffer;
          lengths[names_count] = utf8_length;
          indices[names_count] = index;
          hashValues[names_count++] = hash;
          if (names_count == SymbolTable::symbol_alloc_batch_size) {
            SymbolTable::new_symbols(_loader_data, constantPoolHandle(THREAD, cp), ...);
            names_count = 0;
          }
        } else { cp->symbol_at_put(index, result); }
```

批量入口里有一个决定符号命运的细节：`is_permanent` 只看是不是 null class loader 的 CLD，而注释提醒**非强隐藏类（non-strong hidden class）即使由引导加载器加载也不算永久**，因为它们的 CLD 不同（`classfile/symbolTable.cpp:485-501`）。UTF16 入口则体现一个小优化：短串用 128 字节栈缓冲，长串才退回 Resource 区（`classfile/symbolTable.cpp:454-467`）；源码里 "Push unicode-based lookup all the way into the hashing and probing logic" 那条建议仍未实现。

### Concurrency Model

`ConcurrentHashTable` 的设计目标写在头注释（`utilities/concurrentHashTable.hpp:36-39`）：`a mostly concurrent-hash-table where the read-side is wait-free, inserts are CAS and deletes mutual exclude each other on per bucket-basis.`

| 操作 | 机制 | 是否阻塞 |
| :-- | :-- | :-- |
| 读 `get` | wait-free，epoch 式临界区 `ScopedCS`，只累加链长计数 | 从不阻塞 |
| 插 `insert` | CAS 换桶头 `_first`，失败则 yield / SpinPause 重试 | 与同桶写者互斥 |
| 删死节点 | 每桶一把自旋锁，删除者两两互斥 | 只挡同桶写者 |
| resize / rehash | 桶指针低 2 位编码三态，逐桶搬运并安装 redirect | 搬运期间读侧照常工作 |

桶状态注释把死锁风险说得很直白（`utilities/concurrentHashTable.hpp:117-125`）："You must never busy-spin on trylock() or call lock() without _resize_lock, that would deadlock. Redirect can only be installed by owner and is the final state of a bucket." 链长统计在 `get_node()` 顺手完成（`utilities/concurrentHashTable.inline.hpp:619-638`），`internal_get()` 用它产出 hint：`*grow_hint = loops > _grow_hint;`（同文件 `864-881`）。`SymbolTable` 侧把这个出参一律命名为 `rehash_warning`，是同一件事的两种叫法。安全性的最后一环是"死符号不能被读出来复用"，靠 `equals()` 里的 `try_increment_refcount()` 与表操作落在同一临界区内完成。

## Resize Rehash and Cleanup

### Work Signaling

符号表没有后台定时器，所有维护都挂在 **ServiceThread** 上（线程本体见 [Thread](/docs/CS/Java/JDK/JVM/Thread.md)）。信号链：任何一次 `do_lookup()` / `do_add_if_needed()` 拿到 hint → `update_needs_rehash()` → `trigger_cleanup()` → 唤醒 ServiceThread（`classfile/symbolTable.cpp:427-432`、`243-250`）：

```cpp
void SymbolTable::trigger_cleanup() {
  // Avoid churn on ServiceThread
  if (!has_work()) {
    MutexLocker ml(Service_lock, Mutex::_no_safepoint_check_flag);
    _has_work = true;
    Service_lock->notify_all();
  }
}
```

`ServiceThread` 的轮询用**算术或**而非短路或，注释解释是为了避免"前面永远为真的条件把后面的工作饿死"（`runtime/serviceThread.cpp:104-120`、`132-134`）；即使没人 notify，也有 `ServiceThreadCleanupInterval` 兜底，默认 1000 毫秒、DIAGNOSTIC（`runtime/globals.hpp:1258-1261`）。另外两个触发入口：插入撞到死节点的 `clean_hint` 经 `mark_has_items_to_clean()` + `check_concurrent_work()` 走（同文件 `542-545`、`797-809`，条件是"有垃圾待清 或 负载因子 > 8.0"）；以及类卸载——`SystemDictionary::do_unloading()` 只要真卸载过类就无条件 `SymbolTable::trigger_cleanup()`（`classfile/systemDictionary.cpp:1554`、`1576-1577`）。

### do_concurrent_work Order

一次维护只做一件事，优先级 rehash > grow > clean。`do_concurrent_work()` 里 "Rehash if needed. Rehashing goes to a safepoint but the rest of this work is concurrent" 与 "We prefer growing, since that also removes dead items" 两句注释就把流程定完了：先 `needs_rehashing() && maybe_rehash_table()`，成了就直接返回；否则 `should_grow()` 为真走 `grow(jt)`，不然走 `clean_dead_entries(jt)`；最后 `release_store(&_has_work, false)`（`classfile/symbolTable.cpp:815-830`）。

"宁可扩表也不光清垃圾"的理由就在注释里：grow 搬运节点时会顺手丢掉死项，一次干两件事。`grow()` 与 `clean_dead_entries()` 都是分片推进的可中断任务，每做一片就 `pause()` 并让出 `_thread_in_Java` 状态（`ThreadBlockInVM`），确保不拖住 Java 线程进安全点（`classfile/symbolTable.cpp:723-742`、`766-795`）。清理判据只有一条：`refcount() == 0`（`SymbolTableDeleteCheck`，`classfile/symbolTable.cpp:755-764`）。`clean_dead_entries()` 开头那段锁序注释是一个真实踩过的坑：`BulkDeleteTask::prepare()` 会拿 `ConcurrentHashTableResize_lock`（rank `nosafepoint-2`），开启 `NativeHeapTrimmer` 时 `SuspendMark` 会拿它自己的锁，必须先 `SuspendMark` 才不死锁（同文件 `767-770`）。

### Rehash at Safepoint

`maybe_rehash_table()` 有两道劝退检查（`classfile/symbolTable.cpp:855-875`）：能 grow 就 grow；**已经 rehash 过一次还长链，说明不是哈希算法的问题**，打个 warning 就放弃，绝不反复进安全点。剩下的交给 `VM_RehashSymbolTable`（`runtime/vmOperations.cpp:112-114`）在全局安全点执行 `rehash_table()`——注意它**不换大小、只换算法**（`classfile/symbolTable.cpp:832-853`）：

```cpp
// Called at VM_Operation safepoint
void SymbolTable::rehash_table() {
  assert(SafepointSynchronize::is_at_safepoint(), "must be called at safepoint");
  _alt_hash_seed = AltHashing::compute_seed();
  // We use current size
  size_t new_size = _local_table->get_size_log2(Thread::current());
  SymbolTableHash* new_table = new SymbolTableHash(new_size, END_SIZE, REHASH_LEN, true);
  _alt_hash = true;                       // Use alt hash from now on
  _local_table->rehash_nodes_to(Thread::current(), new_table);
  delete _local_table; _local_table = new_table;
  _rehashed = true; _needs_rehashing = false;
}
```

函数开头还有一条断言 `is_safepoint_safe()`，保证 ServiceThread 发起 rehash 时表不处于"搬运到一半"的状态。安全点机制见 [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)。

## Releasing Symbols

### Where Refcounts Go Down

一个符号的引用来源是"谁把它存进了持久字段"，因此减计数的位置恰好是那些字段的释放函数。类卸载链条由 `ClassLoaderDataGraph::do_unloading()` 驱动：

| 持有者 | 释放点 | 位置 |
| :-- | :-- | :-- |
| `Klass::_name` | `Klass::release_C_heap_structures()` | `oops/klass.cpp:154-156` |
| 常量池每个 UTF8 项 | `ConstantPool::unreference_symbols()` | `oops/constantPool.cpp:1400-1412` |
| 模块名 / 版本 / 位置 | `ModuleEntry::~ModuleEntry()` | `classfile/moduleEntry.cpp:308-314` |
| 模块 location | `ModuleEntry::set_location()` 换值前先减旧的 | `classfile/moduleEntry.cpp:56-59` |
| 包名 | `PackageEntry::~PackageEntry()` | `classfile/packageEntry.cpp:61-64` |
| 解析错误的 error 与 cause | `ResolutionErrorEntry::~ResolutionErrorEntry()` | `classfile/resolutionErrors.cpp:111-114` |
| 加载器约束表 | `LoaderConstraintTable::purge_loader_constraints()` | `classfile/loaderConstraints.cpp:291-296`，由 `systemDictionary.cpp:1569` 在卸载阶段调 |
| `ClassFileParser::_class_name` | 解析失败路径回退 | `classfile/classFileParser.cpp:5304`、`5421` |

第 7 行值得多看一眼：`purge_loader_constraints()` 内部调的是 `_loader_constraint_table->unlink(&purge)`，**这是 `unlink` 在本树里与符号生命周期相关的唯一残留用法**，走的是旧式 `Hashtable`；符号表本身早就没有这个方法了。

常量池侧的实现解释了**为什么只减 UTF8 而不动字符串**——`String` 常量指向这些符号，但当初并没有加计数（`oops/constantPool.cpp:1400-1413`）：

```cpp
// Iterate over symbols and decrement ones which are Symbol*s
// This is done during GC.
// Only decrement the UTF8 symbols. Strings point to
// these symbols but didn't increment the reference count.
void ConstantPool::unreference_symbols() {
  for (int index = 1; index < length(); index++) { // Index 0 is unused
    constantTag tag = tag_at(index);
    if (tag.is_symbol()) { symbol_at(index)->decrement_refcount(); }
  }
}
```

完整调用链是 `InstanceKlass::deallocate_contents()` → `release_C_heap_structures(true)` → `constants()->release_C_heap_structures()` → `unreference_symbols()`（`oops/instanceKlass.cpp:616`、`639`、`2977-3023`；`oops/constantPool.cpp:144-147`）。类加载器与卸载全流程见 [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)。

### What Actually Frees Memory

`refcount == 0` 只是"标了死"，`Symbol` 内容与 `Node` 内存还在原地。真正把内存还给 libc 的时机只有四个：

| 时机 | 实现 | 是否立刻回收 |
| :-- | :-- | :-- |
| 插入时 CAS 失败撞重 | `free_node()` → `FreeHeap()` | 立刻 |
| 快速插入顺路清理 | `internal_insert_get()` → `delete_in_bucket()` | 立刻 |
| ServiceThread 清理死项 | `clean_dead_entries()` 的 `BulkDeleteTask` | 分批 |
| 扩表搬运 | `unzip_bucket()` 遇 `dead_hash` 丢弃节点 | 搬运时 |

最后一行的证据在 `utilities/concurrentHashTable.inline.hpp:643-670`：搬运途中重新算哈希，若 `CONFIG::get_hash()` 报告死亡，就把这个节点从新表里抹掉并 `destroy_node`——这正是 `do_concurrent_work` 里 "prefer growing" 的另一面。死亡的定义与哈希取自同一个回调 `SymbolTableConfig::get_hash()`：先 `*is_dead = (value.refcount() == 0)`，死亡则返回 0，否则返回 `hash_symbol(value.bytes(), value.utf8_length(), _alt_hash)`（`classfile/symbolTable.cpp:127-134`）——一次调用同时完成"标死"与"算桶"。

永久符号**永远不会死**：计数是 `0xffff`，`decrement_refcount()` 遇到它就原样返回。而 `_arena` 在全文件里只有一个赋值点（`create_table()`，`classfile/symbolTable.cpp:213-216`），没有任何 delete 或 reset 路径，所以永久符号的内存事实上与进程同寿，`Afree` 的 LIFO 限制又让"归还"极少成功。

### Class Loader Leak Symptoms

把上面几条串起来，就得到"符号泄漏是类加载器泄漏的典型症状"的完整因果：

1. 类加载器还活着 → 它加载的每个 `InstanceKlass` 与常量池都还在 → 其中每个 UTF8 项各持有一次 `Symbol` 计数 → 符号计数不为 0 → 既不会被标死也不会被回收。
2. 泄漏的不只是那几百 KB 的 Klass 元数据，还有它引入的**全部名字空间**：一个动态代理 / Groovy 脚本 / ASM 生成的类往往带着一串独一无二的类名与方法名，这些字符串本身就是符号表里不可回收的条目。
3. 符号是 C 堆内存，不受 `-XX:MaxMetaspaceSize` 约束，堆转储里也看不到 → 表现为 **RSS 缓慢上涨而堆与 Metaspace 都正常**，这是最容易被误诊的一段。
4. 反过来，符号表的增长速度本身就是好探针：类数量稳定而符号表条目持续增加，说明不断有新名字被驻留且旧符号没释放。

`print_histogram()` 里的 `Percent removed = _symbols_removed / _symbols_counted` 正是为这个判断准备的（`classfile/symbolTable.cpp:922-950`）：`_symbols_counted` 在每轮 `clean_dead_entries()` 里累加扫描数，`_symbols_removed` 在每次 `item_removed()` 里累加（同文件 `82-83`、`228-231`）。健康进程的百分比应随卸载波动，长期贴着 0 说明根本没有东西在死。句柄与 JNI 引用对符号计数的影响见 [Handles](/docs/CS/Java/JDK/JVM/Handles.md)。

## Diagnostics

命令名必须从 `SymboltableDCmd::name()` 读，是 **`VM.symboltable`**（`services/diagnosticCommand.hpp:692-699`；注册 `services/diagnosticCommand.cpp:118`；实现 `classfile/symbolTable.cpp:954-965`，参数只有一个 `-verbose`，执行时投递 `VM_DumpHashtable::DumpSymbols` 到 VMThread）。

| 手段 | 命令或参数 | 位置 | 备注 |
| :-- | :-- | :-- | :-- |
| 统计表 | `jcmd <pid> VM.symboltable` | `symbolTable.cpp:591-602` | 桶数 / 条目数 / footprint / 桶长均值与最大 |
| 全量符号清单 | `jcmd <pid> VM.symboltable -verbose=true` | `symbolTable.cpp:655-681` | `VERSION: 1.1` 打头，含 Shared 与 Dynamic shared 两段 |
| 字符串表对照 | `jcmd <pid> VM.stringtable` | `diagnosticCommand.hpp:717` | 同一套统计格式 |
| 本地内存归因 | `jcmd <pid> VM.native_memory summary` 看 `Symbol` | `nmt/memTag.hpp:44`、`runtime/globals.hpp:584` | 开关是 product 级的 `-XX:NativeMemoryTracking=summary` |
| Metaspace 对照 | `jcmd <pid> VM.metaspace` | `memory/metaspace/metaspaceDCmd.hpp:47` | 符号**不**计入 Metaspace |
| 结构化日志 | `-Xlog:symboltable`，性能细节 `-Xlog:symboltable,perf` | `logging/logTag.hpp:203` | 全部构建 |
| 退出时打印两表统计 | `-XX:+PrintStringTableStatistics` | `globals.hpp:1038`、`init.cpp:224-227` | 名字只提 String，实际两张表都打 |
| 符号长度直方图 | `-XX:+PrintSymbolTableSizeHistogram` | `globals.hpp:1044`、`java.cpp:298-299` | develop，即 fastdebug 才有 |
| 退出时校验符号表 | `-XX:VerifySubSet=symbol_table` | `universe.cpp:1234-1236`、`1291-1294` | 需配合校验开关 |
| 初始桶数 | `-XX:SymbolTableSize=...` | `globals.hpp:1816-1818` | EXPERIMENTAL |

`-verbose` 输出的每行格式是 `<字节数> <引用计数>: "<内容>"`（`symbolTable.cpp:624-630`）。**引用计数长期为 1、内容又像生成类名**（`$$Lambda$1234`、`GroovyClassLoader$1`）的那批条目就是泄漏嫌疑对象。不带 `-verbose` 时重点看统计的最后三项：`Average bucket size` 正常但 `Maximum bucket size` 上百就是哈希退化，此时连 `VM.symboltable` 本身都会变慢。两个易踩的坑：`dump()` 对动态表用 `try_scan()`，扫不上会只打一行 `dump unavailable at this moment`，别误读成表是空的（`symbolTable.cpp:663-665`）；`VerifySubSet` 的取值是 **`symbol_table`**（带下划线），不是日志标签 `symboltable`，写错会被分词后的分支静默忽略（`universe.cpp:1219-1240`）。日志与 NMT 的完整能力见 [Serviceability](/docs/CS/Java/JDK/JVM/Serviceability.md)。

## SymbolTable versus StringTable

两张表现在是同一套 `ConcurrentHashTable` 机制的两个实例，但语义几乎处处相反：

| 维度 | SymbolTable | StringTable |
| :-- | :-- | :-- |
| 存什么 | VM 内部名字：类名、方法名、字段名、签名、模块名、包名 | `String.intern()` 后的 `java.lang.String` 实例 |
| 表值类型 | `Symbol*`（`symbolTable.cpp:125`） | `WeakHandle`（`stringTable.cpp:175`） |
| 容器 | `ConcurrentHashTable<SymbolTableConfig, mtSymbol>`（`symbolTable.cpp:75`） | `ConcurrentHashTable<StringTableConfig, mtSymbol>`（`stringTable.cpp:94`） |
| 数据本体在哪 | C 堆 malloc，或永久符号的 `Arena` | Java 堆；表侧只存 `WeakHandle`，oop 放 weak OopStorage `"StringTable Weak"`（`stringTable.cpp:300`） |
| NMT 归属 | `Symbol`（`mtSymbol`） | 表节点与 OopStorage **也标 `mtSymbol`**，与符号表共用标签，NMT 里分不开 |
| 引用强度 | 手动引用计数，`0xffff` 为永久 | 弱引用，GC 回收字符串后条目自动变死 |
| 死亡判据 | `refcount() == 0`（`symbolTable.cpp:409-411`） | `WeakHandle::peek() == nullptr`（`stringTable.cpp:177-181`） |
| 谁触发清理 | 类卸载 + 插入撞死 + 负载超阈值 | GC 经 `register_num_dead_callback(&gc_notification)` 上报死项数（`stringTable.cpp:301`、`617-636`） |
| 能否被卸载 | 非永久符号可以，随类加载器一起 | 随 GC，与类加载器无直接绑定 |
| GC 是否扫它 | 不扫；仅安全点由 `symbols_do()` 遍历给堆转储用（`symbolTable.cpp:273-281`、`services/heapDumper.cpp:2458`） | 是 GC 的 root 来源之一，死项由 GC 周期暴露 |
| 哈希输入 | UTF-8 **字节**（`javaClasses.hpp:178`） | 按码点，或 UTF-8 解码后按码点（`javaClasses.hpp:187`），oop 走 `String.hashCode()` 快路径 |
| 内容比较 | `memcmp`，即 `Symbol::equals` | `java_lang_String::equals`，要处理 LATIN1/UTF16 coder（`stringTable.cpp:156-168`） |
| 初始桶数 | `SymbolTableSize` 默认 32768，EXPERIMENTAL | `StringTableSize` LP64 默认 65536，非实验参数（`globals.hpp:110`、`1811-1813`） |
| 共享归档表 | `OffsetCompactHashtable` 两个实例 | `SharedStringTable`，仅 `INCLUDE_CDS_JAVA_HEAP` |
| 诊断命令 | `jcmd <pid> VM.symboltable` | `jcmd <pid> VM.stringtable` |

两处值得停下来想的结论。**其一，"能不能卸载"是两张表最根本的分野**：`Symbol` 的生死只取决于有没有人还指着它，JVM 能在类卸载那一刻精确释放名字；`String` 的生死取决于 GC 何时回收，所以 `intern()` 出来的字符串身份**不稳定**——它可能只是堆里一个普通对象，被回收后下次 `intern()` 返回另一个地址。符号则只要还活着，地址就是它身份的组成部分（`fast_compare()` 敢比地址）。软/弱/虚引用这一族的差别见 [Basic/Ref](/docs/CS/Java/JDK/Basic/Ref.md)。

**其二，两者对同一串文本会算出不同哈希**：`SymbolTable` 的 `hash_symbol` 把指针强转成 `const jbyte*` 走原始字节路径，`StringTable` 对 `SymbolStr`/`UTF8Str` 走 `const char*` 重载、内部先 `UTF8::unicode_length()` 再按码点累加。纯 ASCII 名字两者恰好相等，非 ASCII 名字（中文类名、含 emoji 的字符串常量）两者不同。这不是 bug，但若手工构造 key 想让两张表命中同一个桶，得记住这点。

字符串驻留的 Java 侧行为与 intern 性能陷阱见 [Basic/String](/docs/CS/Java/JDK/Basic/String.md)，本篇不重复。

## Links

- [ClassFile](/docs/CS/Java/JDK/JVM/ClassFile.md)
- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [Method](/docs/CS/Java/JDK/JVM/Method.md)
- [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)

## References

- [The Class File Format, JVM Specification SE 21](https://docs.oracle.com/javase/specs/jvms/se21/html/jvms-4.html)
- [jcmd, JDK 21 Tools Reference](https://docs.oracle.com/en/java/javase/21/docs/specs/man/jcmd.html)
- [Native Memory Tracking, JDK 21 JVM Tools Guide](https://docs.oracle.com/en/java/javase/21/vm/native-memory-tracking.html)
- [JVM Tool Interfaces, JDK 21 JVM Tools Guide](https://docs.oracle.com/en/java/javase/21/vm/tools.html)
- [JEP 310: Application Class-Data Sharing](https://openjdk.org/jeps/310)
- [JEP 350: Dynamic CDS Archives](https://openjdk.org/jeps/350)
