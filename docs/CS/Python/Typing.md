## Introduction

Python 的类型标注有两套彼此独立的语义：**检查时的静态语义**由 mypy / pyright 实现，**运行时的动态语义**由解释器与第三方库实现。它们的历史并不同步。静态侧的语法一路扩张（3.9 内置泛型、3.10 `X | None`、3.12 类型参数语法、3.13 类型参数默认值）；动态侧则反复修改"注解表达式到底什么时候求值"这一件事，到 3.14 已经是第三套执行模型。

"这个写法为什么在运行时炸了""那个库为什么读不到我的注解"这类问题，根因几乎都在这条时间线上，而不是在某条检查器规则里。本篇按这条主线组织：先钉住"标注不改变运行时行为"这个前提，再讲求值语义的三段演变（3.14 迁移的实际痛点），最后给语法版本线、类型收窄、结构化与名义、第三方库如何携带类型、运行时校验、渐进类型化策略。API 罗列交给官方文档。

## Annotations Do Not Change Runtime Behavior

Python 不做类型强制：标注是**元数据**，解释器既不校验实参，也不据此分派。

```python
def add(a: int, b: int) -> int:
    return a + b

print(add("x", "y"))     # xy    # Python 3.12.5 实测
```

同样地，mypy / pyright 报错**不阻止代码执行**：它们只在 CI 与编辑器里读源码，运行时不参与任何判断。duck typing 仍是运行时事实，静态检查是在其上叠加的一层可选契约。

标注真正的消费者有三类，它们对"注解是什么"的要求完全不同：

| 消费方 | 时机 | 需要的是 | 典型代表 |
| :-- | :-- | :-- | :-- |
| 静态检查器 | 不执行代码，只解析源码 | 语法与类型规则的完备性 | mypy / pyright |
| IDE | 源码 + 索引 | 可解析的名称与签名 | 补全、跳转、重构 |
| 运行时库 | 导入后按需求值或直接读值 | `__annotations__` 里真的有可用对象 | `dataclasses`、pydantic、FastAPI、`typing.get_type_hints()` |

第三类是所有历史包袱的来源：一个把注解当**对象**用的库，和一个把注解当**文本**看的检查器，对同一个写法的容忍度不一样。

## Eager Evaluation in 3.0 to 3.13

```python
def f(x: int, y: "str" = "a") -> bool:
    return x > 0

print(f.__annotations__)
# {'x': <class 'int'>, 'y': 'str', 'return': <class 'bool'>}   # Python 3.12.5 实测

class C:
    a: int
    b: str = "x"
print(C.__annotations__, "a" in C.__dict__, "b" in C.__dict__)
# {'a': <class 'int'>, 'b': <class 'str'>} False True            # Python 3.12.5 实测

try:
    def g(x: Undefined): ...
except NameError as e:
    print(e)     # name 'Undefined' is not defined                # Python 3.12.5 实测
```

两种东西可以同时出现在同一个 dict 里：`int` 是对象，`'str'` 只是你手写的字符串字面量（检查器叫它 forward reference）。`__annotations__` 就是普通字典，键是参数名加 `return`；类体里的 `x: int` 只登记注解、**不创建类属性**，带默认值的 `b: str = "x"` 才会。第三段是这一节的全部要害：**注解表达式在 `def` 或类体执行的那一刻就被求值**，未定义的名字立刻炸。另有一处独立于求值语义的坑：3.10 之前没有自己注解的 `Derived.__annotations__` 会返回父类的字典，3.10 起才是自己的空 dict（实测 3.12.5）。官方 howto 因此建议运行时库走 `inspect.get_annotations()`（3.14 起是 `annotationlib.get_annotations()`）而不是裸取属性——它会忽略继承来的注解与元类上的注解。

由此派生三个日常后果：

1. 名字还不存在时要引用它，只能加引号——递归类型、互相引用的两个类、定义在后面的类，全都要写字符串。
2. 被引用的类型必须真的存在于运行时命名空间。只为标注服务的 import 因此会制造循环，需要塞进 `if TYPE_CHECKING:` 块，代价是运行时读不到那个名字（机制见 [Import](/docs/CS/Python/Import.md)）。
3. 求值跟着 `def` 语句走，而不是只跟着导入走。实测：把注解写成函数调用 `def inner(x: ann())` 并让 `outer()` 里定义 `inner`，调用 `outer()` 三次，`ann()` 被调用三次；加上 `from __future__ import annotations` 后是 0 次。工厂函数、装饰器包装、按参数动态生成类的代码里，注解求值成本会落在每次调用上。模块级注解同理会把重计算推进导入路径——数值库把 shape / dtype 元数据放进 `Annotated` 时特别明显（用法见 [NumPy](/docs/CS/Python/NumPy.md)）。

## Stringized Annotations with PEP 563

`from __future__ import annotations`（3.7 起）把注解编译成**源码文本**存起来，求值推迟到消费方主动求值。

```python
from __future__ import annotations
import typing

def f(x: int, y: Undefined_ok) -> bool: ...
print(f.__annotations__)          # {'x': 'int', 'y': 'Undefined_ok', 'return': 'bool'}

try:
    typing.get_type_hints(f)      # NameError: name 'Undefined_ok' is not defined
except NameError as e:
    print(e)
Undefined_ok = str
print(typing.get_type_hints(f))   # {'x': <class 'int'>, 'y': <class 'str'>, 'return': <class 'bool'>}

# 以上 Python 3.12.5 实测：def 那行不再报错，但求值的那一刻照样抛
```

- 好处一：所有注解自动成为前向引用，引号可以全删。好处二：`list[int]`、`X | None` 这类"在旧解释器上立即求值会炸"的新语法可以提前写。⚠️ 但这是**推迟炸点而不是消除**：3.9 上字符串化的 `int | None` 平时没事，一旦某个库调用 `get_type_hints()`，`eval` 照样抛 `TypeError`。
- 坏处：`__annotations__` 里的值不再是对象，**任何按对象用注解的代码都会退化**。实测把一个哨兵对象当注解：stock 语义下 `ann["x"] is sentinel` 为真，字符串化后变成 `'sentinel'`，`is` 判断静默失效。手写引号还会被二次包裹，`def foo(a: "str")` 打印出 `{'a': "'str'"}`（官方 howto 明列此怪癖）。
- 运行时库被迫各写一套兼容层，而且**行为会与 stock 语义悄悄不同**。`dataclasses` 就是典型：它不 `eval` 字符串，而是用正则取出注解里的模块级标识符，再到**类的模块 `__dict__`** 里查它是不是 `typing.ClassVar`。实测在 `from __future__ import annotations` 下，模块级别名 `CV = ClassVar[int]` 仍能识别，而**类体内**的别名 `CV2 = ClassVar[int]; cv1: CV2` 识别不到——`cv1` 静默变成一个普通字段，`__init__` 多了必填参数；去掉那行 future import 又恢复正常。pydantic 与 FastAPI 同理要自己维护求值命名空间才能解析 `TYPE_CHECKING` 块里的名字。`typing.get_type_hints()` 是这套逻辑的标准化入口，但它只在**模块 globals 加类 namespace** 里求值——实测：函数内部定义的局部类，被嵌套函数标注成 `"Local"` 后 `get_type_hints()` 抛 `NameError`。
- 两个必须记住的取参：`get_type_hints()` 默认**剥掉 `Annotated` 的元数据**，要 `include_extras=True` 才拿得到 `Annotated[int, 'unit=ms']`（实测）；`inspect.signature()` 原样搬运注解，字符串模式下 `Parameter.annotation` 是 `'int'` 而非 `int`，要 `eval_str=True`（3.10+）才求值（实测）。

PEP 563 原本计划"将来成为默认"，**从未实现**，因为运行时消费方太痛。取代它的是第三套模型。

## Deferred Evaluation with PEP 649 and PEP 749

3.14 落地 PEP 649 并用 PEP 749 收尾（新增标准库模块 `annotationlib`）：**编译器为每个函数、类、模块生成一个 `__annotate__` 函数**，注解表达式留在函数体里，只有被访问时才执行。既不再立即求值，也不退化成一维字符串。

```python
def func(a: Cls) -> None: ...
class Cls: pass
print(func.__annotations__)     # {'a': <class 'Cls'>, 'return': None}
```

同一段代码在 3.13 及之前抛 `NameError`，在 PEP 563 下打印 `{'a': 'Cls', 'return': 'None'}`。上面是 3.14 的行为（本机 3.12 无法验证，按官方文档与 PEP 649 的示例记录）。要点：

- **前向引用不再需要引号**，因为求值发生在访问时。`__annotations__` 仍然可以读，但它现在是"触发求值"的入口，默认返回真对象（`Format.VALUE`）。上一节"立即求值"派生的三条后果里有两条被直接消掉：`def` 处的 `NameError` 不再可能，工厂函数也不再每次调用都执行注解；第三条也软化了——纯粹为注解服务的 import 可以留在 `if TYPE_CHECKING:` 里而不打断运行时读取。`from __future__ import annotations` 保留为**显式**字符串化路径，官方文档同时声明该行为最终会移除。
- `annotationlib.get_annotations(obj, format=...)` 是新的推荐入口，**取代** `inspect.get_annotations()`（3.10 到 3.13 的最佳实践）；`typing.get_type_hints()` 继续可用，`inspect.signature()` 会看到求值后的值。四种格式：

| Format | 返回值 | 给谁用 |
| :-- | :-- | :-- |
| `VALUE`（默认，值 1） | 求值后的对象，遇到未定义名字抛 `NameError` | 运行时库，需要真对象 |
| `FORWARDREF`（值 3） | 能解析的给真值，解析不了的给 `ForwardRef` 代理，不抛异常 | 检查器、文档工具，以及"类还没建完就要读注解"的场景 |
| `STRING`（值 4） | 近似源码的字符串 | 展示与序列化；不保证逐字符等于源码——常量运算、f-string、`and` / 三元 / 推导式会出错或报错 |
| `VALUE_WITH_FAKE_GLOBALS`（值 2） | 内部格式 | 支撑 `STRING` 与 `FORWARDREF` 的 fake globals 机制，第三方库不应传入，只应在被调用时返回与 `VALUE` 相同的结果或抛 `NotImplementedError` |

- 兼容性现状：`dataclasses` / pydantic / FastAPI 都必须在**同一版本解释器上同时处理三套语义**（旧式求值、563 字符串、649 惰性），所以它们各自维护一层注解读取适配；`typing_extensions` 提供 `get_annotations()` 的向后 backport，是库作者屏蔽差异的正确做法。元类最需要注意——3.14 起 class namespace 里可能根本没有 `__annotations__` 键，要改走 `get_annotate_from_class_namespace()` + `call_annotate_function()`，推荐用 `FORWARDREF`（类尚未创建完成，名字可能还不可解析）。
- 一个反直觉的安全后果：3.14 里**读注解等于执行代码**。`annotationlib` 文档明确警告 `get_annotations()` 可能调用任意 `__annotate__`、`ForwardRef.evaluate()` 可能 `eval` 任意字符串，注解体里可以是任何表达式；而 PEP 563 的字符串模式在读取阶段不执行代码——这是"字符串化"唯一比"直接给值"更安全的一处。

## Syntax Timeline Determined by Minimum Version

静态标注本身由 PEP 484（3.5，引入 `typing` 与检查器约定）与 PEP 526（3.6，变量与属性标注语法）奠基，下面每一行都只是增量。能用哪些语法由**最低支持版本**决定，而不是由开发机版本决定：

| 想要的写法 | 最低版本 | 更早的替代 |
| :-- | :-- | :-- |
| `list[int]` / `dict[str, X]`（PEP 585） | 3.9 | `typing.List[int]`，或加 `from __future__ import annotations` |
| `X \| None`（PEP 604） | 3.10 | `Optional[X]`，同上可字符串化绕过 |
| `Protocol`（PEP 544）/ `Literal` / `Final` / `TypedDict` | 3.8 | `typing_extensions` |
| `ParamSpec`（PEP 612）/ `TypeGuard`（PEP 647） | 3.10 | `typing_extensions` |
| `Unpack` / `TypeVarTuple`（PEP 646）/ `Required` / `NotRequired`（PEP 655）/ `Self`（PEP 673）/ `Never` / `assert_never` | 3.11 | `typing_extensions` |
| PEP 695 的 `def f[T]` 泛型函数语法与 `type Alias = ...`、`@override` | 3.12 | 显式 `TypeVar("T")` + `TypeAlias` 赋值 |
| 类型参数默认值 `class Stack[T = int]`（PEP 696） | 3.13 | `typing_extensions` |
| `TypeIs`（PEP 742）/ `ReadOnly`（PEP 705）/ `@deprecated`（PEP 702） | 3.13 | `typing_extensions` |
| 注解默认按需求值（PEP 649 / 749） | 3.14 | `from __future__ import annotations` |

PEP 695 不只是少写一行 `TypeVar`。实测（3.12.5）：

```python
def f[T](x: T) -> T:
    return x

type IntList = list[int]
print(f.__type_params__, IntList, type(IntList).__name__)   # (T,) IntList TypeAliasType
```

泛型类的 `G.__type_params__` 同理。**类型参数由此获得运行时身份**，检查器也能判断某个 `TypeVar` 属于哪个作用域——旧写法里跨函数复用同一个模块级 `TypeVar` 是长期存在的静默 bug 源。

## Type Narrowing

检查器沿控制流收紧变量的类型，这叫 narrowing。可靠手段只有几种：

| 手段 | 运行时 | 检查时 |
| :-- | :-- | :-- |
| `isinstance` / `issubclass` / `if x:` / `len(x) == 0` | 真实判断 | 在对应分支收窄 |
| `assert cond` | 真执行，但 `python -O` 会**整条删掉**（实测：`assert 1 == 2` 在 `-O` 下不抛，继续往下跑） | 收窄；用 `assert` 表达不变式等于放弃生产环境的检查 |
| `typing.cast(T, v)` | **原样返回 `v`**（实测 `cast(int, "hello")` 得 `"hello"`） | 无条件把表达式当 `T`，只骗检查器 |
| 守卫函数 `TypeGuard` / `TypeIs` | 普通函数调用 | 见下 |

`TypeGuard`（PEP 647）与 `TypeIs`（PEP 742，3.13）的差别不在"能不能收窄"，而在**可信度与方向**：

- `TypeGuard[X]` 只声明"返回 True 时参数算 X"。检查器**照搬 X 作为收窄结果**，不叠加已有知识（`Awaitable[int] | int` 经 `TypeGuard[Awaitable[Any]]` 会收成 `Awaitable[Any]` 而不是更精确的 `Awaitable[int]`），**负分支完全不收窄**，也不校验 X 与参数类型是否相容。
- `TypeIs[X]` 要求 X 与参数的声明类型相容——`def is_str(x: int) -> TypeIs[str]` 直接在定义处报错；并且**两个分支都收窄**：正分支取交集，负分支剔除 X 的兼容成员。它还在参数类型上不变（invariant），`TypeIs[bool]` 不能当 `TypeIs[int]` 传，否则会漏掉真实运行错误。
- 结论：`TypeGuard` 允许你的守卫逻辑悄悄撒谎，被污染的变量类型会扩散到下游；`TypeIs` 把同一类错误提前到定义期。3.13 起新项目默认用 `TypeIs`，只有确实需要"宽化"（从 `object` 收成不相关类型）时才留 `TypeGuard`。旧代码库两者会长期共存，因为把 `TypeGuard` 改成 `TypeIs` 可能暴露新的收窄错误。

穷尽性检查用 `match` 加 `assert_never`：default 分支里 `typing.assert_never(x)`，若联合类型仍有未覆盖成员，检查器报错。实测它的运行时是**显式 raise `AssertionError`**（不是 `assert` 语句），因此 `-O` 也删不掉——"用 assert 兜住不可能分支"要换成 `assert_never` 或手写 `raise`。`NoReturn` 说的是另一件事：函数**不会正常返回**（必抛、`sys.exit()`、死循环），标注它之后调用点后面的代码会被检查器判为不可达；`Never` 则是"不可能的值"，用于空联合与 `assert_never` 的参数。

## Structural versus Nominal Typing

| 机制 | 子类型判定 | 运行时行为 | 什么时候用 |
| :-- | :-- | :-- | :-- |
| `typing.Protocol`（PEP 544） | 结构化：形状对即可，不要求继承 | 默认不能 `isinstance`；`@runtime_checkable` 后只查**方法名是否存在** | 给第三方类型或隐式接口做标注，跨模块解耦 |
| `abc.ABC` | 名义：必须显式继承 | 实例化时未实现抽象方法直接 `TypeError`，可 `register()` 虚拟子类 | 自己写"必须实现"的框架基类 |
| `TypedDict` | 只作用于检查时 | **运行时就是普通 dict**，键与值都不校验 | 给 JSON / DB 行的形状做标注 |
| `typing.NamedTuple` | 名义，真 `tuple` 子类 | 有真构造器与字段名，但没有校验 | 不可变小记录 |
| `Final` / `Literal` | 只作用于检查时 | `Final` 不阻止再赋值；`Literal` 就是一组值 | 常量、字面量枚举 |
| `Annotated[T, ...]` | 透传给检查器 | `__metadata__` 是运行时可读的元组 | 给第三方库挂参数的唯一标准位置 |

实测两个容易踩的"运行时假安全感"：`isinstance([1], list[int])` 抛 `TypeError: isinstance() argument 2 cannot be a parameterized generic`；`@runtime_checkable` 的 Protocol 里声明 `thing(self, a, b)`，一个 `thing(self)` 的类照样被判 `True`——它只做名字存在性检查，不看签名也不看返回类型。真要校验得自己组合 `hasattr` 与 `inspect.signature`，或者交给 pydantic。

结构化与名义的分工细节在 [Data_Model](/docs/CS/Python/Data_Model.md)（含 `NamedTuple` 与 dataclass 家族），类型系统取哪一侧是语言层面的权衡，横向对照见 [Languages](/docs/CS/Languages.md)；静态结构类型做得更彻底的是 [TypeScript](/docs/CS/TypeScript/TypeScript.md)，它的结构化子类型与鸭子类型几乎同义，而 Python 的 `Protocol` 只是把这套判断搬到检查器里，运行时仍靠 ABC 的名义继承兜底。

`Annotated` 是 pydantic 与 FastAPI 契约的承载点：`Annotated[int, Field(gt=0)]` 之所以成立，正因为 `__metadata__` 在运行时读得到（见 [FastAPI](/docs/CS/Framework/FastAPI.md)）。

## Typed Third-Party Packages and Checker Config

- **PEP 561 `py.typed`**：包要让自己的 `.py` 注解被采信，必须在包目录里放一个空的 `py.typed` 标记文件；没有它，检查器把整包当 `Any`。有标记但注解不完备，可用 `partial` 变体。src 布局下这个文件常被打包配置漏掉（代码能跑、检查器看不见类型），修复属于打包配置的范畴。
- **typeshed**（`python/typeshed`）：标准库与第三方存根的事实来源，检查器内置它。它也是"规范与实现冲突"的暴露面——报错内容随 typeshed 与检查器版本一起变，升级检查器会出现"昨天过今天不过"，所以 CI 里要锁检查器版本。
- **`typing_extensions`**：超前于解释器版本的 API 落地处（`TypeIs`、`ReadOnly`、`deprecated`、`get_annotations` backport）。库作者只要支持多版本就该依赖它；应用只跑一个版本，用 `typing` 就够。
- **抑制手段**：`# type: ignore` 关掉整行所有错误，`# type: ignore[code]` 只关一个错误码。裸 ignore 是复利型技术债，因为它连"检查器升级后这条错误已经不存在"一起吞掉，必须配 `warn_unused_ignores` 把失效的 ignore 变回错误。pyright 侧对应 `# pyright: ignore[reportXxx]`。

mypy 常开的配置项（`--strict` 之外按需，取舍如下）：

| 选项 | 作用 | 取舍 |
| :-- | :-- | :-- |
| `disallow_untyped_defs` | 必须有完整注解 | 收益最大的一条，开前先建基线 |
| `disallow_incomplete_defs` | 禁止只注解一半 | 与上一条同开，否则半注解函数最危险 |
| `disallow_any_generics` | `list` 必须写成 `list[X]` | 裸泛型是隐式 `Any` 的主要入口 |
| `warn_return_any` | 返回 `Any` 时告警 | 挡住 `Any` 沿返回值传染出去 |
| `no_implicit_reexport` | 未显式 re-export 的名字不能被别处 import | 逼出稳定的公共 API 面 |
| `check_untyped_defs` | 无注解函数的体内也做检查 | 想早受益就开，代价是首轮报错量大 |
| `follow_imports = silent` | 只取依赖的类型、不报依赖的错 | 混合质量仓库的过渡措施 |

pyright 用 `basic` / `strict` 两个 mode 加 `reportXxx` 细粒度开关（`--level` 决定门槛）。它的 strict 会报大量 `Unknown` 系列（如 `reportUnknownMemberType`），大项目上通常按规则关掉。两者对边界规则的严格度不同，**一个仓库只认一个权威**，双跑只产噪声（工具矩阵见 [Ecosystem](/docs/CS/Python/Ecosystem.md)）。

## Runtime Validators Are a Different Job

静态标注在运行时不构成约束。任何来自进程外部的数据（HTTP body、CLI 参数、配置文件、消息队列）都必须过校验这一层。

| 工具 | 机制 | 定位 |
| :-- | :-- | :-- |
| beartype | `@beartype` 装饰器，把注解编成检查代码，装饰一次成型 | 断言内部契约、测试期抓误用；不处理外部数据 |
| typeguard | 装饰器 + **导入钩子**（对指定模块自动插桩，不需要逐处改代码） | 想要"不改代码就全量插桩"的调试与灰度 |
| pydantic / attrs validator | 显式模型 + `validate` | **外部边界**：结构、类型、范围一体的校验层 |
| msgspec | 显式模型 + `encode` / `decode` / `convert` | 边界处的编解码，形状由 schema 决定，与 pydantic 的分工见 Data_Model 的家族表 |

判断标准是失败该怪谁：`@beartype` 抛错说明**你自己的代码有 bug**；pydantic 抛错说明**来的数据不合法**，应该变成 400 而不是 500。把两者混用会把校验成本推进热路径。这条铁律值得单独钉一句：**加满注解不会让程序对坏输入更安全**，它只让读代码的人和检查器更早发现误用。

## Incremental Adoption Strategy

1. **先建基线，不要先立目标。** pyright 的 `--createbaseline` 把当前错误数写进 `pyrightconfig.json`，存量错误不再阻塞、新增错误立即报错；mypy 侧对应按模块豁免（`ignore_missing_imports`、`follow_imports`）加逐目录放开。核心是把"零错误"改造成**不可回退的单调目标**。
2. **从 public API 与数据边界开始**：包对外暴露的函数、序列化入口、跨模块 DTO。这些位置的注解会传导给调用方，收益最高且不需要动内部实现。
3. **`--strict` 是终点不是起点。** 一上来全开会在几千条错误里失去判断力。可执行的推进序大致是 `check_untyped_defs` → `disallow_untyped_defs` → `disallow_any_generics` → `warn_unused_ignores` → `no_implicit_reexport` → `--strict`。
4. 分批迁移的三个真痛点：**隐式 Any**（无注解依赖、`__getattr__` 动态属性、缺 `py.typed` 的第三方包，使参数退化成 `Any` 并静默放行）；**`Any` 传染**（一个 `Any` 参与运算，结果通常仍是 `Any`，一路扩散到返回值，所以 `warn_return_any` 要早开）；**版本错配**（typeshed、检查器、`typing_extensions` 与解释器四者任意升级都可能冒出新错，CI 必须锁版本）。
5. 检查器只认它**能静态解析的代码**：动态属性、插件注册表、`eval` 构造的类在静态侧等于不存在。这类结构要么给存根，要么显式标 `Any` 并留注释，不要指望注解替它们工作。

## Annotate versus Validate versus Serialize

三件事三套工具，常见错配是"内部对象全在用 pydantic 验证"或"写满注解就以为校验过了"：

| 需求 | 工具 | 运行时开销 | 交叉笔记 |
| :-- | :-- | :-- | :-- |
| 给检查器与 IDE 信息 | `typing` 语法 + mypy / pyright | 仅注解表达式在 `def` / 类体执行时求值那一次（3.14 起连这次也推迟到访问时） | [Data_Model](/docs/CS/Python/Data_Model.md) |
| 内部契约断言 | `@beartype`、`TypeIs`、`assert_never` | 每次调用 | [Ecosystem](/docs/CS/Python/Ecosystem.md) |
| 外部输入建模 | pydantic / attrs validator | 构造时全量校验 | [FastAPI](/docs/CS/Framework/FastAPI.md) |
| 编解码 | `json`、msgspec、pickle | 序列化路径 | [NumPy](/docs/CS/Python/NumPy.md) |

## Links

- [Python](/docs/CS/Python/Python.md)
- [Languages](/docs/CS/Languages.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [Memory](/docs/CS/Python/Memory.md)

## References

- [PEP 484 – Type Hints](https://peps.python.org/pep-0484/)
- [PEP 526 – Syntax for Variable Annotations](https://peps.python.org/pep-0526/)
- [PEP 563 – Postponed Evaluation of Annotations](https://peps.python.org/pep-0563/)
- [PEP 649 – Deferred Evaluation Of Annotations Using Descriptors](https://peps.python.org/pep-0649/)
- [PEP 749 – Implementing PEP 649](https://peps.python.org/pep-0749/)
- [PEP 561 – Distributing and Packaging Type Information](https://peps.python.org/pep-0561/)
- [PEP 585 – Type Hinting Generics In Standard Collections](https://peps.python.org/pep-0585/)
- [PEP 604 – Allow writing union types as X \| Y](https://peps.python.org/pep-0604/)
- [PEP 544 – Protocols: Structural subtyping (static duck typing)](https://peps.python.org/pep-0544/)
- [PEP 647 – User-Defined Type Guards](https://peps.python.org/pep-0647/)
- [PEP 742 – Narrowing types with TypeIs](https://peps.python.org/pep-0742/)
- [PEP 695 – Type Parameter Syntax](https://peps.python.org/pep-0695/)
- [PEP 696 – Type Defaults for Type Parameters](https://peps.python.org/pep-0696/)
- [PEP 646 – Variadic Generics](https://peps.python.org/pep-0646/)
- [PEP 655 – Marking individual TypedDict items as required or potentially-missing](https://peps.python.org/pep-0655/)
- [PEP 673 – Self Type](https://peps.python.org/pep-0673/)
- [PEP 705 – TypedDict: Read-only items](https://peps.python.org/pep-0705/)
- [PEP 702 – Marking deprecations using the type system](https://peps.python.org/pep-0702/)
- [typing – Support for type hints](https://docs.python.org/3/library/typing.html)
- [annotationlib – Functionality for introspecting annotations](https://docs.python.org/3/library/annotationlib.html)
- [Annotations Best Practices](https://docs.python.org/3/howto/annotations.html)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [Typing Python with Static Analysis](https://typing.readthedocs.io/en/latest/)
- [typeshed](https://github.com/python/typeshed)
- [mypy configuration file](https://mypy.readthedocs.io/en/stable/config_file.html)
- [Using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html)
- [Pyright](https://github.com/microsoft/pyright)
- [typing_extensions](https://pypi.org/project/typing-extensions/)
- [beartype documentation](https://beartype.readthedocs.io/en/latest/)
- [Pydantic documentation](https://docs.pydantic.dev/latest/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
