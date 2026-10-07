## Introduction

Python 没有 `interface` 关键字，但 `for`、`with`、`len()`、`a[i]`、`a + b` 对任何类型都能用。原因是语法层根本不问类型，只问"有没有实现某个固定名字的方法" —— 这些名字就是**特殊方法（special method，俗称 dunder）**，它们组成的约定叫**协议（protocol）**：实现 `__iter__`/`__next__` 就得到可迭代对象，实现 `__get__`/`__set__` 就拿到属性访问的拦截点，实现 `__set_name__` 就知道自己被绑到了哪个字段。于是"鸭子类型为什么能工作"可以精确成一句：**语法先被翻译成 dunder 调度，然后去类型上找实现**。

本篇只讲这套调度与协议本身：属性查找、描述符、类构造链、MRO 与 `super()`、数据类家族选型、不可变性与哈希契约。类型标注与注解求值见 [Typing.md](/docs/CS/Python/Typing.md)，`__slots__` 的内存数字见 [Memory.md](/docs/CS/Python/Memory.md)。

## Protocol-Oriented Dispatch

| 语法 / 内置函数                | 实际调度                                    | 要点                                                                                             |
| :------------------------- | :-------------------------------------- | :--------------------------------------------------------------------------------------------- |
| `for x in it`              | `iter(it)` → `__iter__`，随后反复 `__next__` | 没有 `__iter__` 时退回旧式序列协议：`__getitem__(0)`、`__getitem__(1)`… 直到 `IndexError`（实测 `iter()` 也接受这种对象）      |
| `with e as v`              | `__enter__` / `__exit__`                | `contextlib.contextmanager` 把生成器包装成实现了这两个方法的对象，异常在 `yield` 处重新抛出                                |
| `async with` / `await`     | `__aenter__` / `__aexit__` / `__await__` | 与同步版是**不同协议**，同一个对象要两套都实现才能两边都用                                                               |
| `a + b`                    | `a.__add__(b)` → 拒绝后试 `b.__radd__(a)`   | 若 `type(b)` 是 `type(a)` 的严格子类，`__radd__` 优先；两边都拒绝才 `TypeError`                                    |
| `len` / `a[i]` / `x in a` / `a()` | `__len__` / `__getitem__` / `__contains__` / `__call__` | `in` 缺 `__contains__` 时退回 `__iter__`，再退回 `__getitem__`                                       |

```python
class N:
    def __init__(self, v): self.v = v
    def __add__(self, o):
        print("N.__add__ <-", type(o).__name__)
        return NotImplemented
class M:
    def __radd__(self, o):
        print("M.__radd__ <-", type(o).__name__)
        return "M handled"
print(N(1) + M())          # 左边拒绝，右边接手
try: print(N(1) + 2)       # 两边都拒绝
except TypeError as e: print("TypeError:", e)
```

```text
# Python 3.12.5 实测
N.__add__ <- M
M.__radd__ <- N
M handled
N.__add__ <- int
TypeError: unsupported operand type(s) for +: 'N' and 'int'
```

> [!WARNING]
> `NotImplemented` 不是异常，也不是 `NotImplementedError`，它是**交还给解释器**继续调度的信号。`__eq__` 里两边都返回它时，解释器最终退回身份比较（实测两个不同实例 `==` 为 `False`，同一对象为 `True`），这就是 `x == y` 几乎从不抛异常的原因 —— 所以 `__eq__` 遇到不认识的类型要返回 `NotImplemented`，不要抛异常，也不要直接返回 `False`。

## Why Special Methods Live on the Type

解释器自己发起的调用只查 `type(obj).__mro__` 上的类型槽位，**完全绕过实例 `__dict__`**；而 `obj.m()` 是普通属性查找，实例属性优先。两套规则同时存在：

```python
class C: pass
c = C()
c.__len__ = lambda: 42          # 绑到实例
try: len(c)
except TypeError as e: print("TypeError:", e)
C.__len__ = lambda self: 42     # 绑到类型
print(len(C()))
class E:
    def m(self): return "class method"
e = E(); e.m = lambda: "instance attr"
print(e.m())
```

```text
# Python 3.12.5 实测
TypeError: object of type 'C' has no len()
42
instance attr
```

后果有两个：给实例打 dunder 补丁必然无效（mock 长度协议得 patch 到**类**上）；实例上写 `__len__`、`__init__` 这类名字不报错，但它是彻底的死代码。反过来看这正是"协议"的经济学解释 —— 槽位在类型上固定，调用点不必每次做属性查找，代价是实例级多态被取消。

## Attribute Lookup Order

`object.__getattribute__` 的优先级是固定的：**数据描述符 > 实例 `__dict__` > 非数据描述符 / 类属性 > `__getattr__` 兜底**。

```python
from functools import cached_property
class Val:                                   # 数据描述符（有 __set__）
    def __set_name__(self, owner, name): self.name = "_" + name
    def __get__(self, obj, objtype=None):
        return self if obj is None else obj.__dict__.get(self.name)
    def __set__(self, obj, value): obj.__dict__[self.name] = value
class A:
    val = Val()
    @cached_property
    def heavy(self): return sum(range(100))   # 非数据描述符
    cls_attr = "class-level"
    def __getattr__(self, k): return f"<fallback {k}>"
a = A()
a.val = 1
a.__dict__["val"] = "hacked"                 # 数据描述符优先，实例 dict 遮蔽不住
print(a.val, "|", a.__dict__)
a.__dict__["heavy"] = "from dict"            # 非数据描述符让位给实例 dict
print(a.heavy, "|", A.__dict__["heavy"].__class__.__name__, "没有 __set__:", not hasattr(cached_property, "__set__"))
a.cls_attr = "shadow"
print(a.cls_attr, A.cls_attr, "|", a.nope)
```

```text
# Python 3.12.5 实测
1 | {'_val': 1, 'val': 'hacked'}
from dict | cached_property 没有 __set__: True
shadow class-level | <fallback nope>
```

- `__getattr__` 是**兜底**，只在正常查找全失败后触发；`__getattribute__` 是**每次读属性都经过的入口**，重写它必须自己调 `object.__getattribute__(self, name)`，而里面任何一次属性读取都会再进自己 —— 极易递归。`__setattr__` / `__delattr__` 同理拦截全部赋值与删除，实现里写 `self.x = v` 就是死循环（`RecursionError`），要落盘只能 `object.__setattr__(self, k, v)` 或直接操作 `self.__dict__[k]`。
- 描述符收到 `obj is None` 表示"在类上访问"（`A.val`），`property` 与 `classmethod` 的行为差异全靠这个区分。
- `property` 只是把三个方法包起来的内置数据描述符（`vars(property)` 含 `__set__`）。`functools.cached_property` 是**非数据描述符**：算完写进实例 `__dict__`，第二次由实例 dict 抢先命中 —— 所以它必须有 `__dict__`。`slots=True` 的 dataclass 上实测 `TypeError: No '__dict__' attribute on 'WithCP' instance to cache 'double' property.`，`frozen=True` 同理写不进去。
- `__dict__` 与 `__weakref__` 本身就是 `getset_descriptor`，且**每个可存属性的类各带一个**（实测 `object.__dict__` 里没有 `__dict__`）；`__slots__ = ("x",)` 生成的是 `member_descriptor`。基类没有 `__slots__` 时，子类加了也仍然有 `__dict__`（实测）。

## The Descriptor Protocol

一个 15 行描述符，同时做**赋值校验**与**首次访问时延迟计算**：

```python
class Field:
    def __init__(self, default=None, *, check=lambda v: True):
        self.default, self.check = default, check
    def __set_name__(self, owner, name):
        self.name = "_" + name                          # 类创建完成后立刻被调
    def __get__(self, obj, objtype=None):
        if obj is None: return self
        if self.name not in obj.__dict__:               # 延迟：首次访问才落地
            obj.__dict__[self.name] = self.default() if callable(self.default) else self.default
        return obj.__dict__[self.name]
    def __set__(self, obj, value):
        if not self.check(value): raise ValueError(f"{self.name} 拒绝 {value!r}")
        obj.__dict__[self.name] = value

class Order:
    total = Field(0, check=lambda v: isinstance(v, int) and v >= 0)
    label = Field(lambda: "heavy-computed")
o = Order()
print(o.total, o.label, o.__dict__)
o.total = 5
try: o.total = -1
except ValueError as e: print("ValueError:", e)
```

```text
# Python 3.12.5 实测
0 heavy-computed {'_total': 0, '_label': 'heavy-computed'}
ValueError: _total 拒绝 -1
```

数据 / 非数据的判据是**实现了 `__set__` 或 `__delete__`**（CPython 只看一个 `tp_descr_set` 槽位，两个名字都会置位）：实测只有一个 `__delete__` 的描述符同样压得住实例 dict。写缓存类描述符时要**故意不写 `__set__`**，否则自己的写回永远读不到。而 `__set_name__(owner, name)` 是"字段声明式 API"能成立的唯一关键 —— 类体里 `total = Field(...)` 只是造了个被所有实例共享的描述符对象，字段名只有 `__set_name__` 知道。

这套协议无处不在：`property`、`classmethod`、`staticmethod`、**普通函数本身**（`f.__get__(obj)` 就是 bound method 的来源，`self` 是描述符协议塞进来的第一个参数，不是关键字）、`__slots__` 的 `member_descriptor`、`abc.abstractmethod`（只给函数打 `__isabstractmethod__` 标记，绑定仍委托内层的 `classmethod`/`property` 描述符）、以及 ORM 的列对象（声明期收类型 → `__set_name__` 收字段名 → `__get__`/`__set__` 代理到实例状态字典）。

## Class Creation Chain

`C(*args)` → `type(C).__call__` → `C.__new__(C, *args)` → **只有当 `__new__` 返回 `C` 的实例时**才 `C.__init__(self, *args)`。`__init__` 的返回值被忽略，返回非 `None` 直接 `TypeError: __init__() should return None, not 'int'`（实测）。

```python
class T:
    def __new__(cls, *a, **k): print("__new__"); return super().__new__(cls)
    def __init__(self, v=0): print("__init__", v)
T(3)
T.__new__(T)                       # 绕过 type.__call__，不触发 __init__
class Singleton:
    _inst = None
    def __new__(cls):
        if cls._inst is None: cls._inst = super().__new__(cls); print("created")
        else: print("reused")
        return cls._inst
    def __init__(self): print("__init__ 每次都会再跑")
s1 = Singleton(); s2 = Singleton()
print(s1 is s2)
class Model:
    registry = []
    def __init_subclass__(cls, table=None, **kw):
        super().__init_subclass__(**kw)
        cls.table = table or cls.__name__.lower(); Model.registry.append(cls)
class User(Model, table="t_user"):
    name = Field(); age = Field()          # Field 即上一节的描述符
print([(c.__name__, c.table) for c in Model.registry], User.name.name, User.age.name)
```

```text
# Python 3.12.5 实测
__new__
__init__ 3
__new__
created
__init__ 每次都会再跑
reused
__init__ 每次都会再跑
True
[('User', 't_user')] _name _age
```

单例的坑就在倒数第二行：`__new__` 缓存了实例，`__init__` 却照样每次重跑，所以初始化要么幂等，要么把"只做一次"的判断挪进 `__new__`。`__init_subclass__` 与 `__set_name__`（PEP 487，3.6+）拿掉了 metaclass 的大部分用武之地 —— 注册子类、给字段绑名字都能写成普通方法，随继承自然传播、支持多继承、还能收关键字。

metaclass 的代价：多继承时子类的 metaclass 必须是所有基类 metaclass 的子类，否则实测 `TypeError: metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of the metaclasses of all its bases`；介入点有 `__prepare__`（决定 class body 用哪个 mapping 收集）、`__new__`、`__init__` 三处；对读代码的人不透明，两个不兼容的 metaclass 只能再写一个合并类。

判断标准：需求落在**类对象本身**而不是实例上时才用 metaclass —— 需要控制创建顺序或拦截创建的全局注册表、强制 API 约束（禁止子类覆盖某方法、必须声明某类属性）、需要在类体求值前换掉命名空间容器。其余情况先试 `__init_subclass__` + 描述符 + 类装饰器，这三者已能覆盖旧代码里绝大多数 metaclass。

## MRO and super()

C3 线性化只有三条规则：保持基类列表的局部顺序、子类一定排在其所有父类之前、必要时把共同基类往后推。它**不是深度优先**（深度优先会得到 `K, L, Base, object, E, M`，把 `object` 排到 `E` 之前，违反第二条），也常被误记成"从右往左"。`super()` 同样按 MRO 走：它的含义是"沿 `type(self).__mro__`，从 `super().__self_class__` 之后再往后一个"，**不是"父类"**。

```python
class Base: pass
class E(Base): pass
class L(Base): pass
class M: pass
class K(L, E, M): pass
print([c.__name__ for c in K.__mro__])
class A: pass
class B(A): pass
try:
    class C(A, B): pass          # 局部顺序与继承顺序矛盾
except TypeError as e: print("TypeError:", e)
class D:
    def m(self): print("D.m")
class X(D):
    def m(self): print("X.m: super() 起点 =", super().__self_class__.__name__, "| X.__bases__[0] =", X.__bases__[0].__name__); super().m()
class Y(D):
    def m(self): print("Y.m"); super().m()
class Z(X, Y): pass
print([c.__name__ for c in Z.__mro__]); Z().m()
```

```text
# Python 3.12.5 实测
['K', 'L', 'E', 'Base', 'M', 'object']
TypeError: Cannot create a consistent method resolution
order (MRO) for bases A, B
['Z', 'X', 'Y', 'D', 'object']
X.m: super() 起点 = Z | X.__bases__[0] = D
Y.m
D.m
```

`X.m` 里 `super()` 落到 `Y` 而不是 `X` 的父类 `D` —— 起点是**实际实例的类**，所以同一个 `super()` 在不同调用路径上指向不同目标。协作链条断掉的两个真实场景（均实测）：

1. 中间类吃掉参数却不调 `super().__init__()`：`class Leaf(Mid, Base)` 中 `Mid.__init__` 不调 `super()`，`Base.__init__` 就静默不执行 —— 没有报错，只有没初始化的字段。
2. 链上某个类的 `__init__` 不接收 `**kwargs`：多传一个参数就 `TypeError: Strict.__init__() got an unexpected keyword argument 'extra'`。

所以 mixin 的写法是固定的：`__init__(self, **kw)` 收下并消费自己认识的键，末尾 `super().__init__(**kw)`，链上必须有一个类负责吸收剩余参数。

## The Data-Class Family

| 方案 | 运行时形态 | 可变 | 校验 / 序列化 | 什么时候选 |
| :--- | :--- | :--- | :--- | :--- |
| `tuple` | 定长不可变序列 | 否 | 无 | 两三个字段、纯位置语义、要当字典键 |
| `typing.NamedTuple` | `tuple` 子类，`__slots__ = ()`（实测类与实例都没有 `__dict__`） | 否 | 无 | 需要字段名与解包、跨函数传递零成本；但它仍参与元组比较，字段顺序一改语义静默变化 |
| `dataclasses.dataclass` | 生成 `__init__`/`__repr__`/`__eq__` | 默认是 | 无 | 库内部值对象的默认答案；`frozen=True` 禁写并在 `eq=True` 时自动生成 `__hash__`，`slots=True` 用 `__slots__` 重建类，`kw_only=True`（3.10+）强制关键字以躲开顺序陷阱 |
| `attrs`（第三方） | 同上，选项更早更全 | 可 | 可选 validator | 需要 `field(factory=...)`、默认 slots、冻结 + 转换器组合时 |
| `typing.TypedDict` | **就是普通 dict** | 是 | 无（只有静态标注） | 只想给已有字典结构标注形状，不需要构造器与方法（见 [Typing.md](/docs/CS/Python/Typing.md)） |
| `pydantic.BaseModel`（第三方） | 独立类，字段带验证器 | 可配 | 运行时校验 + 序列化 | 外部边界（HTTP / JSON / 配置）；代价是构造明显变慢、字段名要额外 alias 映射。Web 层见 [FastAPI.md](/docs/CS/Framework/FastAPI.md) |
| `msgspec.Struct`（第三方） | 紧凑布局的 struct | 可配 | 不做运行时类型校验，只做编解码 | 性能敏感的 RPC / 消息通道 |
| `recordclass` 一类 | 可变版命名元组 | 是 | 无 | 只作为"字段访问 + 可写 + 省内存"这个很窄的生态位记住 |

可变默认值的根因不是 dataclass 的怪癖，而是**默认值在 `def` 执行时求值一次**、存进函数的 `__defaults__`，所有调用共享同一个对象：

```python
from dataclasses import dataclass, field
def bad(items=[]):
    items.append(1); return items
print(bad(), bad())
try:
    @dataclass
    class Bad:
        items: list = []
except ValueError as e: print("ValueError:", e)
@dataclass
class Good:
    items: list = field(default_factory=list)
print(Good(), Good())
```

```text
# Python 3.12.5 实测
[1, 1] [1, 1]
ValueError: mutable default <class 'list'> for field items is not allowed: use default_factory
Good(items=[]) Good(items=[])
```

dataclass 的 `__post_init__` 用来做派生字段与跨字段校验，但类是 `frozen=True` 时那里赋不了值 —— 得回到本篇前面的机制：`object.__setattr__(self, "full_name", ...)`。

## Immutability and the Hash Contract

契约只有一条：`a == b` ⇒ `hash(a) == hash(b)`，反向不要求；它跨类型也成立（实测 `hash(1) == hash(1.0)` 为 `True`，`{1, 1.0, True}` 长度是 1）。

- 自定义 `__eq__` 会让 `__hash__` 变成 `None`（实测），实例随即 `TypeError: unhashable type` —— 这是刻意设计：按内容相等通常意味着内容可变。
- `@dataclass` 默认 `eq=True` 且非 frozen ⇒ `__hash__ = None`；只有 `frozen=True`（且 `eq=True`）才自动给 `__hash__`；`eq=False` 则继承 `object.__hash__`（三个 case 均实测）。
- 参与哈希的字段变了，对象就从集合里"丢"了：

```python
class Box:
    def __init__(self, v): self.v = v
    def __hash__(self): return hash(self.v)
    def __eq__(self, o): return self.v == o.v
b = Box(1); s = {b}
b.v = 2
print(b in s, len(s), list(s)[0] == b, list(s)[0].v)
s.discard(b); print(len(s))
```

```text
# Python 3.12.5 实测
False 1 True 2
1
```

桶位置按新哈希算，旧元素成了"遍历得到、`==` 成立、却删不掉"的幽灵。修复只有一个方向：改值就整个替换（重建集合）—— 旧值一改，连删除都定位不到。

## Boundary with Static Typing and Memory

协议是运行时约定，静态侧有两种互补表达：`typing.Protocol` 是**结构化子类型**（不显式继承也能通过类型检查，加 `runtime_checkable` 后 `isinstance` 只核对方法名是否存在）；`abc.ABC` 是**名义子类型**（必须显式继承，但能 `register()` 虚拟子类、能在实例化时强制未实现的方法）。要"运行时强制必须实现"用 ABC，只想给检查器描述形状用 Protocol —— 细节都在 [Typing.md](/docs/CS/Python/Typing.md)。

`__slots__` 的收益与它破坏的东西（`cached_property`、动态属性、多继承时重复 slot 抵消收益）记在 [Memory.md](/docs/CS/Python/Memory.md)，本篇不给字节数。

## Links

- [Python](/docs/CS/Python/Python.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [Languages](/docs/CS/Languages.md)
- [Reflection](/docs/CS/Go/Reflection.md)

## References

- [Python Documentation — Data model](https://docs.python.org/3/reference/datamodel.html)
- [Descriptor HowTo Guide](https://docs.python.org/3/howto/descriptor.html)
- [dataclasses — Generated Python Data Classes](https://docs.python.org/3/library/dataclasses.html)
- [functools — Higher-order functions and callable](https://docs.python.org/3/library/functools.html)
- [contextlib — Utilities for with-statement contexts](https://docs.python.org/3/library/contextlib.html)
- [abc — Abstract Base Classes](https://docs.python.org/3/library/abc.html)
- [typing — Support for type hints](https://docs.python.org/3/library/typing.html)
- [PEP 487 — Simpler customisation of class creation](https://peps.python.org/pep-0487/)
- [The Python 2.3 Method Resolution Order](https://www.python.org/download/releases/2.3/mro/)
- [attrs documentation](https://www.attrs.org/en/stable/)
- [msgspec on PyPI](https://pypi.org/project/msgspec/)
- [Pydantic documentation](https://docs.pydantic.dev/latest/)
