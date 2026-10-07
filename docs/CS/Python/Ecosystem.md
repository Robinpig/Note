## Introduction

这篇不教任何一个库怎么用，只回答两个问题：**这个生态位上有哪些选择，以及按什么维度选**。Python 的第三方生态比多数语言都厚，同一件事常有五六种可行方案，差别不在功能表而在**运行模型**——同一个 `async def` 放到不同 server 上，性能特征可以差一个数量级；同一份数据换个内存布局，能不能上多核就完全不同。所以选型的入口是"我的负载长什么样"，不是"哪个项目更流行"。

分工：本目录 [README](/docs/CS/Python/README.md) 管"这个目录里有哪些笔记"，[Python](/docs/CS/Python/Python.md) 管语言总览，框架的具体机制归 [FastAPI](/docs/CS/Framework/FastAPI.md)，消息投递语义归 [MQ](/docs/CS/MQ/MQ.md)。下面每一块只给**判断**，并链到承载机制的那篇。

## Selection Starts From The Concurrency Model

Python 生态在近十年分裂成"同步栈"和"异步栈"两套工具，根因是两个运行时事实：GIL 让多线程拿不到 CPU 并行，而解释器逐字节码执行的开销让"每个请求一个线程"的模型在 I/O 等待上极度浪费。于是同一类问题出现两种解法——用**进程**换并行（WSGI + prefork），或用**协程**换等待时间的复用（ASGI + 事件循环）。

| 负载特征 | 该走的路 | 理由 |
|---|---|---|
| 每个请求主要是 CPU 计算 | 进程池 / prefork | 协程不减少 GIL 排队，也不让字节码变快 |
| 每个请求主要是等下游 | 事件循环 | 等待时间被复用，单进程能撑住远高于核数的并发 |
| 依赖的 SDK 只有同步阻塞版 | 同步栈，或 async 里显式丢线程池 | 阻塞调用会卡住整个循环，异步收益直接归零 |
| 大量长连接（WebSocket / SSE） | ASGI | WSGI 的请求-响应契约里没有双向流 |

原理在 [GIL](/docs/CS/Python/GIL.md)、[Asyncio](/docs/CS/Python/Asyncio.md)、[Concurrency](/docs/CS/Python/Concurrency.md) 三篇，这里只用来当选择依据。

## Web Services

### WSGI vs ASGI

| 维度 | WSGI | ASGI |
|---|---|---|
| 契约 | 一次请求 = 一次同步调用 `application(environ, start_response)` | 一次请求/连接 = 一个协程，消息在 `scope` / `receive` / `send` 间流动 |
| 并发来源 | server 的 worker 模型（进程或线程） | 单进程内的事件循环 |
| 协议归属 | PEP 3333，标准库有 `wsgiref` 参考实现 | 独立规范，由 ASGI server 生态维护，不在标准库 |
| 阻塞 I/O 的后果 | 只占住当前 worker，符合线程池直觉 | 卡住整个循环，全服务一起退化 |
| 长连接 | 无原生位置，要靠绕过协议 | WebSocket / SSE / 双向流是一等公民 |

ASGI 之所以**必须**带一个事件循环：协议把"一次交互"拆成了多次消息收发，谁在 `await` 期间让出、谁被唤醒，需要一个调度者；这正是 [Asyncio](/docs/CS/Python/Asyncio.md) 里 `epoll` 之上的那层。常见加速项 `uvloop` 就是替换循环实现，`anyio` / `asyncio` 的抽象差异则决定了库能不能同时服务两种栈。

判断：一个服务该不该上 ASGI，只看它的依赖树里是不是**端到端**异步。只要链路上有一个同步阻塞 client，异步化带来的不是吞吐而是排查成本（"谁在循环里同步阻塞"）。反过来，纯同步的 CRUD 接口配 prefork 更好推理，也不受"一个慢查询拖死整进程"的影响。

### Framework Positioning

| 框架 | 定位 | 默认并发模型 | 选型时的真实约束 |
|---|---|---|---|
| Django | 全栈：ORM、admin、auth、migration 一体化 | 同步（ASGI 下可 async view，长连接另需 channels 类扩展） | 组件间约定强，替换任一层成本都高 |
| Flask | 请求分发 + 模板渲染，其余靠扩展拼装 | WSGI | 能力在扩展手里，维护状态参差，风险随扩展数量上升 |
| FastAPI | 类型注解驱动校验与文档，路由层很薄 | ASGI | 契约完全绑在类型系统与 pydantic 上 |

怎么选：按"你还得自己搭多少东西"排，而不是按压测数字排。业务核心是权限、后台管理与关系数据 → Django；边界清楚的内部小服务 → Flask 更省认知；接口契约（请求/响应模型、OpenAPI）是团队协作的主要摩擦点 → FastAPI。三者的机制与代码组织不在这里展开，见 [FastAPI](/docs/CS/Framework/FastAPI.md)。

### Serving and Reverse Proxy

| 组件 | 角色 | 模型 |
|---|---|---|
| gunicorn | 进程管理器 + HTTP server | prefork：master 持有监听 socket，fork 出 N 个 worker 抢占 accept |
| uvicorn | ASGI server | 单进程事件循环，多进程要靠 `--workers` 或外部进程管理器 |
| hypercorn / granian | ASGI server 的另两种实现 | 前者偏协议完整度（HTTP/2、WebSocket），后者把 runtime 换到 Rust |
| nginx | 反向代理、TLS 终结、静态资源 | 与业务进程解耦，只负责连接与缓冲 |

有效并发 = `worker 数 × 每 worker 内的并发单位数`。prefork 下后者恒为 1，所以 worker 数按内存上限和核数定；这也是 GIL 存在时唯一能真并行用满多核的路径（见 [GIL](/docs/CS/Python/GIL.md)）。ASGI 下并发单位换成协程，单 worker 撑住成百上千在途请求，于是"几个 worker"重新变成一个内存与 CPU 的问题而不是连接数的问题。

`--preload` 是 fork 语义最容易咬人的地方。它让 master 先 import 应用再 fork，收益是启动更快、且只读的常驻数据（路由表、词表、模型权重）靠写时复制只在物理内存里存一份；代价是子进程继承 master 打开的**文件描述符**——如果 import 期就建立了数据库连接池、HTTP client 长连接或后台线程，fork 后多个进程会共享同一个 socket，两个进程往同一条 TCP 连接上收发就会互相串包，而线程在 fork 后根本不会存在于子进程里。规则很简单：`--preload` 只 import，不在 import 期做任何连接与起线程；连接池留到 worker 起来之后再建（gunicorn 的 post-fork hook 或惰性初始化）。这类坑与 [Concurrency](/docs/CS/Python/Concurrency.md) 里的 fork 安全、以及进程/线程共享 fd 的模型是同一件事。

nginx 侧最常见的两个坑：`proxy_buffering` 默认开启，会把上游响应先收进缓冲区再下发——对普通 JSON 无感，对 SSE / chunked 流式输出就是"客户端永远等不到增量"，需要按 location 关掉，并同步调大 `proxy_read_timeout`（默认几十秒会切断长连接）；WebSocket 升级依赖 `Upgrade` / `Connection` 这类逐跳头，nginx 不会自动透传，必须显式设置。上游 server 还应感知代理层，用 `Forwarded` / `X-Forwarded-*` 还原真实客户端地址与协议，否则限流与重定向都会拿到内网地址。

## Task Queues and Scheduling

| 项目 | 依赖 | 定位 |
|---|---|---|
| Celery | broker + 结果 backend（常见 Redis / RabbitMQ） | 功能全集：路由、优先级、重试、限流、工作流编排 |
| RQ | Redis | 队列语义的最小实现，任务 = 函数 + 队列，几乎无学习成本 |
| Dramatiq | RabbitMQ / Redis | 把投递语义与 ack 时机摆在明面上的轻量替代 |
| arq | Redis | asyncio 原生，跑在事件循环里，适配已是 async 的技术栈 |

Celery 的两个易混概念：**broker 负责投递**（谁消费、消息何时可以消失，需要 ACK、持久化、公平调度），**backend 只负责结果**（按 task id 存取返回值与状态，本质是 KV）。二者介质可以完全不同，把 Redis 同时当两者是默认配置而不是最优配置——结果存储用 Redis 很合适，投递通道则需要 broker 语义更强的实现。消息可靠性、幂等与重试的通用论述在 [MQ](/docs/CS/MQ/MQ.md)，此处不重复。

worker 的并发池决定了同一个 worker 进程里任务怎么并行：`prefork`（默认，子进程隔离，能安全跑会释放 GIL 的 C 扩展，代价是内存与启动开销）、`threads`（受 GIL 限制，只在被调用的同步库不是协程安全时有意义）、`gevent` / `eventlet`（协程池，靠猴子补丁把同步调用改成非阻塞，高并发 I/O 最省内存但最难排查，与原生阻塞调用不兼容）、`solo`（在主进程内联执行，只用于调试）。选择顺序应是：先确认任务里最耗时的一段是 CPU 还是 I/O，再决定"加进程"还是"加协程数"；把 CPU 任务和大量协程混在一个进程里，GIL 排队会同时毁掉两者的尾延迟。

幂等不是可选优化：broker 层默认只保证 at-least-once，worker 在 ack 前崩溃、连接重试、开启延迟 ack 都会造成**正常路径上的重复投递**。所以任务体要么本身幂等，要么用外部唯一键去重；重试次数与退避必须显式设上限，否则一次下游抖动会被重试放大成自我 DDoS。

调度的关键是别把不同层混为一谈：

| 层 | 机制 | 边界 |
|---|---|---|
| 操作系统 | cron / systemd timer | 与主机绑定，多副本之间不协调，不防任务重叠执行 |
| 应用进程内 | APScheduler（trigger / job store / scheduler 三段） | 调度逻辑属于业务，但多副本会重复触发，需要共享 job store 与选主 |
| 集群 | Celery beat + worker 池 | 派发与执行天然分离，但 beat 本身是单点，要做故障接管 |

分层、错过补偿与时钟漂移的系统性讨论见 [Scheduled_Task](/docs/CS/SE/Scheduled_Task.md)。

## Data and Analysis

| 项目 | 数据形状 | 执行与内存模型 |
|---|---|---|
| NumPy | 同构数值 n 维数组 | 单块连续 buffer，切片是 view 不是拷贝，开销出现在与 Python 对象互转的边界上（见 [NumPy](/docs/CS/Python/NumPy.md)） |
| pandas | 带标签的表 + 混合类型 | 每列是对象数组，缺失值与字符串带来显著拷贝与装箱开销 |
| Polars | DataFrame | 数据留在 Arrow 列式 buffer，表达式下推后多核并行 |
| DuckDB | 进程内 OLAP 引擎 | SQL + 向量化执行，能直读 Parquet，不搬数据 |
| PyArrow | 跨语言列式内存格式 | 计算层是附属，主要价值是组件之间的零拷贝交换 |

一条主线：Python 对象模型让"每一行数据都是一个对象引用"（详见 [Memory](/docs/CS/Python/Memory.md)），所以 DataFrame 类工具的性能差异往往不来自算法，而来自**有没有做那次 Python 对象化**。Arrow 系（Polars / DuckDB / PyArrow）的共同策略是把数据留在原生 buffer 里，只在结果出口投影成 Python 对象。怎么选：数据能整块放进内存、且变换路径不确定 → pandas；量大且操作可先声明后执行 → Polars；要做 join / agg 且数据已经在文件里 → DuckDB；需要和 JVM 或大数据栈共享列式数据 → Arrow / Parquet。

### ORM Drivers and Migrations

| 组件 | 定位 |
|---|---|
| SQLAlchemy Core | 表达式层的 SQL 构建器，贴近 SQL 本身 |
| SQLAlchemy ORM | 对象映射与单元工作（identity map、flush） |
| SQLAlchemy async engine | 同一套 API 挂到 asyncio 上，必须配真异步驱动 |
| psycopg | PostgreSQL 驱动，同一 API 同时提供 sync 与 async |
| asyncpg | 为 asyncio 重写协议的 PG 驱动，不兼容 DB-API，性能取向 |
| aiosqlite | SQLite 的 async 包装，底层是线程池代理，不是真异步 I/O |
| Alembic | SQLAlchemy 的 schema 版本化迁移工具 |

判断：先选**驱动**再选 ORM。异步栈里 `aiosqlite` 这类"线程池伪装成 async"的驱动只适合低并发本地开发，生产要换成能挂到事件循环上的真异步驱动，否则连接池会退化成一个小线程池。连接池在 async + 多进程下有两个硬约束：一个连接不能跨事件循环使用，因此池必须按 worker/循环各建一份；不要在 import 期或 fork 之前预建连接（与上面 `--preload` 那段是同一个 fork 问题）。关系模型、事务与连接池的通用原理见 [DB](/docs/CS/DB/DB.md)。

## AI as the Glue Layer

| 项目 | 定位 |
|---|---|
| PyTorch | 动态图 + autograd：反向图随前向构建，控制流就是 Python 控制流；`torch.compile` 把重复算子图交给编译后端做核融合 |
| JAX | 函数变换（jit / grad / vmap）作用在纯函数上，配合 XLA 做整图编译，因此要求随机数与副作用显式穿过参数 |
| transformers | 模型结构与权重的统一 API 及分发通道 |
| vLLM | 推理服务引擎，把显存分页与连续批处理放在引擎侧，Python 只做调度与服务外壳 |

Python 在 AI 里是**胶水层**而不是实现层，靠的是三段结构：解释器负责编排与契约（张量语义、并行策略、训练循环），C / C++ / CUDA / Rust 负责内核（矩阵乘、显存拷贝），中间靠类型注解与描述符式 API 把边界粘住。字节码逐指令执行的开销见 [Bytecode](/docs/CS/Python/Bytecode.md)——正因为这个开销无法靠"少写点 Python"消除，有效做法必须是**把更多工作塞进单个大内核**，让一次跨语言调用摊薄解释成本。API 设计为什么高度依赖注解，见 [Typing](/docs/CS/Python/Typing.md)。

GIL 在这里不致命的原因值得单独说清：进入 native 内核计算时通常会释放 GIL，真正的热点循环不在字节码里；数据加载用**多进程**而不是多线程；推理侧靠异步服务与批量调度提高吞吐，而不是靠线程数。也就是说，生态是通过"绕开解释器"而不是"修好解释器"来规避 GIL 的，一旦负载回到纯 Python 的特征工程，限制立刻重新出现。算法与系统层面见 [AI](/docs/CS/AI/AI.md)。

## Quality Tooling

| 工具 | 职责 |
|---|---|
| ruff | lint + format，一个 Rust 实现收敛了此前 flake8 插件群 + isort + black 的角色 |
| mypy | 类型检查的参考实现，语义保守、报错可读 |
| pyright | 检查速度快、与编辑器深度集成，是 typing 规范的主要落地基准之一 |
| pytest | fixture + 参数化 + 插件生态，事实上的标准测试运行器 |
| coverage.py | 行/分支覆盖，配合 pytest 使用 |
| pre-commit | 提交前钩子的统一入口，消解"每人本地工具版本不同" |
| tox / nox | 多解释器版本 × 依赖组合的矩阵测试，nox 的配置用 Python 写 |

判断：lint 与格式化优先合并到一个工具，规则集越少越容易在多人仓库里维持一致；类型检查要认一个权威（mypy 与 pyright 对边界规则的严格度不同，双跑只会产生噪声），并且清楚**没有注解的代码在类型检查器眼里等于不存在**，收益随注解覆盖率非线性上升。矩阵测试属于库作者的需求（要证明多个 Python 版本都能装能跑），只服务单一部署环境的应用把它换成 CI 里固定的一个版本更划算。pytest 的 fixture 与参数化机制本库暂无独立笔记，不在此展开。

## Packaging Distribution and Runtime Environments

| 层 | 项目 | 何时用 |
|---|---|---|
| 分发格式 | PyPI + wheel | wheel 带平台与 ABI 标签，决定用户是否需要现场编译 |
| 环境与安装 | pip + venv | 标准路径；pip 只管单包解析，可复现靠锁文件或 uv |
| 现代工具链 | uv | 解析、缓存、锁文件与项目管理，把"可复现"落到应用侧（见 [uv](/docs/CS/Python/uv.md)） |
| CLI 工具安装 | pipx | 每个工具一个隔离环境，不污染项目依赖 |
| 跨语言依赖 | conda | 需要非 Python 二进制（CUDA、地理/数值库）时（见 [conda](/docs/CS/Python/conda.md)） |
| 部署单元 | 容器镜像 | 多阶段构建把编译期与运行期分开 |
| 冻结产物 | PyInstaller / Nuitka / pex | 无网络或无 Python 的目标机上分发单体可执行 |
| 浏览器内 | Pyodide | WASM 里跑解释器，适合交互演示而非服务后端 |

先分清三种目标，绝大多数"本地能跑线上不行"都来自把它们混着管：**库**要向后兼容与多平台 wheel 矩阵（发布规范见 [Packaging](/docs/CS/Python/Packaging.md)），**应用**要锁文件与可复现环境，**CLI 工具**要隔离与免依赖启动。

C 扩展是成本的放大器：要么 CI 为每个（平台 × ABI）产出二进制 wheel（manylinux 之类的标签就是为此存在），要么把编译器和头文件留给用户现场。容器里对应的是多阶段构建——编译阶段带 toolchain，运行阶段只 `COPY` 产物；选 `slim` 还是 distroless 取决于你是否需要在容器里装依赖与用 shell 排障，distroless 没有 shell，调试要换临时调试容器。冻结部署换来单文件，代价是体积、启动解压、隐藏导入清单（数值库常需手写 hook）、无法用包管理器补底层依赖，以及 C 扩展与特殊构建（如 free-threaded）的兼容性需自行验证。

## Observability and Debugging

| 工具 | 定位 |
|---|---|
| logging | 标准库三段式 logger / handler / formatter；未配置时只有较高级别被兜底输出 |
| structlog | 事件模型：结构化键值 + 处理器链，把上下文注入与序列化分开 |
| OpenTelemetry Python SDK | trace / metric / log 的统一出口，附各框架的 auto-instrumentation |
| pdb | 同步断点调试；协程与并发任务栈上体验很差 |
| debugpy | 走 DAP 协议，支持 IDE 附加到远端进程 |
| py-spy | 采样式剖析，可附加到运行中的生产进程，不需要改代码 |

结构化日志的主流做法不是换掉 logger，而是**在 formatter 里输出 JSON，并用 contextvars 携带请求级字段**（trace id、user id）——`contextvars` 是协程安全的每任务上下文，这正是 `threading.local` 在异步栈上会串味的地方。OTel 的 auto-instrumentation 依赖对第三方库做猴子补丁，因此与框架版本强耦合：升级 Web 框架后要重新验证 span 是否完整，别把"没有报错"当成"还在采集"。剖析的判读与工具选择见 [Performance](/docs/CS/Python/Performance.md)；采样剖析器只能看到解释器停在安全点时的栈，若火焰图里大量样本聚在 native 帧或"等 GIL"，那是同步调用，需要配合系统级工具。采集链路与指标模型见 [APM](/docs/CS/SE/APM.md)。

## Ecosystem Map

| 层次 | 代表项目 | 何时用 | 对应本库笔记 |
|---|---|---|---|
| Web 协议 | WSGI / ASGI | 依赖树端到端异步才选 ASGI | [Asyncio](/docs/CS/Python/Asyncio.md) |
| Web 框架 | Django / Flask / FastAPI | 按"还要自己搭多少"选 | [FastAPI](/docs/CS/Framework/FastAPI.md) |
| HTTP server | gunicorn / uvicorn / hypercorn | prefork 换 CPU，事件循环换 I/O 复用 | [Concurrency](/docs/CS/Python/Concurrency.md) |
| 任务队列 | Celery / RQ / arq / Dramatiq | 有 broker 语义需求才上 Celery | [MQ](/docs/CS/MQ/MQ.md) |
| 定时调度 | APScheduler / cron / Celery beat | 先决定它属于哪一层 | [Scheduled_Task](/docs/CS/SE/Scheduled_Task.md) |
| 数值与 DataFrame | NumPy / pandas / Polars / DuckDB / PyArrow | 数据能否留在原生列式 buffer | [NumPy](/docs/CS/Python/NumPy.md) |
| 数据访问 | SQLAlchemy / psycopg / asyncpg | 先选驱动再选 ORM | [DB](/docs/CS/DB/DB.md) |
| AI 栈 | PyTorch / JAX / transformers / vLLM | Python 编排 + native 内核 | [AI](/docs/CS/AI/AI.md) |
| 质量工具 | ruff / mypy / pyright / pytest / tox | 规则集越少越一致 | [Typing](/docs/CS/Python/Typing.md) |
| 打包分发 | wheel / pip / uv / conda / pipx | 分清库、应用、CLI 三种目标 | [Packaging](/docs/CS/Python/Packaging.md) |
| 运行环境 | venv / 容器 / PyInstaller / Pyodide | C 扩展数量决定复杂度 | [conda](/docs/CS/Python/conda.md) |
| 可观测性 | logging / structlog / OTel / py-spy | 上下文用 contextvars 传递 | [Performance](/docs/CS/Python/Performance.md) |

## Links

- [Import](/docs/CS/Python/Import.md)
- [SE/Concurrency](/docs/CS/SE/Concurrency.md)
- [process](/docs/CS/OS/process.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)

## References

- [PEP 3333 – Python Web Server Gateway Interface v1.0.1](https://peps.python.org/pep-3333/)
- [ASGI Specification](https://asgi.readthedocs.io/en/latest/)
- [Django documentation](https://docs.djangoproject.com/en/stable/)
- [Flask documentation](https://flask.palletsprojects.com/en/stable/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Gunicorn](https://gunicorn.org/)
- [Uvicorn](https://github.com/encode/uvicorn)
- [Hypercorn](https://github.com/pgjones/hypercorn)
- [nginx ngx_http_proxy_module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [Celery User Guide](https://docs.celeryq.dev/en/stable/userguide/workers.html)
- [RQ](https://github.com/rq/rq)
- [Dramatiq](https://dramatiq.io/)
- [arq](https://github.com/samuelcolvin/arq)
- [APScheduler documentation](https://apscheduler.readthedocs.io/en/stable/)
- [NumPy documentation](https://numpy.org/doc/stable/)
- [pandas documentation](https://pandas.pydata.org/docs/)
- [Polars](https://github.com/pola-rs/polars)
- [DuckDB Documentation](https://duckdb.org/docs/stable/)
- [Apache Arrow](https://arrow.apache.org/docs/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/en/latest/)
- [psycopg 3 documentation](https://psycopg.org/)
- [aiosqlite](https://github.com/omnilib/aiosqlite)
- [PyTorch documentation](https://pytorch.org/docs/stable/)
- [JAX documentation](https://jax.readthedocs.io/en/latest/)
- [transformers](https://github.com/huggingface/transformers)
- [vLLM documentation](https://docs.vllm.ai/en/stable/)
- [Pydantic](https://docs.pydantic.dev/latest/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [mypy documentation](https://mypy.readthedocs.io/en/stable/)
- [Pyright](https://github.com/microsoft/pyright)
- [pytest documentation](https://pytest.org/en/latest/)
- [Coverage.py](https://coverage.readthedocs.io/en/latest/)
- [pre-commit](https://www.pre-commit.com/)
- [tox documentation](https://tox.wiki/en/stable/)
- [Nox](https://github.com/wntrblm/nox)
- [Python Packaging User Guide](https://packaging.python.org/en/latest/)
- [uv documentation](https://docs.astral.sh/uv/)
- [wheel — the built-distribution format](https://wheel.readthedocs.io/en/stable/)
- [pipx](https://github.com/pypa/pipx)
- [conda documentation](https://docs.conda.io/en/latest/)
- [distroless images](https://github.com/GoogleContainerTools/distroless)
- [PyInstaller Manual](https://pyinstaller.org/en/stable/)
- [Nuitka](https://nuitka.net/)
- [pex](https://github.com/pex-tool/pex)
- [Pyodide documentation](https://pyodide.org/en/stable/)
- [logging — Logging facility for Python](https://docs.python.org/3/library/logging.html)
- [structlog](https://github.com/hynek/structlog)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [pdb — The Python Debugger](https://docs.python.org/3/library/pdb.html)
- [debugpy](https://github.com/microsoft/debugpy)
- [py-spy](https://github.com/benfred/py-spy)
- [uvloop](https://github.com/MagicStack/uvloop)
- [anyio](https://anyio.readthedocs.io/en/stable/)
- [venv — Creation of virtual Python environments](https://docs.python.org/3/library/venv.html)
