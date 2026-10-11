## Introduction

Class 文件是 Java 「一次编写，到处运行」的载体：编译器把 Java 源码编译成与平台无关的字节码，JVM 再把字节码翻译成本地机器码。理解 class 文件的结构，等于理解了 JVM 的输入格式。

但「结构」只是一半，另一半是**HotSpot 拿到这串字节后到底读走了什么**：常量池里哪些 tag 会真的建出运行时条目、哪些属性被解析、哪些属性连同字节一起被丢弃、什么情况下整份文件被拒绝。本篇按 `share/classfile/classFileParser.cpp` 与 `share/classfile/verifier.cpp` 的实际代码逐条核对，凡是只出现在旧书里而本树已不存在的开关或数字，会在正文点名。

## Version Baseline

> [!NOTE]
> **版本口径**：class 文件格式由《Java SE 规范》锁定，整体结构长期稳定，**主版本号随版本递进**。下表全部取自本树 `classfile/classFileParser.cpp:99-155` 的 `JAVA_n_VERSION` 宏，不是转抄二手资料：
>
> | Java SE | major | Java SE | major | Java SE | major |
> | :-- | :--: | :-- | :--: | :-- | :--: |
> | 1.5 | 49 | 11 | 55 | 19 | 63 |
> | 1.6 | 50 | 12 | 56 | 20 | 64 |
> | 7 | 51 | 13 | 57 | 21 | 65 |
> | 8 | 52 | 14 | 58 | 22 | 66 |
> | 9 | 53 | 15 | 59 | 23 | 67 |
> | 10 | 54 | 16 | 60 | 24 | 68 |
> | | | 17 | 61 | 25 | 69 |
> | | | 18 | 62 | 26 | 70 |
> | | | | | 27 | 71 |
>
> 三个容易被写错的版本事实：
>
> 1. **45 是下界而不是唯一的旧值**：`JAVA_MIN_SUPPORTED_VERSION` 就是 45（`classFileParser.cpp:99`），低于它直接抛 `UnsupportedClassVersionError`；本树只为 1.5 与 1.6 单独立了 `JAVA_1_5_VERSION` / `JAVA_6_VERSION` 两个宏（注释写明是「向后兼容 1.5 的格式新增与 bug 修复」），1.1 – 1.4 复用的 46 – 48 在今天只作为区间下界存在。
> 2. **minor 不再恒为 0，但也不是随便填**：自 major ≥ 56（Java 12）起，`minor` 只允许 `0` 或 `65535`；`65535` 是预览特性标记（`JAVA_PREVIEW_MINOR_VERSION`，`classFileParser.cpp:100`），且要求 `major` 恰好等于当前运行时上限，否则报「was compiled with preview features that are unsupported」；缺 `--enable-preview` 报「Try running with '--enable-preview'」；其它非零值报「was compiled with an invalid non-zero minor version」（`classFileParser.cpp:4371-4396`）。
> 3. **版本号检查与校验器开关无关**：`verify_class_version()` 在流解析最开头就被调用，源码注释写得很直白 —— `// Check version numbers - we check this even with verifier off`（`classFileParser.cpp:5514`）。
>
> 开头是 4 字节 magic `0xCAFEBABE`，随后两个 `u2` 依次是 minor 与 major（`classFileParser.cpp:5505-5512` 正是这个读取顺序）。本篇的常量池与属性表结构按 **JDK 27** 核对。JVM 域的新特性记录见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Overall Structure

class 文件是一段**紧凑的二进制流**，没有对齐要求：

```text
ClassFile {
    u4             magic;              // 0xCAFEBABE
    u2             minor_version;
    u2             major_version;
    u2             constant_pool_count;
    cp_info        constant_pool[constant_pool_count-1];   // 索引 1 开始
    u2             access_flags;
    u2             this_class;
    u2             super_class;
    u2             interfaces_count;
    u2             interfaces[interfaces_count];
    u2             fields_count;
    field_info     fields[fields_count];
    u2             methods_count;
    method_info    methods[methods_count];
    u2             attributes_count;
    attribute_info attributes[attributes_count];
}
```

> [!TIP]
> 常量池下标从 **1** 开始，`0` 保留作「不存在」的占位（如 `super_class` 为 0 表示 `java.lang.Object`）；`constant_pool_count` 记录的是**实际条目数 + 1**。这两个「反直觉」的约定是手写 class 文件工具时最常见的 bug 来源。HotSpot 的循环条件也印证了它：`for (int index = 1; index < length; index++)`（`classFileParser.cpp:189`）。

`parse_stream()` 严格按上表顺序读，每读一段先 `guarantee_more()` 保证流里还剩够字节，读不完就报 `ClassFormatError: Truncated class file`（`classfile/classFileStream.cpp:30`）。

用 [jclasslib bytecode editor](https://github.com/ingokegel/jclasslib) 可以直观查看 class 文件的每个字段。

## access flags

`access_flags` 描述类/接口的访问级别与特性，是 16 位掩码：

| 标志 | 含义 |
| :-- | :-- |
| `ACC_PUBLIC` (0x0001) | public |
| `ACC_PRIVATE` / `ACC_PROTECTED` / `ACC_PACKAGE` | 访问级别（三者互斥） |
| `ACC_STATIC` | static（接口方法不允许） |
| `ACC_FINAL` | final |
| `ACC_SUPER` / `ACC_SYNCHRONIZED` | 同步相关 |
| `ACC_VOLATILE` / `ACC_BRIDGE` | 协变返回的桥接方法 |
| `ACC_VARARGS` | 可变参数（`...`） |
| `ACC_INTERFACE` | 标志这是接口 |
| `ACC_ABSTRACT` | 抽象类/方法 |
| `ACC_SYNTHETIC` | 编译器生成（非源码） |
| `ACC_ANNOTATION` | 标志这是注解类型 |
| `ACC_ENUM` | 标志这是枚举 |
| `ACC_MODULE` (0x8000) | 这是 `module-info` |

> [!NOTE]
> `ACC_SUPER` 是历史包袱：JDK 1.0.2 之前没有它，用于改变 `invokespecial` 对 `super` 的处理语义。现在几乎所有编译产物都置上它，**判断一个类是不是「老式」时可以看这个位**。HotSpot 读到的 flags 会立刻和掩码求与，只保留它认识的位：`flags = stream->get_u2_fast() & (JVM_RECOGNIZED_CLASS_MODIFIERS | JVM_ACC_MODULE)`，其中 `JVM_ACC_MODULE` 只在 major ≥ 53 时才参与（`classFileParser.cpp:5546-5550`）——**未知的高位被静默清零，而不是报错**，这是 class 文件向后兼容的关键手段。

## Constant Pool

常量池是 class 文件的**核心**：它既是「符号表」，又承载了字面量。

- **字面量（Literal）**：`int`、`long`、`float`、`double`、`String` 的值
- **符号引用（Symbolic Reference）**：类名与全限定名、字段名与方法名、字段与方法的类型描述符

### The Full Tag Set Supported By This Tree

下表是 `ClassFileParser::parse_constant_pool_entries()` 的 `switch (tag)` **真正有 case 的集合**（`classFileParser.cpp:194-383`）。tag 数值来自规范（References 的 JVMS §4.4），**符号名与版本门限来自本树**：

| tag | JVMS 名称 | HotSpot 符号 | 装载动作 | 版本门限 |
| :-- | :-- | :-- | :-- | :-- |
| 1 | `CONSTANT_Utf8` | `JVM_CONSTANT_Utf8` | 进 `SymbolTable` 驻留成 `Symbol*` | 无 |
| 3 | `CONSTANT_Integer` | `JVM_CONSTANT_Integer` | `cp->int_at_put` | 无 |
| 4 | `CONSTANT_Float` | `JVM_CONSTANT_Float` | `cp->float_at_put`，按位重解释 | 无 |
| 5 | `CONSTANT_Long` | `JVM_CONSTANT_Long` | `cp->long_at_put`，**index++ 占两项** | 无 |
| 6 | `CONSTANT_Double` | `JVM_CONSTANT_Double` | `cp->double_at_put`，**index++ 占两项** | 无 |
| 7 | `CONSTANT_Class` | `JVM_CONSTANT_Class` | `klass_index_at_put`，先存 **name_index** 而非解析后的类 | 无 |
| 8 | `CONSTANT_String` | `JVM_CONSTANT_String` | `string_index_at_put` | 无 |
| 9 | `CONSTANT_Fieldref` | `JVM_CONSTANT_Fieldref` | `field_at_put` | 无 |
| 10 | `CONSTANT_Methodref` | `JVM_CONSTANT_Methodref` | `method_at_put` | 无 |
| 11 | `CONSTANT_InterfaceMethodref` | `JVM_CONSTANT_InterfaceMethodref` | `interface_method_at_put` | 无 |
| 12 | `CONSTANT_NameAndType` | `JVM_CONSTANT_NameAndType` | `name_and_type_at_put` | 无 |
| 15 | `CONSTANT_MethodHandle` | `JVM_CONSTANT_MethodHandle` | `method_handle_index_at_put`，含 `ref_kind` | major ≥ 51 |
| 16 | `CONSTANT_MethodType` | `JVM_CONSTANT_MethodType` | `method_type_index_at_put` | major ≥ 51 |
| 17 | `CONSTANT_Dynamic` | `JVM_CONSTANT_Dynamic` | `dynamic_constant_at_put`，顺带收集 `bootstrap_specifier_index` | major ≥ 55 |
| 18 | `CONSTANT_InvokeDynamic` | `JVM_CONSTANT_InvokeDynamic` | `invoke_dynamic_at_put` | major ≥ 51 |
| 19 | `CONSTANT_Module` | `JVM_CONSTANT_Module` | **不落常量池**，只记 `_bad_constant_seen` | major ≥ 53 |
| 20 | `CONSTANT_Package` | `JVM_CONSTANT_Package` | **不落常量池**，同上 | major ≥ 53 |

**没有 tag 2 的 case**：历史上 `CONSTANT_Class` 曾用 2，规范废弃后编号保留，本树遇到即落 `default` 分支报 `Unknown constant tag %u in class file %s`。同理，14（`CONSTANT_Reserved`）也不存在。

门限的报错文案是分档的：`MethodHandle` / `MethodType` / `InvokeDynamic` 太旧时报 `Class file version does not support constant tag %u in class file %s`（`classFileParser.cpp:232 / 255 / 271`），门限常量来自 `classfile/verifier.hpp:40-43`：

```cpp
    STACKMAP_ATTRIBUTE_MAJOR_VERSION    = 50,
    INVOKEDYNAMIC_MAJOR_VERSION         = 51,
    DYNAMICCONSTANT_MAJOR_VERSION       = 55
```

> [!WARNING]
> **`long` 和 `double` 各占两个常量池槽位**。所以遍历常量池时索引不能简单 `i++`，必须按 tag 判断是否跳过下一项——否则会错位。这是解析 class 文件时的高频 bug。规范上槽位 1 也不能被 long/double 占用（为了兼容早期实现）。HotSpot 的处理是**读完 8 字节后再手动 `index++`**，并在读之前先保证「后面还有槽位」：
>
> ```cpp
>       case JVM_CONSTANT_Long: {
>         // A mangled type might cause you to overrun allocated memory
>         guarantee_property(index + 1 < length,
>                            "Invalid constant pool entry %u in class file %s",
>                            index,
>                            CHECK);
>         cfs->guarantee_more(9, CHECK);  // bytes, tag/access_flags
>         const u8 bytes = cfs->get_u8_fast();
>         cp->long_at_put(index, bytes);
>         index++;   // Skip entry following eigth-byte constant, see JVM book p. 98
>         break;
>       }
> ```
>
> `classFileParser.cpp:296-307`，`Double` 分支逐字相同。注释里的 `eigth-byte` 是 HotSpot 源码原样的拼写错误。

### Special Handling of Module and Package

这两个 tag 是「格式合法但 HotSpot 不需要」的典型：解析器读掉 `name_index` 后**不写 ConstantPool**，只调用 `set_class_bad_constant_seen(tag)` 记一笔，然后继续解析（`classFileParser.cpp:365-376`）：

```cpp
      case JVM_CONSTANT_Module:
      case JVM_CONSTANT_Package: {
        // Record that an error occurred in these two cases but keep parsing so
        // that ACC_Module can be checked for in the access_flags.  Need to
        // throw NoClassDefFoundError in that case.
        if (_major_version >= JAVA_9_VERSION) {
          cfs->guarantee_more(3, CHECK);
          cfs->get_u2_fast();
          set_class_bad_constant_seen(tag);
          break;
        }
      }
```

这个 case **没有 `break`**：major < 53 时会顺着落到 `default`，报 `Unknown constant tag %u`——旧版本 class 里出现 Module 才是真错误。记下来的 `bad_constant` 在 access flags 解析完才被消费（`classFileParser.cpp:5559`），目的是让 `module-info.class` 以普通 class 身份被加载时给出正确的 `NoClassDefFoundError` 而不是含糊的 `ClassFormatError`。`set_class_bad_constant_seen()` 自身的 `assert` 也写死了「只可能是 Module 或 Package，且 major ≥ 53」（`classFileParser.cpp:157-162`）。

### Utf8Info and Symbol

HotSpot **不为 Utf8 条目分配 `Utf8Info` 对象**：常量池里对应槽位直接放 intern 后的 `Symbol*`。路径是「先查、查不到再攒批」（`classFileParser.cpp:341-362`）：

```cpp
        unsigned int hash;
        Symbol* const result = SymbolTable::lookup_only((const char*)utf8_buffer,
                                                        utf8_length,
                                                        hash);
        if (result == nullptr) {
          names[names_count] = (const char*)utf8_buffer;
          lengths[names_count] = utf8_length;
          indices[names_count] = index;
          hashValues[names_count++] = hash;
          if (names_count == SymbolTable::symbol_alloc_batch_size) {
            SymbolTable::new_symbols(_loader_data,
                                     constantPoolHandle(THREAD, cp),
                                     names_count,
                                     names,
                                     lengths,
                                     indices,
                                     hashValues);
            names_count = 0;
          }
        } else {
          cp->symbol_at_put(index, result);
        }
```

两点值得注意：**批量分配**（攒满 `symbol_alloc_batch_size` 才调 `new_symbols`，减少全局表锁与 Metaspace 分配次数）与**校验前置**（`if (_need_verify) verify_legal_utf8(...)`，`classFileParser.cpp:337-339`，非法 modified-UTF8 在驻留之前就被拒）。驻留、哈希与 `Symbol` 生命周期属于 [SymbolTable](/docs/CS/Java/JDK/JVM/SymbolTable.md) 的职责，本篇不展开。

### HotSpot Private Runtime Tags

`utilities/constantTag.hpp` 除了规范 tag，还有一批 **100 起的实现私有 tag**，它们**永远不会出现在 class 文件字节里**，是解析后或链接过程中的状态标记（`constantTag.hpp:39-48`）：

| 值 | 符号 | 含义 |
| :-- | :-- | :-- |
| 0 | `JVM_CONSTANT_Invalid` | 非法值初始化占位 |
| 100 | `JVM_CONSTANT_UnresolvedClass` | 已解析成类引用但目标类尚未解析 |
| 101 | `JVM_CONSTANT_ClassIndex` | 构造常量池期间的临时 tag |
| 102 | `JVM_CONSTANT_StringIndex` | 构造常量池期间的临时 tag |
| 103 | `JVM_CONSTANT_UnresolvedClassInError` | 解析出错的错误态 |
| 104 | `JVM_CONSTANT_MethodHandleInError` | 解析出错的错误态 |
| 105 | `JVM_CONSTANT_MethodTypeInError` | 解析出错的错误态 |
| 106 | `JVM_CONSTANT_DynamicInError` | 解析出错的错误态 |

`JVM_CONSTANT_InternalMin = 100` / `InternalMax = 106` 界定了这个私有区间；`constantTag` 的构造函数 `assert` 只接受 `0..12`、`15..18` 与私有区间（`constantTag.hpp:124-129`），**这个白名单里没有 19 / 20**——正好呼应上一节：Module / Package 条目根本不进 ConstantPool，因此不需要运行时 tag。

私有 tag 的存在还能看到解析的分阶段进行：常量池条目读完后还有「第二遍格式检查」，其 `switch (tag)` 里 `CONSTANT_Class` 槽位此时已经是 `JVM_CONSTANT_UnresolvedClass`（`classFileParser.cpp:612-621`），即 Class 条目经历了「存 `name_index` → 临时 tag `ClassIndex` → 未解析态」三步，而 `constantTag.hpp:42-43` 的注释 `Temporary tag while constructing constant pool` 就是在描述中间那一步。

> [!NOTE]
> **Valhalla 相关的新常量池 tag 在本版本尚未引入**。本树 `constantTag.hpp` 与 `parse_constant_pool_entries()` 都不存在值类型 / 原始类相关 tag（`JVM_CONSTANT_*Value`、`*Flattened`、`*Primitive` 全树 grep 无命中），私有 tag 区间仍停在 106。markWord 里预留的 Valhalla 位属于对象头，见 [Object_Header](/docs/CS/Java/JDK/JVM/Object_Header.md)。

## Attribute Table

属性表是 class 文件最重要的**可扩展点**，理解 HotSpot 侧的关键在于：**它不查表，而是把属性名的 `Symbol*` 与 `vmSymbols::tag_xxx()` 逐个做指针比较的 if-else 链**。所以「支持哪些属性」= 「这条链上写了多少个分支」，链尾的统一处理就是丢弃。

### Attributes Allowed at Each of the Four Layers

| 层 | 被解析的属性 | 代码位置 |
| :-- | :-- | :-- |
| **field** | `ConstantValue`（仅 static 有效）、`Synthetic`、`Deprecated`、`Signature`、`RuntimeVisibleAnnotations`、`RuntimeInvisibleAnnotations`、`RuntimeVisibleTypeAnnotations`、`RuntimeInvisibleTypeAnnotations` | `classFileParser.cpp:1260-1347` |
| **class** | `SourceFile`、`SourceDebugExtension`、`InnerClasses`、`Synthetic`、`Deprecated`、`Signature`、`RuntimeVisible/InvisibleAnnotations`、`EnclosingMethod`、`BootstrapMethods`、`RuntimeVisible/InvisibleTypeAnnotations`、`NestMembers`、`NestHost`、`Record`、`PermittedSubclasses` | `classFileParser.cpp:3428-3631` |
| **method** | `Code`、`Exceptions`、`MethodParameters`、`Synthetic`、`Deprecated`、`Signature`、`RuntimeVisible/InvisibleAnnotations`、`RuntimeVisible/InvisibleParameterAnnotations`、`RuntimeInvisibleParameterAnnotations`、`AnnotationDefault`、`RuntimeVisible/InvisibleTypeAnnotations` | `classFileParser.cpp:2269-2573` |
| **Code** | `LineNumberTable`、`LocalVariableTable`、`LocalVariableTypeTable`、`StackMapTable` | `classFileParser.cpp:2343-2417` |

三条**没有出现在表里**的值得单独记住：

- **`Module` / `ModuleMainClass` / `Package` 类属性不在链上**：本树 `share/classfile/` 内没有任何读取 `vmSymbols::tag_module()` / `tag_package()` 属性的分支，模块描述符由 JDK 库侧自行从 `module-info.class` 的字节里取，HotSpot 只保证这类文件不会把 VM 搞崩。
- **`StackMapTable` 只在 major ≥ 50 才被承认**（`classFileParser.cpp:2408-2409`，门限即 `Verifier::STACKMAP_ATTRIBUTE_MAJOR_VERSION`）。
- **`RuntimeInvisible*` 一律只记一个布尔值**，字节被 `skip_u1(attribute_length)` 直接跳过；`RuntimeVisibleTypeAnnotations` 在类层的注释写着 `// No need for the VM to parse Type annotations`（`classFileParser.cpp:3560`）。

### Version Gates on Attributes

门限是**嵌套 if 的层级**表达的，不是每个属性单独标注，读代码时容易看漏：

| 门限 | 效果 |
| :-- | :-- |
| major < 49 | field / method / class 三层里 `Signature` 与四个注解属性整体落入 `else` 分支被跳过（`classFileParser.cpp:1290 / 2481 / 3479`） |
| major ≥ 51 | `BootstrapMethods` 才被解析（`classFileParser.cpp:3543-3544`，条件写的是 `>= Verifier::INVOKEDYNAMIC_MAJOR_VERSION`） |
| major ≥ 50 | `StackMapTable` 才被解析 |
| major ≥ 60 | `Record`（`classFileParser.cpp:3608`） |
| major ≥ 61 | `PermittedSubclasses`（`classFileParser.cpp:3617`） |

`NestHost` / `NestMembers` 位于 major ≥ 55 的嵌套分支内（`classFileParser.cpp:3570-3606`），报错文案里能看到 JEP 181 的另一半效果：`Nest-host class_info_index %u has bad constant type in class file %s`。`PermittedSubclasses` 还有一条纯语义检查：`PermittedSubclasses attribute in final class file %s`（`classFileParser.cpp:3624-3627`）——**final 类不允许有许可子类**。

### How Unknown Attributes Are Dropped

三种情况都会走同一句 `cfs->skip_u1(attribute_length, CHECK)`：

1. 属性名是本层白名单之外的任意字符串（注释原话 `// Skip unknown attributes`，`classFileParser.cpp:1349 / 2419 / 2575`）；
2. 属性名认识但**版本门限不满足**（落入外层 `else`，`classFileParser.cpp:1352 / 2580 / 3644`）；
3. class 层里，即使 `Record` / `PermittedSubclasses` 被记住了起始指针，其字节仍被跳过（`classFileParser.cpp:3633-3634` 的注释 `// Skip attribute_length for any attribute where major_verson >= JAVA_17_VERSION`，`verson` 是源码原样的拼写错误）——**数据留在原始流里，按需再由使用方解析**。

> [!TIP]
> 「丢弃」是精确含义：**属性不会占用 Metaspace，也不会被 InstanceKlass 记住**，JVMTI 之外没有第二条路能拿回它。唯一的前置校验是属性名索引必须是合法 `Symbol`，否则 `Invalid field attribute index %u in class file %s`（`classFileParser.cpp:1254-1257`）；属性**长度**则只在 `_need_verify` 为真时才与实际读掉的字节数核对（`Code segment has wrong length in class file %s`，`classFileParser.cpp:2424-2428`）。这也解释了为什么「加一个自定义属性不影响 JVM 运行」：HotSpot 不认识的属性，代价只是流指针前进。

### The VM Internal Annotation Whitelist

属性链之外还有一条常被误认为「属性」的通道：`@Stable`、`@Contended`、`@ForceInline`、`@IntrinsicCandidate`、`@CallerSensitive`、`@Hidden`、`@Scoped`、`@ValueBased`、`@TrustFinalFields`、`@AOTSafeClassInitializer`、`@AOTRuntimeSetup` 等 **jdk.internal.\* 注解会被 HotSpot 在装载期消费并落到 FieldInfo / method / InstanceKlass 的位上**。它们的判定集中在 `AnnotationCollector::annotation_index()`（`classFileParser.cpp:1817-1929`），规则有两条硬约束：

```cpp
  // Privileged code can use all annotations.  Other code silently drops some.
  const bool privileged = loader_data->is_boot_class_loader_data() ||
                          loader_data->is_platform_class_loader_data() ||
                          can_access_vm_annotations;
```

- **位置约束**：每个 case 第一行就是 `if (_location != _in_method) break;`（或 `_in_field` / `_in_class`），放错层等于没写；`@Contended` 允许 field 与 class，`@Stable` 只允许 field，`@TrustFinalFields` 只允许 class。
- **权限约束**：非特权代码里 `break` 出链，注解被**静默丢弃**（`AnnotationCollector::_unknown`）——这就是应用代码给字段加 `@Contended` 却完全无效的原因。此外 `@Contended` 还额外受 `EnableContended` / `RestrictContended` 控制，`@ReservedStackAccess` 受 `RestrictReservedStack` 控制。

## Hard Limits

下表每一项都在本树有明确检查点与报错文案。**旧书里那套「class 文件不得超过 32 MB」的说法在 JDK 27 的 HotSpot 里已经没有对应实现**：`KlassfileSizeLimit` / `klassfile_size_limit` 在 `src/hotspot` 全树 grep 零命中，取而代之的是「流边界 + 各字段的自然宽度」。

| 上限 | 值 | 检查点 | 报错文案 |
| :-- | :-- | :-- | :-- |
| magic | `0xCAFEBABE` | `classFileParser.cpp:5506` | `Incompatible magic value %u in class file %s` |
| major 下界 | 45 | `classFileParser.cpp:4354` | `%s (class file version %u.%u) was compiled with an invalid major version` |
| major 上界 | 运行时 `JVM_CLASSFILE_MAJOR_VERSION`，本树即 71 | `classFileParser.cpp:4360-4367` | `%s has been compiled by a more recent version of the Java Runtime (class file version %u.%u), this version of the Java Runtime only recognizes class file versions up to %u.0` |
| minor | 只允许 0 或 65535 | `classFileParser.cpp:4371-4396` | `... was compiled with an invalid non-zero minor version` / `... preview features that are unsupported` / `Preview features are not enabled for %s ... Try running with '--enable-preview'` |
| `constant_pool_count` | `u2`，即 ≤ 65535；且 ≥ 1 | `classFileParser.cpp:5518-5522` | `Illegal constant pool size %u in class file %s` |
| hidden class 追加槽位 | 追加前必须 `< 0xffff` | `classFileParser.cpp:5525-5527` | `Overflow in constant pool size for hidden class %s` |
| `long` / `double` 位置 | 不能是最后一项 | `classFileParser.cpp:298 / 310` | `Invalid constant pool entry %u in class file %s` |
| `NameAndType` 的 name 与 signature | 两者长度都不能为 0 | `classFileParser.cpp:629-634` | `Illegal zero length constant pool entry at %d in class %s` |
| `code_length` | `0 < n <= 65535`（`MAX_CODE_SIZE`，`classFileParser.cpp:2012`） | `classFileParser.cpp:2293-2295` | `Invalid method Code length %u in class file %s` |
| 方法参数槽位 | `<= 255`（`MAX_ARGS_SIZE`，`classFileParser.cpp:2011`） | `classFileParser.cpp:2204-2205` | `Too many arguments in method signature in class file %s` |
| `args_size <= max_locals` | 语义检查 | `classFileParser.cpp:2290-2292` | `Arguments can't fit into locals in class file %s` |
| 数组维度 | 255（`MAX_ARRAY_DIMENSIONS`，`verifier.cpp:69`） | 校验器 | `VerifyError` |

**没有的检查**，同样是本篇要记的结论：

- `fields_count` / `methods_count` / `interfaces_count` **没有独立的计数上限检查**——它们是 `u2`，65535 就是天然天花板；本树只有 `_java_fields_count` 这类记账（`classFileParser.cpp:1389`），以及 hidden class 注入成员后重建流的逻辑。
- `Code` 的 `exception_table_length`、`LineNumberTable` 条数同样没有全局上限，只有 `attribute_length` 与实际字节的自洽校验。
- **类文件总大小没有 flag**：唯一兜底是每一处 `guarantee_more()` 造成的截断检测 → `ClassFormatError: Truncated class file`（`classFileStream.cpp:30`）。真正限制单个 InstanceKlass 元数据体积的是 Metaspace，见 [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)。

> [!WARNING]
> 容易与「class 大小上限」混淆的是 `FastAllocateSizeLimit`（`runtime/globals.hpp:1079`，`develop` 标志、默认 `128*K`），它在 `classFileParser.cpp:3990-3996` 被用：实例大小达到该值就把 layout helper 标成「不可走快速分配路径」。**限制的是对象实例大小，不是 class 文件大小，且只在 debug 构建可调。**

## Bytecode Verification

### The type checking Boundary

分界就是 `Verifier::STACKMAP_ATTRIBUTE_MAJOR_VERSION = 50`（`verifier.hpp:40`），决策点只有一个 if（`verifier.cpp:219-256`）：

```cpp
  if (klass->major_version() >= STACKMAP_ATTRIBUTE_MAJOR_VERSION) {
    ClassVerifier split_verifier(jt, klass);
    // We don't use CHECK here, or on inference_verify below, so that we can log any exception.
    split_verifier.verify_class(THREAD);
    exception_name = split_verifier.result();

    // If dumping {classic, final} static archive, don't bother to run the old verifier, as
    // the class will be excluded from the archive anyway.
    bool can_failover = !(CDSConfig::is_dumping_classic_static_archive() || CDSConfig::is_dumping_final_static_archive()) &&
      klass->major_version() < NOFAILOVER_MAJOR_VERSION;
    ...
  } else {
    message_buffer = NEW_RESOURCE_ARRAY(char, message_buffer_len);
    exception_message = message_buffer;
    exception_name = inference_verify(
        klass, message_buffer, message_buffer_len, THREAD);
  }
```

三条由此推出的结论：

1. **major ≥ 50 走 type checking**：不再由验证器推断栈帧类型，而是拿 `StackMapTable` 里声明的帧类型逐条比对，因此线性时间复杂度。`StackMapTable` 缺失本身不是错误（可以被推断出的情况由 JVMS 决定），但帧类型对不上就是 `VerifyError`。
2. **回退只对 major == 50 开放**：`NOFAILOVER_MAJOR_VERSION = 51`（`verifier.cpp:66`），split verifier 失败后只有 `major < 51` 才允许 failover 到 `inference_verify()`。换句话说 50 是唯一「两套验证器都可能跑」的版本，51 及以上失败即失败。
3. **旧的推理式验证器不在 HotSpot 里**：`inference_verify()` 通过 `os::dll_load(... "verify")` 加载外部 `verify` 库、查找 `VerifyClassForMajorVersion` 符号（`verifier.cpp:96-108`），加载失败即让调用方抛 `VerifyError`。这是为老 class 保留的兼容通道，不是当前主路径。

failover 还有一个副作用值得知道：**用旧验证器验证过的类会被踢出 CDS 归档**（`SystemDictionaryShared::set_excluded(klass)`，注释解释为旧验证器不会调用 `add_verification_constraint()`，`verifier.cpp:235-242`）。

### Which Classes Get Verified

`Verifier::should_verify_for()` 按 **loader 是否为引导类加载器**分档（`verifier.cpp:115-118`）：

```cpp
bool Verifier::should_verify_for(oop class_loader) {
  return class_loader == nullptr ?
    BytecodeVerificationLocal : BytecodeVerificationRemote;
}
```

对应的 flag 定义在 `runtime/globals.hpp:455-459`，两者都是 **DIAGNOSTIC**：

| flag | 默认 | 作用 |
| :-- | :-- | :-- |
| `BytecodeVerificationRemote` | `true` | 非引导 loader 的类（「远程」） |
| `BytecodeVerificationLocal` | `false` | 引导 loader 的类（「本地」，视为可信） |

因为是 DIAGNOSTIC，命令行改它们必须先 `-XX:+UnlockDiagnosticVMOptions`。`runtime/arguments.cpp:3530-3532` 还有一条归一化规则：只开了 `BytecodeVerificationLocal` 而没开 Remote 时，Remote 会被自动置 true——**没有「只验证本地类」这种组合**。

`_need_verify` 的来源在 `classFileParser.cpp:5392`，比上面的分档多一条优先级：

```cpp
  _need_verify = stream->from_class_file_load_hook() ? true : Verifier::should_verify_for(_loader_data->class_loader());
```

**经 JVMTI `ClassFileLoadHook` 改写过的字节流一定被验证**，与 loader 无关；这个结论还会记到类上（`ik->set_should_verify_class(_need_verify)`，`classFileParser.cpp:5089`），供后续 redefinition 使用。前文多处 `if (_need_verify)` 说明它同时管着**格式检查的强度**（长度自洽、Utf8 合法性、常量池索引类型），而不只是类型检查——所以「关掉验证」在 HotSpot 里从来不是「什么都不查」。

### The Current Status of -Xverify

> [!WARNING]
> **`-Xverify:none` 在本版本已经不是可用开关**。`runtime/arguments.cpp:2321-2338` 只接受 `-Xverify`（裸写，等价 `:all`）、`-Xverify:all`、`-Xverify:remote` 三种形态：
>
> ```cpp
>     } else if (match_option(option, "-Xverify", &tail)) {
>       if (strcmp(tail, ":all") == 0 || strcmp(tail, "") == 0) {
>         if (FLAG_SET_CMDLINE(BytecodeVerificationLocal, true) != JVMFlag::SUCCESS) {
>           return JNI_EINVAL;
>         }
>         if (FLAG_SET_CMDLINE(BytecodeVerificationRemote, true) != JVMFlag::SUCCESS) {
>           return JNI_EINVAL;
>         }
>       } else if (strcmp(tail, ":remote") == 0) {
>         if (FLAG_SET_CMDLINE(BytecodeVerificationLocal, false) != JVMFlag::SUCCESS) {
>           return JNI_EINVAL;
>         }
>         if (FLAG_SET_CMDLINE(BytecodeVerificationRemote, true) != JVMFlag::SUCCESS) {
>           return JNI_EINVAL;
>         }
>       } else if (is_bad_option(option, args->ignoreUnrecognized, "verification")) {
>         return JNI_EINVAL;
>       }
> ```
>
> `:none` 既不是 `:all` 也不是 `:remote`，会落进 `is_bad_option`——也就是**被当作无效选项拒绝启动**（除非 `-XX:+IgnoreUnrecognizedVMOptions`），没有「deprecation warning 后继续跑」的路径。想等效关闭远程验证只能改走 `-XX:-BytecodeVerificationRemote`（需先解锁 DIAGNOSTIC）。
>
> 同理，`NeverActAsServerClassMachine` 已进入 obsolete 表：`{ "NeverActAsServerClassMachine", JDK_Version::jdk(26), JDK_Version::jdk(27), JDK_Version::jdk(28) }`（`runtime/arguments.cpp:552`）——**JDK 26 起 deprecated、27 起 obsolete**，本版本写它必然报错，不能再作为「关掉某些优化以复现旧行为」的手段。

## Method Invocation Instructions

class 文件里最关键的一组字节码是方法调用，它们决定了方法分派走哪条路：

| 指令 | 何时用 | 特点 |
| :-- | :-- | :-- |
| `invokevirtual` | public/protected 的非 static、非 final 方法 | 需运行时**虚方法表（vtable）**分派 |
| `invokeinterface` | 接口方法 | 需先拿到 `this` 对象的 `Klass` 再查接口方法表 |
| `invokespecial` | private 方法、构造器 `<init>`、以及 `super.` 调用 | **不走虚表**，编译期直接绑定（JEP 181 起不再用于私有接口方法） |
| `invokestatic` | static 方法 | 无 `this`，同样不走虚表 |
| `invokedynamic` | Lambda、字符串拼接（9+）、record 的 `equals/hashCode` 等 | 首次执行时把**引导方法**链接到实际目标 |

对应的 vtable/itable 机制见 [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)。字节码常量池索引何时被替换成 constant pool cache 下标，属于装载期的字节码重写阶段，见 [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)。

> [!TIP]
> [JEP 181](https://openjdk.org/jeps/181)（Nest-Based Access Control，Release **11**）**放宽**了这条历史约束，方向与直觉相反：Java 8 起允许接口私有方法后，规范一度要求它们用 `invokespecial` 调用；JEP 181 明确取消该限制，改为**私有接口方法可以用 `invokeinterface`**（私有构造器仍用 `invokespecial`，私有非接口方法可用 `invokevirtual`）。该 JEP 同时引入 `NestHost` / `NestMembers` 属性，允许同一 nest 的类互相访问私有成员，从而让编译器不必再生成「访问桥接方法」。**注意这套规则需要足够新的 class 文件版本才会被 JVM 启用。**

## Debug Attributes

`Code` 属性里除了字节码指令，还常挂两类调试信息属性：

- **`LineNumberTable`** —— 字节码偏移量到**源码行号**的映射，异常栈回溯能打出「第 N 行」靠它；
- **`LocalVariableTable`** —— 槽位到**变量名与类型**的映射，调试器显示局部变量名靠它。

这两者都**不影响语义**，可以用 `-g:none` 省略以减小体积；但生产环境排查问题时，缺失它们会让栈信息变得很难读。

> [!NOTE]
> VM 侧还有一层「读不读」的开关：`LoadLineNumberTables`、`LoadLocalVariableTables`、`LoadLocalVariableTypeTables`（`runtime/globals.hpp:770-776`）。三个都是 **`develop` 标志、默认 true**——意味着**产品构建里根本没有这两个选项**，只有 debug 构建能关掉装载；而 `LocalVariableTypeTable` 还额外要求 major ≥ 49（`classFileParser.cpp:2379-2381`）。所以「用 `-XX:-LoadLocalVariableTables` 省内存」在正常 JVM 上不成立。

## What Happens After Parsing

本篇只覆盖「字节 → 内存结构」这一段，往后的分工是明确的：

- 解析完的 `constantPoolOop` / `FieldInfo` / `methodHandle` 组装成 `InstanceKlass`，由 [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md) 与 [Method](/docs/CS/Java/JDK/JVM/Method.md) 负责，本篇不涉及。
- Utf8 条目的驻留与 `Symbol` 生命周期归 [SymbolTable](/docs/CS/Java/JDK/JVM/SymbolTable.md)。
- 谁决定往 class 文件里写哪些属性、`-g` 与 `--release` 如何影响产物，见 [Javac](/docs/CS/Java/JDK/JVM/Javac.md)。
- 重写后的字节码如何被执行、`invokedynamic` 的调用点如何链接，见 [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)。
- `ACC_SYNCHRONIZED` 与 `synchronized` 方法落到的对象头位布局，见 [Object_Header](/docs/CS/Java/JDK/JVM/Object_Header.md)。

class 文件只是「原料」，从它到可执行代码要经过 [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md) 的三阶段：

- **加载（load）**：把字节流读成 `Class` 的内部表示（对应 [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md) 的 Klass 层级）；
- **链接（link）**：验证字节码、准备静态字段、把常量池中的符号引用**解析**为直接引用；
- **初始化（initialize）**：执行 `<clinit>()`，给静态字段赋真实值。

## Links

- [Method](/docs/CS/Java/JDK/JVM/Method.md)
- [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)
- [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [Valhalla](/docs/CS/Java/JDK/Valhalla.md)
- [JMH](/docs/CS/Java/JDK/JVM/JMH.md)

## References

- [The class File Format — The Java Virtual Machine Specification, Java SE 27 Edition](https://docs.oracle.com/javase/specs/jvms/se27/html/jvms-4.html)
- [JEP 12: Preview Languages and Virtual Machine Specifications](https://openjdk.org/jeps/12)
- [JEP 359: Hidden Classes](https://openjdk.org/jeps/359)
- [JDK 27 — OpenJDK Projects](https://openjdk.org/projects/jdk/27/)
