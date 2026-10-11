## Introduction

HotSpot 的 GC 会**移动对象**。压缩式回收之后，对象在堆上的地址换了，而 C++ 代码栈上那个 `oop` 变量还停在旧地址——它不会有任何机制通知你"我失效了"。所以 HotSpot 内部传对象从来不以裸 `oop` 为准绳，而是以 **handle** 为准绳：handle 不存对象地址，存的是"装着地址的**槽位**（cell）"的地址；GC 更新槽位里的值，槽位地址本身不变，于是栈上的 handle 永远有效。

没有 handle 会怎样出错，看这个时间线：

```cpp
// 伪代码：展示裸 oop 的悬垂过程
oop obj = create_some_object(THREAD);   // obj 是堆上地址 0xABC0
// ... 调用链深处又发生了一次分配，Eden 满了，触发一次带压缩的 GC ...
// ... GC 把对象从 0xABC0 搬到了 0x1234，并更新了所有它知道的根 ...
obj->print();                           // 错：obj 是栈上的裸指针，GC 不知道要更新它
                                        // 读到的是一块已失效甚至已复用的内存
```

`obj` 是 C++ 栈上的局部变量，不在任何 OopMap / 句柄区里，GC 的根遍历**扫不到它**，自然无从更新。修正方式就是给它套一层间接：

```cpp
Handle h(THREAD, create_some_object(THREAD));
// GC 之后依然正确：h 指向的 cell 位于线程句柄区，
// Thread::oops_do 会在 GC 时走到这个 cell 并更新其内容
h->print();
```

`runtime/handles.hpp` 文件头的注释把这条纪律说得很直白："In order to preserve oops during garbage collection, they should be allocated and passed around via Handles within the VM. A handle is simply an extra indirection allocated in a thread local handle area."（`runtime/handles.hpp:36-40`）并且要求 "oop parameters and return types should be Handles whenever feasible"（`:44-45`）。

本篇讲 HotSpot **内部**这套机制：三层间接、句柄区的数据结构与生命周期管理、每线程的几种存储、JNI 引用表的真实实现，以及代价。与相邻笔记的分工：**程序员可见的 JNI API 规范与调用惯例**在 [JNI](/docs/CS/Java/JDK/Basic/JNI.md)；Java 栈帧与 OOPMap 的根发现机制在 [frame](/docs/CS/Java/JDK/JVM/frame.md) 与 [Stack](/docs/CS/Java/JDK/JVM/Stack.md)；`WeakReference`/`SoftReference` 等 **Java 侧引用语义**在 [Ref](/docs/CS/Java/JDK/Basic/Ref.md)；搬移对象的算法本身在 [GC](/docs/CS/Java/JDK/JVM/GC/GC.md) 子树。

## Version Baseline

> [!NOTE]
> 本篇锚定 **jdk-27-ga**（`src/hotspot` 全量核实，行号均以该 tag 为准）。这是 JVM 子树里**旧书与现实差距最大**的一页，以下每一条都在本树 grep 过：
> - 老材料里 `Handle` 的成员写成 `oopDesc** _handle`。JDK 27 是 `oop* _handle`（`runtime/handles.hpp:67`）。在 product 构建里二者等价（`oop` 就是 `oopDesc*` 的 typedef，`oops/oopsHierarchy.hpp:43`），但 `CHECK_UNHANDLED_OOPS` 构建里 `oop` 是**包装类**（`:81`），二者不再等价——统一写 `oop*` 才是对的。
> - 老句柄区是自研的 `AbstractHeader` / `Block` 链表，带 `_begin` / `_top` / `_size`、`alloc_block`、`handle_size`、`BLOCK_SIZE` 等符号——**这些名字在 JDK 27 树里一个都不存在**（全树 grep 仅命中 `indexSet` 与 `g1MonotonicArena` 的无关同名函数）。`HandleArea` 现在是 `Arena` 的子类（`runtime/handles.hpp:179`），槽位从 Arena 的 Chunk bump 分配。
> - `OWNING_HANDLE` / `OWNING_COMPILEDHANDLE` / `OverlayHandleArea` / `NO_HANDLE_MARK_FRAME` / `CheckHandleArea` / `SkipHandleAreaClean`：全树 grep 均**无命中**，属已被删除的历史机制，本篇不涉及。
> - 老材料里 JNI 局部引用编码为 `(block << 5) + index`；JDK 27 的局部 `jobject` **直接就是槽位地址**，用指针低 2 bit 做类型 tag（`runtime/jniHandles.hpp:65-71`）。
> - `EnsureLocalCapacity` 的老实现会**预分配**句柄块；JDK 27 的实现只做一次上限校验、不分配任何内存（`prims/jni.cpp:711-721`）。
> - JNI 全局 / 弱全局引用早已收编进 `OopStorage`（`gc/shared/oopStorage.hpp`），不再是老式的 `oopHandle` 块链表。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Three-Level Indirection

### Handle Is a Pointer to an oop

`Handle` 类只有一个数据成员：

```cpp
// runtime/handles.hpp:65-105 节选
class Handle {
 private:
  oop* _handle;

 protected:
  oop     obj() const  { return _handle == nullptr ? (oop)nullptr : *_handle; }
  oop     non_null_obj() const { assert(_handle != nullptr, "resolving null handle"); return *_handle; }
 public:
  Handle()             { _handle = nullptr; }
  inline Handle(Thread* thread, oop obj);

  oop     operator () () const  { return obj(); }          // h()   -> 穿透两层取 oop
  oop     operator -> () const  { return non_null_obj(); } // h->   -> 再经 oop 到 oopDesc
  bool operator == (oop o) const          { return obj() == o; }
  bool operator == (const Handle& h) const { return obj() == h.obj(); }
  ...
};
```

三层间接的完整链条是：**栈上的 `Handle` 对象 → `oop*` 指向句柄区里的一个 cell → cell 里存的 `oop` 指向堆上对象**。

```text
   C++ 栈                线程句柄区 Arena 的 chunk            Java 堆
 +----------+           +-------------------+           +-----------+
 | Handle h |  oop*     | cell (一个字宽)     |   oop     |  oopDesc  |---> 对象
 | _handle  |---------> | *_handle = 0x1234 |---------> |           |
 +----------+   第1层    +-------------------+   第2层    +-----------+
                  GC 更新的是 cell 的内容（第2层的值），cell 地址不变，
                  所以 h 本身、h()、h-> 全程不需要重新取。
```

几个关键行为：

- **比较穿透**：`operator==` 两侧都比的是 `obj()`（cell 内容），不是 cell 地址。两个不同 cell 装同一个 oop，则两个 handle 相等——"make h3 refer to same indirection as h1" 那种赋值（`Handle` 默认的位拷贝赋值复制 `_handle` 指针）其实是**共享同一个 cell**，此后 `h3.replace(x)` 会同时改掉 `h1`（文件头注释 `:53` 说的就是这个语义）。
- **null 特例**：`Handle(thread, nullptr)` **不分配 cell**，`_handle` 直接为 `nullptr`（`runtime/handles.inline.hpp:37-44`）；`is_null()` 判的是 cell 是否存在，不是对象是否为空。
- **`replace` 不走写屏障**：`Handle::replace` 的注释明确说明句柄是线程私有、由 `Thread::oops_do` 遍历而非并发遍历，所以裸写 `*_handle = obj` 即可，与 `OopHandle::replace` 必须走屏障形成对照（`runtime/handles.inline.hpp:46-52`）。
- **raw 接口**：`raw_value()` 与 `Handle(oop*, bool)` 构造器是为 `JavaCalls` 快速转换和静态数据结构造 handle 用的，注释自称 "use very sparingly"（`handles.hpp:94-102`）。

### Derived Types and Two Special Handles

`DEF_HANDLE` 宏按 oop 类型派生出带类型检查的 handle：`InstanceHandle`、`ArrayHandle`、`ObjArrayHandle`、`TypeArrayHandle`、`StackChunkHandle`（`handles.hpp:108-131`）。构造时 assert 实际类型（`handles.inline.hpp:55-63`），`operator()` / `operator->` 返回精确的 `xxxOop`，省掉调用方到处 downcast。

另一族是 **Metadata Handle**（`MethodHandle` / `ConstantPoolHandle`，注意这是 C++ 运行时的类，与 `java.lang.invoke.MethodHandle` 无关）。它们**不放在句柄区**——元数据不是 GC 搬移的对象，这类 handle 要防的是 **RedefineClasses 把还有人在用的元数据回收掉**（`handles.hpp:134-137`）。机制是把裸指针登记进线程的 `_metadata_handles`（`GrowableArray<Metadata*>`，构造时 `push`、析构时 `find_from_end + remove_at`，`handles.inline.hpp:66-74` 与 `handles.cpp:52-97`），类重定义清理时走 `Thread::metadata_handles_do`（`runtime/thread.cpp:464-471`）扫这些登记。注释还提醒 Metadata Handle 要以 const 引用传参，避免拷贝构造/析构的登记开销（`handles.hpp:136-137`）。

## HandleArea and HandleMark

### The Handle Area Is an Arena

JDK 27 的 `HandleArea` 直接继承通用 Arena 分配器：

```cpp
// runtime/handles.hpp:179-214 节选
class HandleArea: public Arena {
  friend class HandleMark;
  friend class NoHandleMark;
  friend class ResetNoHandleMark;
 public:
  HandleArea(MemTag mem_tag) : Arena(mem_tag, Tag::tag_ha, Chunk::tiny_size) { ... }
 private:
  oop* real_allocate_handle(oop obj) {
    oop* handle = (oop*)internal_amalloc(oopSize);   // 一个字宽
    *handle = obj;
    return handle;
  }
 public:
  void oops_do(OopClosure* f);   // GC 支持
};
```

- **cell 大小**：`oopSize = sizeof(char*)`（`utilities/globalDefinitions.hpp:238`），LP64 下 8 字节——一个 cell 就是一个指针宽。
- **chunk 布局**：Arena 是 `Chunk` 单链表，活动分配点由 `_chunk` / `_hwm`（high water mark）/ `_max` 三个字段刻画（`memory/arena.hpp:135-144`）。`HandleArea` 的**首块是 tiny**（256 − slack 字节，`Chunk::tiny_size`，`arena.hpp:75`；slack 在 LP64 下为 40），按 `internal_amalloc` 逐 8 字节 bump；空间用尽走 `Arena::grow`，新块尺寸 `MAX2(ARENA_ALIGN(x), Chunk::size)`——即句柄区**第一个溢出块就是 32K 级别**（`arena.hpp:77`、`arena.cpp:330`），约 4000 个 cell。NMT 归属用专门的 `Tag::tag_ha`（"Handle area"，`arena.hpp:108`）。
- **GC 遍历**：`HandleArea::oops_do` 先扫当前 chunk 的 `bottom.._hwm`，再扫所有已填满的历史 chunk（`handles.cpp:100-120`）。入口在 `Thread::oops_do_no_frames`（`runtime/thread.cpp:427-431`）。
- **调试断言**：`allocate_handle` 强制要求当前嵌套深度 `_handle_mark_nesting > 1`，否则报 `"memory leak: allocating handle outside HandleMark"`；`NoHandleMark` 作用域内分配直接 assert 失败（`handles.cpp:32-48`）。这两条断言把"handle 只在 HandleMark 内分配"的纪律从口头约定变成了 debug 构建的硬门禁。

### HandleMark as a Save and Restore RAII

`HandleMark` 析构时把 Arena 回滚到构造时的水位，一次 pop 掉作用域内分配的所有 handle：

```cpp
// runtime/handles.hpp:239-270 节选
class HandleMark {
 private:
  Thread *_thread;              // thread that owns this mark
  HandleArea *_area;            // saved handle area
  Chunk *_chunk;                // saved arena chunk
  char *_hwm, *_max;            // saved arena info
  size_t _size_in_bytes;        // size of handle area
  HandleMark* _previous_handle_mark;  // 链表挂到线程
  ...
};
```

- 构造 `initialize(thread)`：抄走 `_chunk/_hwm/_max/_size_in_bytes` 四个字段，`_handle_mark_nesting++`，并把自己链接进 `thread->last_handle_mark()`（`handles.cpp:122-137`）。
- 析构 `~HandleMark()` 调 `pop_and_restore()`：若有新 chunk 被挂进来，先 `chop_later_chunks()`（`Chunk::next_chop` 归还 chunk 池），再把三个水位字段写回（`handles.inline.hpp:86-99`）。**没有 free 动作**——这就是 Arena 式回收：回滚指针即"释放"。
- 每个 `Thread` 在**构造函数**里就 `new HandleMark(this)` 压了一个终身影子 mark（`runtime/thread.cpp:86`），它是全线程句柄链的锚点；这也是 `HandleMark` 不能声明为 `StackObj`、要自带 `operator new`（`AllocateHeap(size, mtThread)`）的原因（`handles.hpp:236-238`、`handles.cpp:162-176`）。线程销毁时 `delete handle_area()`（`thread.cpp:295`）。
- **越界陷阱**：`handles.hpp:224-231` 的注释给了一个反面教材——内层 `HandleMark` 作用域结束后，其作用域内分配的 handle 全部作废，外层提前声明的空 `Handle` 若指向这些 cell 就成了"悬垂的 cell 指针"。需要跨边界存活就转成裸 `oop`（前提是你保证中间不再触发该对象被搬移的逻辑）或转成 JNI 局部引用。

### Cheaper Cleanup and Allocation-Disabled Markers

- **HandleMarkCleaner**：`HandleMark` 的快版。它不自己存现场，而是**赌栈的更深处已经有一个 HandleMark**（约定俗成地是 `JavaCalls::call_helper` 那个），构造时对 `thread->last_handle_mark()` 调 `push()`、析构时 `pop_and_restore()`（`handles.hpp:303-314`、`handles.inline.hpp:79-108`）。Zero 解释器在每个 Java 方法调用边界用它批量回收本帧产生的句柄（`interpreter/zero/bytecodeInterpreter.cpp:2872`），并在不该被回收的窗口里临时断开这条链（`:3009`、`:3070` 的注释）。
- **NoHandleMark**：仅 ASSERT 生效的"此地禁配句柄"标记，用于不该触碰句柄区的段（如 C1 的 stub 生成，`c1/c1_Runtime1.cpp:677`）。
- **ResetNoHandleMark**：临时解除 `NoHandleMark` 的禁配状态再恢复。注释点明动机：**`_thread_in_native` 状态的线程不得创建 handle**，经 `ThreadInVMfromNative` 短暂回 VM 时用它开一个授权窗口（`handles.hpp:288-301`、`handles.cpp:194-204`）。
- **ZapVMHandleArea**（develop flag，debug 构建默认 true，`runtime/globals.hpp:473`）：`~HandleMark` 里把刚回滚掉的那段内存填 `badHandleValue`（0xBC，`utilities/globalDefinitions.hpp:1047`；填充满写 `handles.cpp:144-149`），让"使用已被 HandleMark 回收的句柄"在 debug 构建里立刻爆炸。

## The Handle Areas Attached to a Thread

`Thread` 基类构造时为每个线程（包括 VM 内部线程）配齐四件套（`runtime/thread.cpp:73-86`）：

| 成员 | 类型 | 谁在用 | 生命周期粒度 |
| :-- | :-- | :-- | :-- |
| `_resource_area` | `ResourceArea*`（Arena） | 非 oop 的临时 C++ 对象 | `ResourceMark` |
| `_handle_area` | `HandleArea*` | VM 内部所有 `Handle` | `HandleMark` |
| `_metadata_handles` | `GrowableArray<Metadata*>*` | `MethodHandle` / `ConstantPoolHandle` 登记表 | handle 构造/析构 |
| `_last_handle_mark` | `HandleMark*` | HandleMark 侵入式链表锚点 | 线程存续 |

声明处见 `runtime/thread.hpp:234`（`_last_handle_mark`）、`:519-521`（`_handle_area` / `_metadata_handles`），访问器 `:399-403`。

`JavaThread` 在此之上**另起一套**给 JNI 用（`runtime/javaThread.hpp:158-162`）：

```cpp
// Active_handles points to a block of handles
JNIHandleBlock* _active_handles;
// One-element thread local free list
JNIHandleBlock* _free_handle_block;
```

- `JavaThread` 一进入运行就分配首个 `JNIHandleBlock`（`javaThread.cpp:623`），线程退出时以 `thread=nullptr` 方式 `release_block`——**归还而不是压 free list**，直接 `delete`（`javaThread.cpp:813-821`、`jniHandles.cpp:352-387`）。
- `_free_handle_block` 是**单元素线程本地链表**：还回来的块先攥在自己手里，下次 `allocate_block` 免锁复用（`jniHandles.cpp:322-326`）。
- 二者都有对应的 GC 入口：`JavaThread::oops_do_no_frames` 先走基类的句柄区，再走 `active_handles()->oops_do(f)`（`javaThread.cpp:1244-1250`）。

**为什么 JNI 帧必须用独立的 `_active_handles` 而不是复用 `_handle_area`**：

1. **失效时机不同**。Arena 句柄被 `HandleMark` 按 C++ 作用域成批作废，而局部引用（local reference）的生命周期是 **native 方法的一次调用帧**，还允许 native 代码用 `DeleteLocalRef` / `PushLocalFrame` / `PopLocalFrame` 精确操纵——需要一个能支持"按引用删除、按帧整段重置"的独立结构。
2. **所有权暴露给了 VM 之外**。`jobject` 会被 native 代码存进自己的全局变量、算术玩弄；句柄区的 cell 被 `HandleMark` 回滚后地址可能立刻重分配，`jobject` 若指向那里就是不可检测的野指针。`JNIHandleBlock` 的块只有整链释放，配合低 2 bit tag 与 free list 位才谈得上 `-Xcheck:jni` 的有效性校验。
3. **线程状态约束**。`ResetNoHandleMark` 的注释（`handles.hpp:288-290`）规定 `_thread_in_native` 不得创建 handle——但 JNI 线程恰恰大量活动发生在 native 态与 in-Java 的**包装器**边界上，引用表由 native wrapper 在 `_thread_in_java` 的窗口里维护，两套机制的触达状态不同。
4. **批量重置的粒度不同**。`JNIHandleMark`（`javaThread.hpp:1287-1293`）提供的是 `push/pop_jni_handle_block`——换一整块引用链表而不是回滚水位（`javaThread.cpp:1222-1241`），给"在 VM 线程上临时执行一段 JNI 逻辑"这类场景用（如 `compiler/compileBroker.cpp:1998`）。

对象在两套体系里的摆渡接口是 `JNIHandles::make_local` 与 `JNIHandles::resolve`（`runtime/jniHandles.hpp:85-97`）。

## Internal Implementation of JNI Reference Tables

与 [JNI](/docs/CS/Java/JDK/Basic/JNI.md) 的分工：那篇讲程序员可见的引用语义与 API 用法；本节只回答"`jobject` 在 HotSpot 里**到底是什么位型**、三种引用各存进哪张表"。

### The Two-Bit Tag Packed into jobject

```cpp
// runtime/jniHandles.hpp:65-78
enum TypeTag {
  local = 0b00,
  weak_global = 0b01,
  global = 0b10,
};
static const uintptr_t tag_size = 2;
static const uintptr_t tag_mask = ((1u << tag_size) - 1u);
```

注释解释了这个设计的动机："Low tag bits in jobject used to distinguish its type. **Checking the underlying storage type is unsuitable for performance reasons**."（`:65-66`）——resolve 一个 jobject 时不必反查它属于哪张表，看两位就够。三种 tag 对应的 `*_ptr` 提取全是加减法（`jniHandles.inline.hpp:51-67`）。

### Local References and the JNIHandleBlock Chain

`JNIHandleBlock` 就是句柄区思想的定长版（`jniHandles.hpp:137-190`）：

```cpp
enum SomeConstants {
  block_size_in_oops  = 32                    // Number of handles per handle block
};
uintptr_t       _handles[block_size_in_oops]; // The handles
int             _top;                         // Index of next unused handle
int             _allocate_before_rebuild;     // Number of blocks to allocate before rebuilding free list
JNIHandleBlock* _next;                        // Link to next block
// 仅链头块使用的字段：
JNIHandleBlock* _last;                        // Last block in use
JNIHandleBlock* _pop_frame_link;              // Block to restore on PopLocalFrame call
uintptr_t*      _free_list;                   // Handle free list
```

要点逐个对应源码：

- **jobject 就是槽位地址**：`allocate_handle` 里 `return (jobject) handle;`，`handle` 是 `&(_last->_handles[_top++])` 或 free list 摘下来的槽（`jniHandles.cpp:446-450`）。因为指针天然 4/8 字节对齐，低 2 bit 恒为 0，正好充当 `local = 0b00` tag——老书里 `(block << 5) + index` 的编码已不存在。
- **块内 free list 与 oop 区分**：`_handles[i]` 既能装 oop 又能装链表指针，用 bit0 tag 区分（`tag_free_list` / `is_tagged_free_list`，`jniHandles.cpp:283-296`），并有一条 `STATIC_ASSERT(sizeof(oop) == sizeof(uintptr_t))` 兜底。
- **`DeleteLocalRef` 只清槽不还位**：`destroy_local` 仅 `*local_ptr(handle) = nullptr`（`jniHandles.inline.hpp:120-124`）。空槽只有在链上所有块**填满之后**，由 `rebuild_free_list()` 统一扫描重新串成 free list（`jniHandles.cpp:427-495`）——且带一个启发式：若回收到的空槽不足一半，接下来先追加若干新块再考虑重扫，避免反复 O(链长) 扫描。
- **越界扩容**：`_last` 满且无空槽，`allocate_block(caller)` 追加新块（先查线程本地 `_free_handle_block`，命中则免分配，`jniHandles.cpp:318-347`）。`make_local` 失败路径（`RETURN_NULL`）支持返回 `nullptr` 而不是 `vm_exit_out_of_memory`（`jniHandles.cpp:72-80`、`:57-71`）。
- **GC 遍历跳过死槽**：`oops_do` 沿 `_next` 走链、再沿 `pop_frame_link` 走下一层帧，且只处理 `_handles[0.._top)` 中非 0、非 free-list-tag 的项（`jniHandles.cpp:391-424`）。

`PushLocalFrame` / `PopLocalFrame` 的实现即"换链头"：push 分配新块并把旧链头挂进 `_pop_frame_link`；pop 恢复旧链头并 `release_block` 整段释放（`prims/jni.cpp:625-664`）。`release_block` 的注释坦承这是防呆设计："This way code will still work if PopLocalFrame is called without a corresponding PushLocalFrame call."（`:651-652`）。

### Global and Weak Global References in Two OopStorage Tables

```cpp
// runtime/jniHandles.cpp:52-55
void jni_handles_init() {
  JNIHandles::_global_handles = OopStorageSet::create_strong("JNI Global", mtInternal);
  JNIHandles::_weak_global_handles = OopStorageSet::create_weak("JNI Weak", mtInternal);
}
```

`make_global`：从 `OopStorage::allocate()` 要一个 `oop*` 槽，`NativeAccess<>::oop_store` 写入（走 GC 屏障，因为 OopStorage **可能被并发标记遍历**——这正是它与句柄区 `replace` 无屏障的镜像对照），然后把槽指针 `+ TypeTag::global` 当作 jobject 返回（`jniHandles.cpp:82-103`）。`make_weak_global` 同构，差异全部在访问装饰器：写读都用 `ON_PHANTOM_OOP_REF`，即**幽灵引用**语义，配合 `weak_oops_do` 由 GC 在对象不可达时把槽清 0（`:105-122`；`is_weak_global_cleared` 于 `:126-130`）。`destroy_global` 写空后 `release` 归还槽位（`:141-159`）。

OopStorage 自身的定位见 `gc/shared/oopStorage.hpp:38-62` 的注释："OopStorage supports management of **off-heap references** to objects allocated in the Java heap"，内部按 Block（含 `oop[]` + 分配位图）组织，设计目标就是"分配/释放、GC 并发遍历、非 GC 工具 safepoint 遍历"四共。JNI 全局表只是它众多用户之一。

引用类型判别走 `handle_type`（`GetObjectRefType` 的底座，`jniHandles.cpp:181-203`）：先看 tag，再查 `OopStorage::allocation_status == ALLOCATED_ENTRY`——这意味着**被 DeleteGlobalRef 删除的全局引用会被判为 invalid** 而不是错误地解引用。局部引用的判定 `is_local_handle` 沿 `active_handles` 链加所有 `pop_frame_link` 检查指针是否落在某个块的 `_handles[0.._top)` 内（`:205-218`）；`is_frame_handle` 兜底识别"指向当前线程栈内 oop 变量的裸指针"这一历史用法（`:225-234`）。

### Why EnsureLocalCapacity and DeleteLocalRef Still Matter

JDK 27 的 `EnsureLocalCapacity` 只有一条实现（`jni.cpp:711-721`）：`capacity >= 0 && (MaxJNILocalCapacity <= 0 || capacity <= MaxJNILocalCapacity)` 则 `JNI_OK`，否则 `JNI_ERR`。**不预分配任何块**——`MaxJNILocalCapacity` 默认 65536（`runtime/globals.hpp:797-800`，`<=0` 表示无限），同样的上限校验也出现在 `PushLocalFrame`（`jni.cpp:625-640`）。它仍然存在的原因：

1. **可移植契约**：局部引用数量在别的 JVM/别的时代可能是**硬上限**，规范语义要求"超出容量时此调用是唯一合法的预报错点"；HotSpot 用一条 flag 校验兑现语义，代码换 JVM 不炸。
2. **显式失败点**：不校验的话，超大的 `PushLocalFrame(N)` 会在后续每次 `NewObject` 时随机爆 native OOM；校验让失败发生在意图表达处。
3. **容量仍是真资源**：自动增长的只是"每次一块"，块内存是 `mtInternal` 的 native 堆且**每块都在 GC roots 里**。`DeleteLocalRef` 在长循环里依然必需——不清零的槽位（a）让对象一直被当局部引用根持有，（b）在整链填满前不进入 free list，表现为句柄链持续变长。HotSpot 无法替你推断"这个引用之后不再用了"，只能靠显式删除。

## What -Xcheck:jni Verifies

flag `CheckJNICalls`（product bool，默认 false，"Verify all arguments to JNI calls"，`runtime/globals.hpp:791-792`）由 `-Xcheck:jni` 置位；若构建未编入 `INCLUDE_JNI_CHECK` 则打 warning 后忽略（`runtime/arguments.cpp:2372-2378`）。开启后的实际改动：

- **换函数表**。`jni_functions()` 在 `CheckJNICalls` 时返回 `jni_functions_check()`（`prims/jni.cpp:3513-3518`），即 `prims/jniCheck.cpp:2061` 的 `checked_jni_NativeInterface`——200 多个入口全部换成包了一层校验的 `check_*` 函数。
- **参数有效性校验**：以 `check_pending_exception` 为例，每次调用检查线程上是否有**未检查就发起下一次 JNI 调用**的挂起异常，命中则 `NativeReportJNIWarning` 打 `"JNI call made with exception pending"` 或 "without checking exceptions when required to from ..." 并打印 JNI 栈（`jniCheck.cpp:186-197`）。它的注释逐字引用了 JNI 规范中"哪些函数必须由程序员主动查异常"的条款（`:164-182`）。引用槽位的有效性用上一节的 `is_local_handle` / `is_global_handle` / `is_weak_global_handle` 判定。
- **降级快速路径**：`UseFastJNIAccessors` 生成的快速 GetField 入口**只在未开 check 时**才被打进函数表（`jni.cpp:3475`），保证字段访问也走校验版本。
- **周期性守护**：`JniPeriodicChecker::engage()` 在 `CheckJNICalls` 时挂一个周期任务，用于侦测"JNI 应用引发的环境破坏"——注释点名了信号处理劫持与 `va 0x0` 被 mmap 覆盖之类的场景（`runtime/jniPeriodicChecker.hpp:29-35`、`runtime/threads.cpp:854`）。
- **警告而非崩溃**：校验失败默认 `WARNING in native method: ...` 打到 tty 并尽量继续（`jniCheck.cpp:143` 的 `NativeReportJNIWarning`），与致命错误区分；`resolve_external_guard` 则把"外部传来的可疑引用"统一解析为 null 处理（`jniHandles.cpp:124-132`）。

`VerifyJNIFields`（develop，debug 构建默认 true）是另一条独立的字段 ID 校验开关（`globals.hpp:1158`），与 `-Xcheck:jni` 互补。

## Costs and Workarounds

### Handle Leaks and Area Growth

句柄区没有逐项释放，一切清理都押在 `HandleMark` 的水位回滚上。典型事故形态是**长循环 / 长生命周期 native 帧**里配 handle：`JNI_OnLoad`、agent、或一个大解析函数内每次迭代 `Handle h(THREAD, ...)` 而不套内层 `HandleMark`，Arena 就以 32K 一块的速度持续挂 chunk，且每个 cell 都是活引用根，把本该回收的对象成批钉住。debug 构建的 `"memory leak: allocating handle outside HandleMark"` 断言（`handles.cpp:33-36`）拦截的是更恶劣的"根本不在任何 HandleMark 里"的场景。标准解法：

```cpp
for (...) {
  HandleMark hm(THREAD);        // 每轮迭代回滚水位
  InstanceHandle h(THREAD, compute(THREAD));
  use(h);
}                               // h 连同本轮 cell 一起作废
```

若只需要一个值跨边界存活，按 `handles.hpp:232-234` 的注释转成裸 `oop` 或局部 JNI 引用。

### Steady-State Overhead

一次 handle 分配是 bump 指针加一次写（两条指令级操作）；一次 `HandleMark` 构造/析构是 5 个字段的保存恢复加链表摘挂，析构时若期间开过新 chunk 还要 `Chunk::next_chop` 归还 chunk 池（`handles.cpp:155-160`）。对绝大多数 runtime 路径这可以忽略，但：

- **能免则免**：`HandleMarkCleaner` 用"借用深层已有现场"的方式把构造侧开销摊成零，适合解释器帧边界这种高频点（`handles.hpp:303-306`）。
- **C1 式硬约束**：确定不配句柄的路径用 `NoHandleMark` 把约定固化为断言（`c1_Runtime1.cpp:677`）。

### Cross-Frame and Long-Lived Use of OopHandle

- **native 边界**：交给外部代码的只能是引用表里的 `jobject`，理由见"线程身上的几套存储"一节。
- **OopHandle 解决的是第三个问题**：既不是"当前 C++ 作用域内保命"（Handle 管这个），也不是"给 native 代码用"（引用表管这个），而是**存进堆外长生命周期数据结构**的引用——`OopHandle` 包裹一个指向 `OopStorage` 槽位的 `oop*`（`oops/oopHandle.hpp:39-76`），槽位地址自分配至 `release()` 期间稳定，可以嵌在 Metaspace / CHeap 对象里；访问必须走带屏障的 `NativeAccess`（`resolve`/`peek`/`replace`/`xchg`/`cmpxchg`，`oopHandle.inline.hpp:32-77`），因为槽位**会被并发遍历**。用户包括 `ClassLoaderData` 的 `ChunkedHandleList _handles`——持有常量池数组、Module 等"与 ClassLoader 同生命周期"的对象（`classfile/classLoaderData.hpp:70-96,130`），以及 `ModuleEntry::_module_handle`（`classfile/moduleEntry.hpp:67-68`）、JNI 全局表本身。
- 三种机制对照：

| 维度 | Handle + HandleArea | JNI 引用表 | OopHandle + OopStorage |
| :-- | :-- | :-- | :-- |
| 存储 | 线程私有 Arena | 线程私有 32 槽块链 | 全局堆外表，分块位图 |
| 回收 | HandleMark 水位回滚 | DeleteLocalRef / 帧弹出 / release | 显式 `release(storage)` |
| 遍历屏障 | 无（safepoint 下独占）| 局部无；全局/弱有 | 有（支持并发遍历） |
| 暴露给 | VM 内部 C++ 代码 | native 代码（`jobject`） | VM 内长期数据结构 |
| 跨线程 | 禁止（cell 随 mark 作废） | local 禁，global/weak 可 | 可（原子接口齐备） |

### Debug vs Release and the Retired OWNING_HANDLE

老材料里的句柄"所有权"追踪宏 `OWNING_HANDLE` / `OWNING_COMPILEDHANDLE`（debug 下让 handle 赋值检查源 handle 是否 owned，用于抓"跨作用域复制 handle"错误）**在 JDK 27 全树 grep 无命中，连同旧句柄区实现一起被删除**。当前的 debug/release 差异由这一组机制承担：

| 开关 / 类 | 生效条件 | 行为 |
| :-- | :-- | :-- |
| `assert_handle_mark_nesting` | ASSERT | 无 HandleMark / 在 NoHandleMark 内分配即断言 |
| `NoHandleMark` / `ResetNoHandleMark` | ASSERT | 禁配句柄区与其豁免窗口（`handles.cpp:178-205`） |
| `ZapVMHandleArea` | develop，debug 默认 true | 回滚区填 0xBC，抓 use-after-pop |
| `CHECK_UNHANDLED_OOPS` 构建 | 特殊构建 | `oop` 变包装类，登记/注销每个 oop，抓裸 oop 逃逸（`oopsHierarchy.hpp:52-115`） |
| `-Xcheck:jni` | 运行时 flag | 见上一节 |

设计上"谁持有 cell、谁能复制 handle"不再由类型系统记账，而是收敛为两条更简单的纪律：**handle 是廉价的值对象，随 HandleMark 生死**；需要长命就换引用表或 OopHandle。

## Links

- [JNI](/docs/CS/Java/JDK/Basic/JNI.md)
- [Oop 与 Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [Thread](/docs/CS/Java/JDK/JVM/Thread.md)
- [frame](/docs/CS/Java/JDK/JVM/frame.md)
- [GC](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md)

## References

- [JNI Specification: Design](https://docs.oracle.com/en/java/javase/27/docs/specs/jni/design.html)
- [JNI Specification: Functions](https://docs.oracle.com/en/java/javase/27/docs/specs/jni/functions.html)
- [java(1) man page — -Xcheck:jni option](https://docs.oracle.com/en/java/javase/27/tools/man-java-1.html)
- [JNI Frequently Asked Questions for the Java Platform](https://docs.oracle.com/en/java/javase/27/vm/jni-frequently-asked-questions.html)
