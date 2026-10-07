## Introduction

一个用 Rust 编写的极速 Python 包和项目管理工具。

uv 的野心不是"更快的 pip"，而是**把 Python 版本、虚拟环境、依赖解析、锁文件、CLI 工具安装、打包发布收进同一个解析器**：它同时替代 `pip` + `venv` + `virtualenv` + `pyenv` + `pipx` + `poetry` 的职责。理解这一点才不会把它的两套接口（项目模式与 `uv pip` 兼容模式）混着用。

速度的来源不是 Rust 本身，而是三件事：**全局缓存 + 硬链接克隆**（同一份 wheel 解包一次，装到 N 个环境是 reflink/硬链接而非拷贝）、**Fork-Save 式并行解析与下载**、**UV_CACHE_DIR 里按包版本复用的解析结果**。

## Installation

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh

# windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

也随 `pipx`/`brew`/CI 镜像分发；装完 `uv --version` 确认。`uv self update` 自更新（包管理器装的不要用它）。

## 两套接口

| 模式 | 命令族 | 状态来源 | 用途 |
| :--- | :--- | :--- | :--- |
| 项目模式 | `uv init` / `add` / `remove` / `sync` / `lock` / `run` / `tree` / `export` | `pyproject.toml` + `uv.lock` | 日常开发、CI、可复现部署 |
| 兼容模式 | `uv pip install` / `compile` / `sync` / `list` | `requirements.txt` | 存量项目、只想要快、无锁文件场景 |
| 工具模式 | `uv tool install` / `uvx` | 隔离的临时环境 | 装并运行 CLI 工具（`ruff`、`black`），不污染项目 |
| 解释器管理 | `uv python install` / `list` / `find` | uv 自管的 Python 安装 | 让项目声明并自动获得所需 Python 版本 |

两者不要混用：项目模式下手写 `.venv` 里 `uv pip install` 的东西会在下次 `uv sync` 时被当成"多余包"处理。

## 项目工作流

```shell
uv init myapp && cd myapp          # 生成 pyproject.toml 与 hello.py
uv add "fastapi>=0.110" httpx      # 解析 + 写 pyproject + 更新 uv.lock + 同步 .venv
uv add --dev pytest ruff           # 开发依赖分组
uv add --optional ml torch         # optional-dependencies
uv lock --upgrade-package httpx    # 只升一个包的锁定版本
uv sync --frozen                   # CI/部署：严格按 uv.lock，不重新解析
uv run pytest                      # 在项目的 .venv 里执行，缺环境时自动 sync
uv tree                            # 依赖树：谁把哪个包拖进来的
uv export --format requirements-txt > requirements.txt   # 给只能吃 requirements 的平台
uv remove httpx                    # 删依赖并重新解析
```

关键约定：`pyproject.toml` 写**意图**（版本范围），`uv.lock` 写**事实**（确切版本 + 哈希 + 全平台 resolution）。锁文件要提交进仓库；`uv.lock` 是跨平台单文件，不要按平台各生成一份。`uv run` 会顺带检查锁文件是否过期，`--frozen` 跳过、`--no-sync` 不装。

单文件脚本的依赖可以内联声明（PEP 723），不建项目也能跑：

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "rich"]
# ///
import httpx
...
```

```shell
uv run fetch.py            # 解析内联依赖到临时环境后执行
uvx ruff check .           # 一次性运行第三方 CLI，等价 uv tool run
```

## 环境变量与调试

| 变量 | 作用 |
| :--- | :--- |
| `UV_PROJECT_ENVIRONMENT` | 把 `.venv` 换到别的路径（如 `.venv-313`） |
| `UV_CACHE_DIR` | 缓存目录，CI 里挂载复用 |
| `UV_PYTHON_INSTALL_DIR` | uv 安装的 Python 放哪 |
| `UV_NO_CACHE` | 排障时用，绕过缓存复现问题 |
| `UV_INDEX_URL` / `UV_EXTRA_INDEX_URL` | 换镜像源或私有 index |
| `UV_CONCURRENT_DOWNLOADS` | 并发下载数，代理/镜像限速时调小 |

解析结果诡异时用 `uv pip compile --verbose` 或 `uv add --dry-run` 看决策；`uv cache clean <pkg>` 只清单个包缓存。

## 与 conda 的分工

uv 管的是 Python 包与 Python 解释器本身，**不解析原生库依赖**（CUDA、`libgdal`、BLAS 变体）。需要这类软件栈时两条路：conda 负责底座、uv 负责项目依赖；或者干脆用提供了预编译 wheel 的包（多数场景已够）。对照与混用风险见 [Packaging](/docs/CS/Python/Packaging.md) 与 [conda](/docs/CS/Python/conda.md)。

## Links

- [Python](/docs/CS/Python/Python.md)
- [Packaging](/docs/CS/Python/Packaging.md)
- [conda](/docs/CS/Python/conda.md)
- [Module](/docs/CS/Go/Module.md)
- [README](/docs/CS/Python/README.md)

## References

- [uv documentation](https://docs.astral.sh/uv/)
- [uv Projects concept](https://docs.astral.sh/uv/concepts/projects/)
- [uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/)
- [PEP 723 – Inline script metadata](https://peps.python.org/pep-0723/)
