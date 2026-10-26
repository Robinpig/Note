## Introduction

`BackgroundTasks` 适合请求返回后、同进程内执行的轻量后处理（发邮件、写审计日志），由 ASGI server 在响应发出后再跑。它与 Celery 类重型任务队列（见 [MQ](/docs/CS/MQ/MQ.md)）的定位不同：BackgroundTasks 不保证重试、不跨进程、进程挂掉就丢。

## Usage

```py
from fastapi import BackgroundTasks

def write_audit(msg: str):
    ...

@app.post("/")
async def root(background_tasks: BackgroundTasks):
    background_tasks.add_task(write_audit, "created")
    return {"ok": True}
```

`add_task(func, *args, **kwargs)` 把函数排进后台队列；响应正常返回后，ASGI server 依次执行这些任务。`func` 可以是普通函数或 `async def`（异步任务会在事件循环上 await）。

## Boundaries

| 维度 | BackgroundTasks | broker 队列（Celery / [MQ](/docs/CS/MQ/MQ.md)） |
| :--- | :--- | :--- |
| 进程 | 同进程 | 跨进程 worker |
| 可靠性 | 进程挂掉即丢，无重试 | broker 持久化、ack、重试 |
| 定时 | 不支持 | 支持（beat / 延时消息） |
| 适用 | 发邮件、审计、轻量后处理 | 可靠投递、重计算、定时任务 |

需要可靠投递 / 重试 / 定时，仍要上 broker 型队列，不要拿 BackgroundTasks 当任务队列用。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Testing](/docs/CS/Framework/FastAPI/Testing.md)
- [Architecture](/docs/CS/Framework/FastAPI/Architecture.md)
- [MQ](/docs/CS/MQ/MQ.md)

## References

- [FastAPI 官方文档：Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
