## Introduction

FastAPI 是一个用于构建 API 的现代、快速（高性能）的 Web 框架，专为 Python 设计。它充分利用了 Python 3.6+ 的类型提示（Type Hints） 特性，是目前 Python 生态中最受欢迎的 Web 框架之一。

核心特性：

- **高性能**：基于 ASGI，性能接近 Node.js 与 Go（[TechEmpower](https://www.techempower.com/benchmarks/) 中 Python 框架第一梯队）。
- **类型即文档**：函数签名的类型注解同时承担参数解析、数据校验与序列化，自动生成交互式文档（Swagger UI / ReDoc）。
- **开发效率高**：编辑器补全友好，样板代码少。

## Installation

```shell
uv add fastapi uvicorn
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

## Request

### Pydantic 请求体

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

### 参数来源

| 来源 | 声明方式 | 示例 |
|---|---|---|
| 路径参数 | 路径占位符 + 同名函数参数 | `/items/{item_id}` → `item_id: int` |
| 查询参数 | 普通函数参数（有默认值即可选） | `q: str \| None = None` |
| 请求体 | Pydantic Model 参数 | `item: Item` |
| Header | `Header()` | `user_agent: str = Header()` |
| Cookie | `Cookie()` | `session_id: str \| None = Cookie()` |
| 表单/文件 | `Form()` / `UploadFile` | `file: UploadFile` |

### 响应模型

通过 `response_model` 声明输出结构，可做字段过滤（如隐藏内部字段）和文档生成：

```py
class UserOut(BaseModel):
    username: str
    email: str

@app.get("/users/me", response_model=UserOut)
async def read_me():
    ...
```

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

## Async

FastAPI 同时支持 `async def` 和普通 `def` 路由：

- **`async def`**：路由内要 await 异步库（如 asyncpg、httpx.AsyncClient）时使用，全程跑在事件循环上，吞吐高。
- **普通 `def`**：FastAPI 自动放到线程池执行，避免阻塞事件循环——但如果内部调用同步阻塞库（如 psycopg2、requests），用普通函数更稳妥。

混用的关键约束：不要在 `async def` 里调用阻塞型同步库，否则会卡住整个 worker 的事件循环。Python 协程原理见 [Concurrency](/docs/CS/SE/Concurrency.md)。

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

### 中间件与生命周期

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

## Deployment

### 多 worker

生产环境用 Uvicorn 的多 worker 模式，或 Gunicorn 管理 Uvicorn worker（支持优雅重启）：

```shell
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### 反向代理

单机前置 [Nginx](/docs/CS/CN/nginx/nginx.md) 处理 TLS、静态文件和负载均衡，把 `/api` 反代到 Uvicorn（`proxy_pass http://127.0.0.1:8000`）。容器化部署时 Nginx 与 Uvicorn 分容器编排即可。

### 文档与调试

启动后访问：

- `http://127.0.0.1:8000/docs` — Swagger UI，可直接发请求调试
- `http://127.0.0.1:8000/redoc` — ReDoc 文档
- `http://127.0.0.1:8000/openapi.json` — OpenAPI 3 schema，可用于生成客户端 SDK

## Links

- [Python](/docs/CS/Python/README.md) — Python 笔记目录
- [LangChain](/docs/CS/Framework/LangTool/LangChain.md) — 同为 Python 生态框架
- [Nginx](/docs/CS/CN/nginx/nginx.md) — 生产环境反向代理
- [Concurrency](/docs/CS/SE/Concurrency.md) — 协程与并发模型对照

## References

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Starlette 文档](https://www.starlette.io/)
- [Pydantic 文档](https://docs.pydantic.dev/)
- [Uvicorn 文档](https://www.uvicorn.org/)
