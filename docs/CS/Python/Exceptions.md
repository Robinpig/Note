## Introduction

Python 的异常不是错误码的语法糖，而是一条**主控制流通道**：迭代靠 `StopIteration` 收尾，`with` 靠 `__exit__` 的返回值决定要不要吞异常，协程取消靠 `CancelledError`。读这套机制要回答三件事：**类型层级**决定你能捕获什么，**链与 traceback** 决定你事后能看到什么，**全局钩子**决定进程崩掉时还剩什么。版本基线：机制结论覆盖 3.11 – 3.14；标 `实测` 的输出来自本机 `python3` 3.12.5（macOS arm64），换机器换版本需重跑；3.14 专有行为本机不能验证，只按官方文档陈述并就地标注版本。

## The BaseException boundary

`BaseException` 的直接子类里只有 `Exception` 以下是"程序内部可讨论恢复的错误"，另外三个是**运行时要往外走的信号**：`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`。实测三者都"caught only by except BaseException"，而 `ValueError` 会被 `except Exception` 接住；`KeyboardInterrupt.__mro__` == `['KeyboardInterrupt', 'BaseException', 'object']`。所以 **`except Exception` 才是不吞中断的写法**，裸 `except:` 等价于 `except BaseException:`，会把 Ctrl-C 一起吃掉。

同理 3.8 起 `asyncio.CancelledError` 也直接挂 `BaseException`（实测 MRO 同上）——取消不是错误，`except Exception` 抓不到它是有意的，别补一个 `except BaseException` 把它捞回来（见 [Asyncio](/docs/CS/Python/Asyncio.md)）。反方向的例子：3.7 起（PEP 479）生成器内部逃逸的 `StopIteration` 被转成 `RuntimeError`，原异常留在 `__cause__`（实测 `generator raised StopIteration`）。

## Four clauses of try

`try` 至少配一个 `except` 或 `finally`，只写 `else` 会报 `SyntaxError: expected 'except' or 'finally' block`（实测）。

| 子句 | 运行时机 | 容易踩的点 |
| :--- | :--- | :--- |
| `try` | 总是 | 范围越大，`except` 越容易误捕别处的异常 |
| `except` | 类型匹配时（逗号是"或"） | `except (A, B) as e` 的括号在 3.14 前不可省 |
| `else` | 见下 | 里面的异常**不会**被前面的 `except` 接住 |
| `finally` | 总是，含 `return` 往外走时 | 里面的 `return` 会吞掉正在传播的异常 |

`else` 的唯一价值是**缩小 try 范围**：语言参考的措辞是"控制流离开 try suite、没有抛出异常、并且没有执行 `return` / `continue` / `break`"才运行 `else`。把"会出错的那一行"留在 `try`，把"出错就说明别处有 bug"的后续动作放进 `else`，`except` 就不会顺手把后者也咽掉（实测：`try` 里 `return` 时 `else` 不运行，`finally` 仍运行）。

`finally` 与 `return` 的交互最危险：`finally` 里的 `return` 总是最后被执行的那个 return，并且丢弃正在传播的异常——实测 `try: 1/0` 配 `finally: return "swallowed"` 得到 `swallowed`，3.12 全程无提示。**3.14 起（PEP 765）编译器会对任何"效果上是离开 finally 块"的 `return` / `break` / `continue` 发 `SyntaxWarning`**，行为暂未改变，PEP 保留升级为 `SyntaxError` 的余地。抑制办法是加过滤器 `ignore::SyntaxWarning`（如 `-Werror -Wignore::SyntaxWarning` 或 `PYTHONWARNINGS=error,ignore::SyntaxWarning`），且**运行时改过滤器只影响之后才编译的代码**，已 import 的模块照样报警。

两个附带机制。其一，`except ... as e` 的 `e` 在子句结束时被自动删除（实测 `after block, 'e' in locals? False`），因为异常 → traceback → frame → 局部变量是一条引用环：实测把异常存进字典后，一个 10 MB 的 `bytearray` 跨过 `gc.collect()` 仍然活着，丢掉异常对象才释放（回收侧见 [Memory](/docs/CS/Python/Memory.md)）。其二，`with` 也参与吞异常——`__exit__` 返回真值即抑制，见 [Data_Model](/docs/CS/Python/Data_Model.md)。

## Raise, chains and tracebacks

| 写法 | 效果 |
| :--- | :--- |
| `raise`（裸） | 重抛当前异常并保留原 traceback；无活动异常时 `RuntimeError: No active exception to reraise`（实测） |
| `raise X` | 新异常；若正处在 `except` 块里，`__context__` 自动指向被处理的那个 |
| `raise X from Y` | 设 `__cause__ = Y`，打印 "The above exception was the direct cause of…" |
| `raise X from None` | 只设 `__suppress_context__`：`__context__` **仍挂在对象上**（实测 `KeyError('k')` + `suppress: True`），只是不再显示 |

`from Y` 是"这是我这一层的错，Y 是原因"；`from None` 是"把底层翻译成本层抽象，底层细节不值得看"。隐式链的措辞是 "During handling of the above exception, another exception occurred:"（实测），它表示"处理上一个异常时又出了别的错"，通常正是你没料到的那一条，看到就先怀疑 `except` 块本身。

`tb_frame` / `tb_lineno` / `tb_next` 构成 traceback 链表；打印用 `traceback.format_exception(exc)`，要延迟到日志或测试里再渲染就用 `traceback.TracebackException.from_exception(exc)`（实测 `stack frames: ['<module>']`）。`X.with_traceback(tb)` 把别处的栈贴到新异常上（线程池转发 future 结果就是这条路），不要拿它伪造来源。

真正让人读不懂日志的是**显式重抛会给同一个帧追加条目**：

```python
def deep():
    raise ValueError("origin")

def explicit():
    try: deep()
    except ValueError as e: raise e        # 显式重抛

def bare():
    try: deep()
    except ValueError: raise               # 裸重抛
```

```text
# Python 3.12.5 实测，帧 = (函数名, tb_lineno)
explicit: 4 entries, [('<module>', 20), ('explicit', 6), ('explicit', 5), ('deep', 2)]
bare:     3 entries, [('<module>', 20), ('bare', 9), ('deep', 2)]
```

`explicit` 出现两次：一次是 `deep()` 的调用点，一次是 `raise e` 那一行。把重抛放进循环再来 4 次，实测 8 帧里同一个函数占 6 帧；裸 `raise` 则不追加当前帧。这就是"日志看起来在原地打转"的根因，也是优先写裸 `raise` 的理由。

## Additions in 3.11

- **PEP 654 `ExceptionGroup` 与 `except*`**：一次上交多个互不相干的异常。`except*` 按类型**切分**整组，未被任何 handler 匹配的部分在所有 handler 跑完后重新抛出（实测 `handled: (ValueError('v'),)` / `leftover: ExceptionGroup … (KeyError('k'),)`）。显式版本是 `split()` 与 `subgroup()`，二者都会**递归下钻嵌套组**（实测嵌套 `split(ValueError)` 返回内层组）。它存在的理由是 `asyncio.TaskGroup`：并发任务的失败必须一起上交（实测 `except* ValueError -> (ValueError('bad 0.01'),)`，因为第一个失败后其余任务被取消，而取消不算失败）。`ExceptionGroup` 拒绝装 `BaseException` 子类（实测 `TypeError: Cannot nest BaseExceptions in an ExceptionGroup`），与"中断不是错误"一致。机制见 [Asyncio](/docs/CS/Python/Asyncio.md)。
- **PEP 678 `add_note()`**：补上下文而**不换掉类型**（实测 `str()` 仍是 `division by zero`、`__notes__` 两条、类型仍是 `ZeroDivisionError`）。note 会进默认 traceback，也随 `__dict__` 被 pickle 带走。
- **PEP 657 列级 caret**：`~^~` 指出是哪个子表达式出的错，数据来自 code object 的 `co_positions()`；嫌占内存可用 `-X no_debug_ranges` 或 `PYTHONNODEBUGRANGES` 关掉。实测：

  ```text
      return data["a"][5] + data["missing"]
             ~~~~~~~~~^^^
  IndexError: list index out of range
  ```

- **zero-cost exceptions**：3.11 起不抛异常时 `try` 不再有实质开销（实测 `4.2 ns/op`），旧的 `SETUP_FINALLY` / `POP_BLOCK` 被编译期异常表取代，对应 [Bytecode](/docs/CS/Python/Bytecode.md) 里块栈的重做。

## Syntax change in 3.14

PEP 758 允许在**不使用 `as`** 时省掉多类型的分组括号（3.14 起；本机 3.12 会报 `SyntaxError`，不要拿本机验证）：

```python
try:
    connect_to_server()
except TimeoutError, ConnectionRefusedError:      # 3.14 起合法
    print("network gone")
```

## EAFP vs LBYL

EAFP（先做再捕获）优于 LBYL（先检查再用）有三条根因：

1. **原子性**。`if k in d: v = d[k]` 是两步，中间窗口里别的线程可能改表；`try: v = d[k]` / `except KeyError` 只有一步。GIL 只保证单条字节码级别的安全，不保证复合操作（见 [GIL](/docs/CS/Python/GIL.md)）。文件系统同理：`os.path.exists()` 与 `open()` 之间文件可被删除或换成符号链接（TOCTOU），而直接 `open()` 再按 `FileNotFoundError` / `PermissionError` 分支永远反映真实结果。
2. **多态**。鸭子类型下你无法可靠地问"你有没有这个属性"，`hasattr` 本身就是一次 `except AttributeError`；`try: obj.attr` 对任意实现都成立。
3. **性能方向**。异常便宜在"不发生"、贵在"发生"，本机 20 万次取最小值实测（ns/op，越小越好）：

   ```text
   # Python 3.12.5 实测
   EAFP hit 15.7   LBYL hit 29.1   dict.get 16.3   try/except 不发生 4.2
   EAFP miss 95.5  LBYL miss 14.2  raise + catch 152
   ```

所以"EAFP 更快"**只在命中率高时成立**：热循环里每次都缺键就该用 `dict.get` 或干脆 LBYL。决定选型的仍是第 1 条。

## Designing domain exceptions

- **给一个领域基类**（`class StoreError(Exception)`）：调用方可只捕基类，也可捕窄类型；不要把 `Exception` 本身当领域类型抛，库尤其不要把"参数不对"一律扔成 `ValueError`——没有名字的失败类型无法被精确捕获。
- **上下文放属性，不要拼进 message**：拼进去的信息调用方只能靠正则读回来。但 `args` 要按可重放的方式设计——默认 `Exception.__init__` 原样存参数，实测 `str(ValueError("a", "b"))` == `"('a', 'b')"`，多参数会一起出现在消息里，所以自定义 `__init__` 要 `super().__init__(message)` 只留一句人话，其余进属性。
- **pickle 决定它能否跨进程**：`BaseException.__reduce__` 是 `(类, args, __dict__)`（实测），属性字典（含 `__notes__`）能过去，而 `__traceback__` / `__cause__` / `__context__` **全部丢失**（实测 `cause survived? None`）；函数内定义的异常类不可 pickle，`__init__` 只有关键字参数的异常在反序列化时抛 `TypeError`。跨进程的正确姿势见 [Concurrency](/docs/CS/Python/Concurrency.md) 的 `ExecutionFailed`。
- **不要用异常做常规控制流**（协议内定好的 `StopIteration` 除外）：本机实测"抛并被捕获"152 ns 对"走完 `try` 却不抛"4.2 ns，差 36 倍；更主要的是它会把 `finally`、上下文管理器与 `except*` 的语义搅复杂。"必然抛、不返回"在类型上写 `Never`，属类型系统话题，见 [Typing](/docs/CS/Python/Typing.md)。

## Global hooks and invisible errors

| 场景 | 默认行为 | 干预点 |
| :--- | :--- | :--- |
| 主线程未捕获 | 打 traceback，退出码 1（实测） | `sys.excepthook`（实测换掉后 `rc` 仍为 1） |
| 子线程未捕获 | 打 traceback 到 stderr，**退出码不变**（实测 `rc=0`） | `threading.excepthook(args)`，可拿 `args.thread` |
| 线程池 / 进程池 | 异常存进 future，`result()` 时才重抛 | 见 [Concurrency](/docs/CS/Python/Concurrency.md) |
| 未 await 的 task | 悄悄存着，回收或关循环时打 "Task exception was never retrieved"（实测） | 必须 await 或取 `exception()`，见 [Asyncio](/docs/CS/Python/Asyncio.md) |

线程里的异常之所以"看不见"，是因为它既不改变退出码也不回到 `join()`：生产上要么设 `threading.excepthook` 打点上报，要么别裸用线程。`atexit` 的处理器在未捕获异常终止时**照常运行**（实测 `rc=1` 且 handler 有输出），但拦不住 `os._exit()` 与段错误。

`warnings` 是异常之外的另一条错误信号：默认按"模块 + 类别"决定是否显示（实测 `warnings.filters` 前两条是 `('default', None, DeprecationWarning, '__main__', 0)` 与 `('ignore', None, DeprecationWarning, None, 0)`，即 `__main__` 里的 `DeprecationWarning` 可见、依赖库里的被忽略）。`-W error::DeprecationWarning` 能把警告提成异常（实测），测试里用 `warnings.catch_warnings(record=True)` + `simplefilter("always")` 捕获。3.14 新增 `-X context_aware_warnings`（让 `catch_warnings` 用 contextvar 管过滤器）与 `-X thread_inherit_context`（让 `threading.Thread` 继承调用方的 `Context()`），两者在 free-threaded 构建默认 true、GIL 构建默认 false，解决的是"一个线程改过滤器影响另一个线程"。

## Crash-level diagnostics

`faulthandler` 是在解释器被 C 层带崩之前拿到 Python 栈的主要手段：开 `-X faulthandler` 或设 `PYTHONFAULTHANDLER=1`（实测 `is_enabled()` 为 True）。它由 C 层实现，所以 `sys.settrace` 到不了的纯 C 栈帧、以及段错误之后的现场它照样能报（实测）：

```text
# Python 3.12.5 实测
dump_traceback()              -> Current thread 0x0000...: File "<string>", line 9 in <module>
dump_traceback_later(0.2, exit=True)
                              -> Timeout (0:00:00.200000)!  Thread 0x0000...: File "<string>", line 4 in <module>
PYTHONFAULTHANDLER=1 + segv   -> Fatal Python error: Segmentation fault
                                 Current thread 0x0000...: File "<string>", line 4 in <module>
```

`dump_traceback_later()` 是死锁 / 挂死的定位器（重复注册要配 `cancel_dump_traceback_later()`），`enable(file=...)` 可把栈落到日志文件。C 扩展内部的崩溃要转 gdb / core dump（见 [Debug](/docs/CS/SE/Debug.md)）；3.14 的 PEP 768 另外给了外部调试器读取 Python 栈的安全接口。

## Four philosophies compared

| 维度 | Python | Go | Java | Rust |
| :--- | :--- | :--- | :--- | :--- |
| 可发现性 | 签名不体现异常，靠文档 / 注解 | `error` 在返回值里，编译器逼你分支 | checked exception 在 `throws` 里，编译期强制 | `Result<T, E>` 在类型里，`?` 显式传播 |
| 控制流成本 | 不抛时约零成本，抛一次约 150 ns 并展开栈 | 每步一次分支，成本可忽略但代码冗长 | 构造即抓栈，`fillInStackTrace` 昂贵，不宜当控制流 | 零成本，值表示，无栈展开 |
| 跨边界传播 | `__cause__` / `__context__` 完整，跨进程只剩 args + 属性字典 | 只有 `%w` 建的链，`errors.Is` / `As` 判定，不带栈 | 序列化要求两端类可加载，常退化成 message | 需 `Box<dyn Error>` 擦除才能统一 |
| 并发安全 | 异常只回当前线程 / 当前 task；TaskGroup 用 `ExceptionGroup` 上交 | goroutine 里 `panic` 打死进程，每个 goroutine 自己 `recover` | 线程靠 `UncaughtExceptionHandler`，线程池包成 `ExecutionException` | 无异常跨线程概念，`panic` 只留给 bug |

分歧其实是同一件事：**把错误放进类型系统，还是放进控制流**。Go / Java / Rust 让调用方在编译期就看见失败，代价是样板；Python 让失败路径与正常路径共用语法，代价是"能捕获什么"必须靠层级约定来沟通——这就是本篇反复回到 `BaseException` 边界的原因。对照实现见 [Go 的 error 与包装链](/docs/CS/Go/Errors.md)、[panic / recover](/docs/CS/Go/Panic.md)、[C 的 errno 与 setjmp](/docs/CS/C/Stdlib.md)、[Java Throwable 层级](/docs/CS/Java/JDK/Basic/Throwable.md)。

## Links

- [Python](/docs/CS/Python/Python.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [Debug](/docs/CS/SE/Debug.md)
- [memory](/docs/CS/memory/memory.md)

## References

- [The try statement — Python Language Reference](https://docs.python.org/3/reference/compound_stmts.html)
- [Built-in Exceptions — Python Library](https://docs.python.org/3/library/exceptions.html)
- [traceback — Print or retrieve a stack traceback](https://docs.python.org/3/library/traceback.html)
- [faulthandler — Debugging Faults and Segmentation Faults](https://docs.python.org/3/library/faulthandler.html)
- [warnings — Issue warning messages](https://docs.python.org/3/library/warnings.html)
- [What’s New in Python 3.11](https://docs.python.org/3/whatsnew/3.11.html)
- [What’s New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [PEP 479 – StopIteration interaction with the generator throw API](https://peps.python.org/pep-0479/)
- [PEP 654 – Exception Groups and except*](https://peps.python.org/pep-0654/)
- [PEP 657 – Include Fine Grained Error Locations in Tracebacks](https://peps.python.org/pep-0657/)
- [PEP 678 – Enriching Exceptions with Notes](https://peps.python.org/pep-0678/)
- [PEP 758 – Allow except and except* expressions without parentheses](https://peps.python.org/pep-0758/)
- [PEP 765 – Disallow return/break/continue that exit a finally block](https://peps.python.org/pep-0765/)
