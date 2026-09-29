## Introduction

FastAPI 是一个用于构建 API 的现代、快速（高性能）的 Web 框架，专为 Python 设计。它充分利用了 Python 3.6+ 的类型提示（Type Hints） 特性，是目前 Python 生态中最受欢迎的 Web 框架之一。


## Installation

```shell
uv add  fastapi uvicorn
```


程序 main.py

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
unicorn main:app --reload
```


## Architecture





## Links
