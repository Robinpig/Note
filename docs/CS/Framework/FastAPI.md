## Introduction

FastAPI 是一个用于构建 API 的现代、快速（高性能）的 Web 框架，专为 Python 设计。它充分利用了 Python 3.6+ 的类型提示（Type Hints） 特性，是目前 Python 生态中最受欢迎的 Web 框架之一。

核心特性：

- **高性能**：基于 ASGI，性能接近 Node.js 与 Go（[TechEmpower](https://www.techempower.com/benchmarks/) 中 Python 框架第一梯队）。
- **类型即文档**：函数签名的类型注解同时承担参数解析、数据校验与序列化，自动生成交互式文档（Swagger UI / ReDoc）。
- **开发效率高**：编辑器补全友好，样板代码少。

## Version Baseline

| 项 | 值 |
| :--- | :--- |
| 版本 | 0.146.0（2026-10，MIT） |
| Python | >= 3.10（0.129.0 起弃 3.9；支持 3.10 – 3.14） |
| 核心依赖 | Starlette（Web / ASGI 基石）、Pydantic v2（校验与序列化） |
| 服务器 | Uvicorn / Hypercorn（ASGI server） |

版本基线：**0.146.0（2026-10）**。自 0.100+ 起 Pydantic v2 为默认校验/序列化引擎（底层 `pydantic-core` 用 Rust 实现），Starlette 提供 ASGI 应用、中间件、WebSocket 与 TestClient。FastAPI 迭代极快（月均数十个补丁版），生产环境务必 pin 版本，不要无锁安装 latest。与 [Django](/docs/CS/Framework/Django.md) 的选型对照见 [Ecosystem](/docs/CS/Python/Ecosystem.md)。

## Installation

官方推荐装 `standard` extra——它把 FastAPI CLI 与 Uvicorn 一并带上：

```shell
uv add "fastapi[standard]"
```

只装最小依赖（自己管理 ASGI server）时：

```shell
uv add fastapi uvicorn
```

生成项目骨架用独立包 `fastapi-new`（注意：它**不是** `fastapi new` 子命令，而是单独的可执行工具）：

```shell
uvx fastapi-new awesomeapp   # 生成到新目录 awesomeapp
cd awesomeapp
uv run fastapi dev
```

程序 `main.py`

```py
from fastapi import FastAPI

# 1. 创建应用实例
app = FastAPI()

# 2. 定义路由和请求方法
@app.get("/")
async def read_root():
    return {"message": "Hello World"}

# 3. 定义带路径参数和查询参数的路由
@app.get("/items/{item_id}")
async def read_item(item_id: int, q: str = None):
    # item_id 会被自动转换为 int 类型，如果传入的不是数字，会自动报错并返回 422 状态码
    return {"item_id": item_id, "q": q}
```

启动

```shell
uvicorn main:app --reload
```

`main:app` 表示 `main.py` 中的 `app` 对象；`--reload` 仅用于开发，代码变更后自动重启。

## FastAPI CLI

`fastapi[standard]` 会装上 `fastapi-cli`（0.0.32），它封装 Uvicorn，提供两个子命令：

| 命令 | 监听地址 | auto-reload | `FASTAPI_ENV` |
| :--- | :--- | :--- | :--- |
| `fastapi dev` | `127.0.0.1` | 开启（默认） | 设为 `development`（已存在则保留） |
| `fastapi run` | `0.0.0.0` | 关闭（默认） | **不修改** |

CLI 会自动探测 `main.py` 中的 `app` 对象，也可用 `--entrypoint` 显式指定；推荐写进 `pyproject.toml`，让 IDE 扩展等外部工具也能发现入口：

```toml
[tool.fastapi]
entrypoint = "backend.main:app"
```

```shell
fastapi dev main.py
fastapi dev --entrypoint backend.main:app
```

`fastapi run` 默认监听 `0.0.0.0`（容器里直接可用），但它**不**把 `FASTAPI_ENV` 设为 `production`——需要区分环境的应用要自己显式设置这个环境变量。

## Request

### Pydantic Request Body

用 Pydantic `BaseModel` 声明请求体，FastAPI 会自动完成 JSON 解析、类型校验（失败返回 422）和 OpenAPI schema 生成。

```py
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool | None = None

@app.post("/items")
async def create_item(item: Item):
    # item.name / item.price 已完成类型转换与校验，可直接使用
    return {"item_name": item.name, "price_with_tax": item.price * 1.13}
```

### Parameter Sources

| 来源 | 声明方式 | 示例 |
|---|---|---|
| 路径参数 | 路径占位符 + 同名函数参数 | `/items/{item_id}` → `item_id: int` |
| 查询参数 | 普通函数参数（有默认值即可选） | `q: str \| None = None` |
| 请求体 | Pydantic Model 参数 | `item: Item` |
| Header | `Header()` | `user_agent: str = Header()` |
| Cookie | `Cookie()` | `session_id: str \| None = Cookie()` |
| 表单/文件 | `Form()` / `UploadFile` | `file: UploadFile` |

### Response Model

通过 `response_model` 声明输出结构，可做字段过滤（如隐藏内部字段）和文档生成：

```py
class UserOut(BaseModel):
    username: str
    email: str

@app.get("/users/me", response_model=UserOut)
async def read_me():
    ...
```

## Routing and APIRouter

小项目把所有路由直接写在 `app` 上即可；模块变多后用 `APIRouter` 拆分，再 `include_router` 装配，避免单文件膨胀：

```py
from fastapi import APIRouter

router = APIRouter(prefix="/items", tags=["items"])

@router.get("/{item_id}")
async def read_item(item_id: int):
    ...

app.include_router(router)
```

- `prefix`：给该 router 下所有路径加统一前缀。
- `tags`：在 OpenAPI / `/docs` 里把同组接口归类，是文档可读性的关键。
- `status_code`：声明成功状态码（如创建返回 201），写在路径操作装饰器上。
- `responses`：补充非 2xx 的响应 schema（如 `responses={404: {"model": ErrorOut}}`），让文档覆盖错误情形。

大型项目通常按业务域分多个 `routers/xxx.py`，`main.py` 只负责创建 `app`、挂载中间件与 `include_router`。

## Dependency Injection

FastAPI 的依赖注入用 `Depends` 声明，特别适合鉴权、数据库会话、分页参数等横切逻辑；依赖还可以嵌套依赖、复用和覆盖（测试时 `app.dependency_overrides` 替换）。

```py
from fastapi import Depends, HTTPException

async def get_token_header(x_token: str = Header()):
    if x_token != "secret":
        raise HTTPException(status_code=400, detail="X-Token header invalid")

@app.get("/admin/", dependencies=[Depends(get_token_header)])
async def admin():
    return {"msg": "authorized"}
```

数据库会话是典型用例：请求开始时建立 session，请求结束自动关闭（yield 依赖）。

## Data Layer

FastAPI **不自带 ORM**——这是与 [Django](/docs/CS/Framework/Django.md) 最实质的分工差异：Django 内置 ORM + 迁移 + admin，FastAPI 只提供 HTTP 层，数据访问要自己选型。社区主流组合是 **SQLAlchemy 2.0 + Alembic**。

版本基线：SQLAlchemy 稳定线 **2.0.54**（2.1 仍为 rc，且 2.1 起最低需 Python 3.11）；Alembic **1.20.0**（自 1.20.0 起要求 SQLAlchemy >= 2.0，1.4 支持已移除）。

### Async Session

用 `async_sessionmaker` 建会话工厂，把会话生命周期绑到请求上：

```py
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine(
    "postgresql+asyncpg://user:pwd@localhost/app",
    pool_pre_ping=True,      # 取连接前探活，避免拿到被数据库端断开的连接
    pool_size=5,
    max_overflow=10,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

`get_session` 就是上面讲过的 yield 依赖——请求进入时开连接、响应发出后归还连接池。驱动选型上：PostgreSQL 用 `postgresql+asyncpg`（或 psycopg 3 的 `postgresql+psycopg`），MySQL 用 `mysql+aiomysql`。

连接池的容量、超时与连接失效检测需按数据库侧的连接上限与 [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md) 的行为来配，不要照抄默认值。

### Declarative Model and Query

```py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column()
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped["User"] = relationship(back_populates="items")
```

SQLAlchemy 2.0 的查询风格是「构造 select 语句再执行」，不再是 1.4 的 `session.query()`：

```py
from sqlalchemy import select

@app.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)):
    stmt = select(Item).where(Item.price > 0).limit(50)
    rows = (await session.execute(stmt)).scalars().all()
    return rows
```

注意 ORM 模型与 Pydantic 模型是**两套独立的类型**：ORM 模型面向数据库（`Mapped[...]` 注解），Pydantic 模型面向 API 契约（`BaseModel`）。把 ORM 对象直接返回会连带暴露内部字段，通常用 `response_model` + `from_attributes` 显式转换。

### Migrations with Alembic

Alembic 管 schema 版本，与 Django 的 `makemigrations` / `migrate` 职责对应，但工具链完全独立：

```shell
alembic init migrations                # 生成迁移环境
alembic revision --autogenerate -m "add items"   # 比对模型与库，自动生成迁移脚本
alembic upgrade head                   # 应用到数据库
```

`--autogenerate` 只做差异比对，**不能捕获全部变更**：重命名列（会被判成删+增）、数据回填、复杂约束都要手写迁移脚本。迁移脚本进版本库、可评审、可回滚，和 Django 迁移的定位一致。

## Security and Authentication

FastAPI 把鉴权拆成「提取凭证」与「校验逻辑」两层：`fastapi.security` 负责从请求里按标准方式取出 token / api key，真正的校验仍由 `Depends` 包裹的函数完成。

```py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer()

async def require_token(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> str:
    # 这里只演示提取；真实场景应校验签名 / 查库 / 查 Redis
    if creds.credentials == "invalid":
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials

@app.get("/secure")
async def secure(token: str = Depends(require_token)):
    return {"token": token}
```

可用的提取器：`HTTPBearer`、`APIKeyHeader` / `APIKeyQuery`（API key）、`OAuth2PasswordBearer`（配合 `tokenUrl` 自动生成 OAuth2 密码流文档）、`OAuth2AuthorizationCodeBearer`。JWT 的签发与验签需自己接 `PyJWT` / `python-jose`——FastAPI 只管「取出凭证并接到 OpenAPI 文档」，不内置鉴权后端。

这与 [Django](/docs/CS/Framework/Django.md) 相反：Django 自带 session + auth 中间件和 User 模型，开箱即用；FastAPI 更裸，靠 `Depends` 把任意鉴权逻辑组合进路由，灵活但要自己搭。

## Async

FastAPI 同时支持 `async def` 和普通 `def` 路由：

- **`async def`**：路由内要 await 异步库（如 asyncpg、httpx.AsyncClient）时使用，全程跑在事件循环上，吞吐高。
- **普通 `def`**：FastAPI 自动放到线程池执行，避免阻塞事件循环——但如果内部调用同步阻塞库（如 psycopg2、requests），用普通函数更稳妥。

混用的关键约束：不要在 `async def` 里调用阻塞型同步库，否则会卡住整个 worker 的事件循环。Python 协程原理见 [Concurrency](/docs/CS/SE/Concurrency.md)。

## WebSockets

FastAPI 原生支持 WebSocket（由 Starlette 提供），无需像 [Django](/docs/CS/Framework/Django.md) 那样另引第三方 Channels——这是两者在「实时/长连接」场景上的关键差异：

```py
from fastapi import FastAPI, WebSocket

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"echo: {data}")
```

要点：

- ASGI 天然双向，连接建立后由 `await` 驱动收发，不占线程。
- 适合推送、聊天、实时仪表盘等场景；多 worker 下连接状态要放外部存储（如 Redis 发布/订阅）而非进程内存。
- 鉴权可在 `accept()` 前读取 `websocket.headers` / `query_params` 自行校验。

## Architecture

FastAPI 本身很薄，建立在两个库之上：

| 层 | 组件 | 职责 |
|---|---|---|
| 应用层 | FastAPI | 路由、参数解析、依赖注入、OpenAPI 文档 |
| 数据层 | Pydantic v2 | 类型校验、序列化（底层用 Rust 实现的 pydantic-core） |
| Web 层 | Starlette | ASGI 应用、中间件、WebSocket、TestClient |
| 服务器 | Uvicorn / Hypercorn | ASGI server，基于 uvloop + httptools |

请求处理链路：

```text
HTTP Request
  → Uvicorn (ASGI server, 解析 HTTP)
  → Starlette (路由匹配 / 中间件链)
  → FastAPI (依赖注入 + Pydantic 校验参数)
  → 用户路由函数 (async def / def 线程池)
  → Pydantic 序列化响应
  → HTTP Response
```

与传统 WSGI（Flask + Gunicorn 同步模型）不同，ASGI 原生支持异步、WebSocket 和长连接，请求不再被一个请求一个线程的模型限制。

### Middleware and Lifespan

```py
import time
from fastapi import Request

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.perf_counter() - start)
    return response
```

跨请求的资源（连接池、模型加载）推荐用 `lifespan` 在启动时初始化、关闭时释放，而不是模块级全局变量。

### CORS

```py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Error Handling

路径操作里用 `HTTPException` 中断请求并返回标准 JSON `{"detail": ...}`：

```py
from fastapi import HTTPException

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    if item_id < 0:
        raise HTTPException(status_code=404, detail="Item not found")
```

- 请求体/参数校验失败由 Pydantic 自动返回 **422**（不是 400），body 是字段级错误。
- 自定义异常处理器可改写错误响应形态、统一错误 envelope：

```py
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "msg": exc.detail},
    )
```

注意 `response_model` 只约束正常返回，异常走处理器，不会套用 `response_model`。

## Testing

FastAPI 的 `TestClient` 来自 Starlette，同步调用即可驱动异步路由（内部自管事件循环），配合 pytest 做接口测试：

```py
from fastapi.testclient import TestClient
from main import app

def test_read_item():
    client = TestClient(app)
    r = client.get("/items/5?q=x")
    assert r.status_code == 200
    assert r.json()["item_id"] == 5
```

- **依赖覆盖**：用 `app.dependency_overrides[get_db] = fake_get_db` 把数据库等外部依赖替换成假实现，单测不碰真实库。
- **异步测试**：需要更精细控制时用 `httpx.ASGITransport(app=app)` 直接驱动 ASGI app，配合 `asyncio` 运行。

## Background Tasks

`BackgroundTasks` 适合请求返回后、同进程内执行的轻量后处理（发邮件、写审计日志），由 ASGI server 在响应发出后再跑：

```py
from fastapi import BackgroundTasks

def write_audit(msg: str):
    ...

@app.post("/")
async def root(background_tasks: BackgroundTasks):
    background_tasks.add_task(write_audit, "created")
    return {"ok": True}
```

它与 Celery 类重型任务队列（见 [MQ](/docs/CS/MQ/MQ.md)）的定位不同：BackgroundTasks 不保证重试、不跨进程、进程挂掉就丢；需要可靠投递/重试/定时，仍要上 broker 型队列。

## Configuration

FastAPI 自身没有配置系统（这点也和 Django 的 `settings.py` 不同），社区惯例是用 `pydantic-settings` 把环境变量收敛成一个带类型、可校验的对象：

```py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    database_url: str
    debug: bool = False
    jwt_secret: str

settings = Settings()
```

- 字段名默认映射到同名环境变量（`APP_` 前缀 + 大写），也可用 `alias` 自定义。
- 校验在**导入时**完成：缺变量或类型不对会立刻抛错，而不是等到第一个请求才暴露。
- 生产环境用真实环境变量注入，`env_file` 只用于本地开发；密钥绝不入库、不进镜像层。
- 区分环境靠 `APP_ENV` 之类的开关，而不是在代码里 `if settings.debug` 分叉业务流程。

## Observability

FastAPI 只提供挂载点，采集方案要自己选：

```py
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}
```

- **健康检查**：`/healthz` 供编排系统探活；区分 liveness（进程活着）与 readiness（依赖就绪，如数据库可连）两个端点更稳。写进 `include_in_schema=False` 可让它不出现在 OpenAPI 文档里。
- **日志**：用标准库 `logging` 或 `structlog` 输出结构化日志；请求 ID 由中间件注入并在响应头回传（见上文 `X-Process-Time` 中间件写法）。
- **指标**：`prometheus-client` 暴露 `/metrics`，注意用 `multiprocess` 模式配合多 worker 部署。
- **链路追踪**：OpenTelemetry 的 `opentelemetry-instrumentation-fastapi` 可自动埋点；跨服务传播的思路与 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的 B3 头是同一类问题。

## Deployment

### Multiple Workers

Uvicorn 自带多 worker 模式（用 **spawn** 而非 pre-fork，能在 Windows 上工作）：

```shell
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

需要进程守护与优雅重启时用 Gunicorn。**注意 worker 类的写法已变**：`uvicorn.workers` 模块自 Uvicorn 0.30.0 起**已弃用**并计划移除，官方要求改用独立包 `uvicorn-worker`：

```shell
pip install uvicorn-worker
gunicorn main:app -w 4 -k uvicorn_worker.UvicornWorker
```

类路径是 `uvicorn_worker.UvicornWorker`（下划线），不是旧的 `uvicorn.workers.UvicornWorker`。网上大量教程仍在用旧写法，它现在仍能跑但会打弃用警告。

Gunicorn 26 起还提供了**原生 ASGI worker**（`-k asgi` / `--worker-class asgi`），不再依赖 Uvicorn：

```shell
gunicorn main:app --worker-class asgi --workers 4
```

它支持 HTTP/1.1 keepalive、WebSocket 与 lifespan 协议，可用 `--asgi-loop uvloop` 换事件循环、`--asgi-lifespan` 控制 lifespan 探测；并发上限用 `--worker-connections` 而非 `--threads`（ASGI worker 下 `--threads` 无效）。

### Containerization

容器里用 `fastapi run`（等价于 `uvicorn`）监听 `0.0.0.0`，多副本交给编排器而非容器内多 worker：

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]
```

用 uv 的 `uv.lock` 保证构建可复现；`--frozen` 禁止在构建期改动锁文件。容器内通常只跑 1 个 worker，由 K8s ReplicaSet 做横向扩容——容器内多进程会让 HPA 的 CPU 指标失真，也拿不到单进程内存限额。

### Reverse Proxy

单机前置 [Nginx](/docs/CS/CN/nginx/nginx.md) 处理 TLS、静态文件和负载均衡，把 `/api` 反代到 Uvicorn（`proxy_pass http://127.0.0.1:8000`）。容器化部署时 Nginx 与 Uvicorn 分容器编排即可。

### Documentation and Debugging

启动后访问：

- `http://127.0.0.1:8000/docs` — Swagger UI，可直接发请求调试
- `http://127.0.0.1:8000/redoc` — ReDoc 文档
- `http://127.0.0.1:8000/openapi.json` — OpenAPI 3 schema，可用于生成客户端 SDK

生产环境建议关掉交互式文档（`FastAPI(docs_url=None, redoc_url=None)`），或用反向代理限制访问路径。

## OpenAPI Customization and SDK Generation

OpenAPI schema 是 FastAPI 的**契约产物**，不只是文档副产品——前后端、客户端 SDK、网关配置都从它派生。

自定义元信息与分组：

```py
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Item Service",
    version="1.0.0",
    openapi_tags=[{"name": "items", "description": "商品相关接口"}],
)
```

- **`openapi_tags`**：给 `tags` 配描述，在 Swagger UI 里显示为分组说明。
- **`openapi_extra`**：给单个路径操作塞厂商扩展字段（如 `x-internal: true`）。
- **统一错误响应**：用 `app.openapi_schema` 覆写生成的 schema，或在每个路由上用 `responses=` 声明常见错误码。

拿到 `/openapi.json` 后可生成客户端 SDK：

- `openapi-python-client`（基于 datamodel-code-generator）生成同步 Python 客户端；
- `openapi-generator` 生成 Java / TS / Go 等多语言客户端；
- `schemathesis` 拿 schema 做属性测试（property-based testing），自动生成边界用例。

契约一旦对外发布就该纳入版本管理：schema 变更等于接口变更，需评审与版本号同步。

## Links

- [README](/docs/CS/Python/README.md)
- [Typing](/docs/CS/Python/Typing.md)
- [Asyncio](/docs/CS/Python/Asyncio.md)
- [Packaging](/docs/CS/Python/Packaging.md)
- [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)
## References

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [FastAPI CLI 文档](https://fastapi.tiangolo.com/fastapi-cli/)
- [Starlette 文档](https://www.starlette.io/)
- [Pydantic 文档](https://docs.pydantic.dev/)
- [Uvicorn 文档](https://www.uvicorn.org/)
- [uvicorn-worker (PyPI)](https://pypi.org/project/uvicorn-worker/)
- [Gunicorn ASGI Worker](https://gunicorn.org/asgi/)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [Alembic 文档](https://alembic.sqlalchemy.org/)
